"""Backtest, on a repository's own history, the two claims behind `tessri triage` and `tessri impact`: that files
ordered by recent activity and then by the size of the change are where a fix lands next more often than files
ordered by size alone, and that files one import apart change together far more often than files that merely share
a directory.

Nothing is read from after each change. A row is one code file a change touched, scored with what git knew when the
change landed (commits touching the file in the active window before it, the lines the change moved), and the
outcome is whether a commit whose subject says fix or revert touched the file within the window after it. The
import graph is built from the tree as it stood at each month's start, and the pairs it relates are compared with
the pairs the month's changes touched together.

    python tools/backtest.py path/to/repository --months 12
    python tools/backtest.py path/to/repository --format json --out backtest.json

Zero dependencies, like the tool; it uses the package in this checkout (or the installed one) to tell code files from
the rest and to build the import graph. Reading the history of a few thousand commits takes seconds; each month's
graph costs one analysis of the tree.
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import datetime as dt
import json
import math
import subprocess
import sys
import tempfile
import textwrap
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tessri import config, gitlog, inventory, since  # noqa: E402  (the package in this checkout)
from tessri.analyze import analyze  # noqa: E402

DAY = 86400
BULK = 50  # a change touching more code files than this says little about which pairs belong together
WIDTH = 110  # the text output's prose is wrapped here
ORDERS = {  # what a file is sorted by, highest first; the first is what `triage` does
    "activity, then size (triage)": lambda r: (r.commits, r.lines),
    "size": lambda r: (r.lines,),
    "activity": lambda r: (r.commits,),
    "fixes, then activity, then size": lambda r: (r.fixes, r.commits, r.lines),
    "dependents, then size": lambda r: (r.dependents or 0, r.lines),
}
NEEDS_GRAPH = {"dependents, then size"}  # orders that read the import graph at the month's start
PAIRS = ("one import apart", "two imports apart", "same directory", "unrelated")


class BacktestError(ValueError):
    """The repository cannot be backtested as asked; one sentence for the person."""


@dataclass
class Change:
    sha: str
    when: int  # commit time, epoch seconds
    subject: str
    lines: dict[str, int] = field(default_factory=dict)  # code file -> lines added + deleted; deleted files left out
    touched: set[str] = field(default_factory=set)  # every code file, deleted ones included


@dataclass(frozen=True)
class Row:
    sha: str
    path: str
    lines: int
    commits: int  # commits touching the file in the active window before the change
    fixes: int  # of those, fix or revert commits
    fixed: bool  # a fix or revert commit touched the file in the window after the change
    dependents: int | None = None  # code files importing it in the tree at the month's start; None without the graph


@dataclass
class Snapshot:
    """The tree before a month's first change: its code files (tests apart), which of them are one import
    statement apart, and how many files import each."""

    tree: str
    files: list[str]
    adjacent: dict[str, set[str]]
    inbound: dict[str, int]


# --- git ------------------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise BacktestError(res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"git {args[0]} failed")
    return res.stdout


def _records(root: Path, *args: str) -> list[tuple[list[str], list[str]]]:
    """`git log -z` with a `\\x1e` header per commit: (header fields, the records that follow) per commit."""
    out: list[tuple[list[str], list[str]]] = []
    for record in _git(root, "log", "-z", "--format=%x1e%H%x09%ct%x09%s", *args).split("\0"):
        record = record.lstrip("\n")
        if record.startswith("\x1e"):
            out.append(((record[1:].split("\t", 2) + ["", ""])[:3], []))
        elif record and out:
            out[-1][1].append(record)
    return out


def _is_code(path: str, skip: list[str]) -> bool:
    lang = inventory.language_of(path)
    return lang is not None and lang.kind == "code" and not inventory.matches(path, skip)


def changes(root: Path, rev: str, skip: list[str]) -> list[Change]:
    """The first-parent commits up to `rev`, oldest first, each with the code files it touched: on a branch that
    squashes or rebases that is every change, and a merge commit counts as the whole of what it merged."""
    walk = ("--first-parent", "--diff-merges=first-parent", "-M", rev)
    found: dict[str, Change] = {}
    for (sha, stamp, subject), records in _records(root, "--name-status", *walk):
        change = found[sha] = Change(sha, int(stamp) if stamp.isdigit() else 0, subject)
        for status, path, _old in gitlog._entries(records):
            if not _is_code(path, skip):
                continue
            change.touched.add(path)
            if status[:1] != "D":
                change.lines[path] = 0
    for (sha, _, _), records in _records(root, "--numstat", *walk):
        change = found[sha]
        i = 0
        while i < len(records):
            added, _, rest = records[i].partition("\t")
            deleted, _, path = rest.partition("\t")
            i += 1
            if not path and i + 1 < len(records):  # a rename: the old and the new name follow as records of their own
                path = records[i + 1]
                i += 2
            if path in change.lines:
                change.lines[path] = int(added) + int(deleted) if added.isdigit() and deleted.isdigit() else 0
    return sorted(found.values(), key=lambda c: c.when)


def events(root: Path, rev: str, skip: list[str]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Per code file, the sorted commit times of every commit touching it up to `rev`, and of those whose subject
    says fix or revert (the rule `triage` uses). A moved file's earlier history stays under its old name."""
    touches: dict[str, list[int]] = defaultdict(list)
    fixes: dict[str, list[int]] = defaultdict(list)
    for (_, stamp, subject), paths in _records(root, "--no-merges", "--name-only", "-M", rev):
        when = int(stamp) if stamp.isdigit() else 0
        repair = bool(gitlog.FIX_SUBJECT.match(subject))
        for path in paths:
            if _is_code(path, skip):
                touches[path].append(when)
                if repair:
                    fixes[path].append(when)
    for listing in (touches, fixes):
        for times in listing.values():
            times.sort()
    return touches, fixes


# --- the rows and the orders -----------------------------------------------------------------------------------------


def _between(times: list[int], start: int, end: int) -> int:
    """How many of the sorted `times` fall in the half-open [start, end)."""
    return bisect.bisect_left(times, end) - bisect.bisect_left(times, start)


def month_of(when: int) -> str:
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%Y-%m")


def _day(when: int) -> str:
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%Y-%m-%d")


def select(all_changes: list[Change], months: int, window: int, active: int) -> dict[str, list[Change]]:
    """The changes to score, by month, oldest first: those whose outcome window closes before the newest commit and
    whose active window lies inside the history, in the last `months` months of them (0 for all)."""
    if not all_changes:
        raise BacktestError("no commits")
    first, last = all_changes[0].when, all_changes[-1].when
    eligible = [c for c in all_changes if c.when >= first + active * DAY and c.when <= last - window * DAY]
    if not eligible:
        raise BacktestError(f"no change has {active} days of history before it and {window} days after it; the history spans {_day(first)} to {_day(last)}")
    grouped: dict[str, list[Change]] = defaultdict(list)
    for c in eligible:
        grouped[month_of(c.when)].append(c)
    keys = sorted(grouped)[-months:] if months > 0 else sorted(grouped)
    return {k: grouped[k] for k in keys}


def rows_of(change: Change, touches: dict[str, list[int]], fixes: dict[str, list[int]], window: int, active: int, inbound: dict[str, int] | None = None) -> list[Row]:
    out = []
    for path, lines in sorted(change.lines.items()):
        before = (change.when - active * DAY, change.when)  # the change itself, at `when`, is outside
        out.append(Row(
            change.sha, path, lines,
            _between(touches.get(path, []), *before),
            _between(fixes.get(path, []), *before),
            _between(fixes.get(path, []), change.when + 1, change.when + window * DAY + 1) > 0,
            inbound.get(path, 0) if inbound is not None else None,
        ))  # fmt: skip
    return out


def auc(scored: list[tuple[tuple, bool]]) -> float | None:
    """The probability that a file later fixed is sorted above one that was not, ties counting half (the
    Mann-Whitney statistic); None when one of the two outcomes is missing."""
    positives = sum(1 for _, fixed in scored if fixed)
    negatives = len(scored) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(scored, key=lambda s: s[0])
    ranks = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        ranks += (i + 1 + j) / 2 * sum(1 for k in range(i, j) if ordered[k][1])  # ranks i+1 .. j, averaged over the tie
        i = j
    return (ranks - positives * (positives + 1) / 2) / (positives * negatives)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def orders(months: dict[str, list[Change]], touches, fixes, window: int, active: int, snapshots: dict[str, Snapshot] | None = None) -> tuple[dict, list[dict]]:
    """Every order's AUC pooled over all rows, per month, and within each change that had both outcomes. The
    orders that read the import graph are left out without `snapshots`."""
    per_change: dict[str, list[Row]] = {}
    for month, found in months.items():
        inbound: dict[str, int] | None = None
        if snapshots is not None:
            inbound = snapshots[month].inbound if month in snapshots else {}  # a month without a tree before it: no dependents known
        for change in found:
            per_change[change.sha] = rows_of(change, touches, fixes, window, active, inbound)
    by_month = {m: [r for c in found for r in per_change[c.sha]] for m, found in months.items()}
    rows = [r for found in by_month.values() for r in found]
    if not rows:
        raise BacktestError("the selected changes touched no code file")
    summary = {
        "count": len(rows),
        "changes": sum(len(found) for found in months.values()),
        "months": list(months),
        "fixed": sum(1 for r in rows if r.fixed),
    }
    size = {m: auc([(ORDERS["size"](r), r.fixed) for r in found]) for m, found in by_month.items()}
    out = []
    for name, key in ORDERS.items():
        if name in NEEDS_GRAPH and snapshots is None:
            continue
        monthly = {m: auc([(key(r), r.fixed) for r in found]) for m, found in by_month.items()}
        within = [a for a in (auc([(key(r), r.fixed) for r in found]) for found in per_change.values()) if a is not None]
        out.append({
            "order": name,
            "pooled": auc([(key(r), r.fixed) for r in rows]),
            "months": monthly,
            "mean_of_months": _mean([a for a in monthly.values() if a is not None]),
            "ahead_of_size": sum(1 for m, a in monthly.items() if a is not None and size[m] is not None and a > size[m]),
            "months_compared": sum(1 for m, a in monthly.items() if a is not None and size[m] is not None),
            "within_change": {"mean": _mean(within), "changes": len(within)},
        })  # fmt: skip
    return summary, out


# --- what changes together ---------------------------------------------------------------------------------------------


def snapshot(root: Path, cfg: config.Config, skip: list[str], sha: str, now: int) -> Snapshot:
    """The tree at `sha`, analysed in a scratch directory with the repository untouched: its code files (tests
    apart), the pairs one import statement apart in either direction, and how many files import each."""
    quiet = dataclasses.replace(cfg, review_days=0)
    with tempfile.TemporaryDirectory(prefix="tessri-backtest-") as scratch:
        since.extract_tree(root, sha, "", Path(scratch), skip)
        a = analyze(Path(scratch), quiet, now=now)
    files = sorted(p for p, r in a.records.items() if r.kind == "code" and r.analyzer and not r.is_test)
    keep = set(files)
    adjacent: dict[str, set[str]] = {p: set() for p in files}
    inbound = {p: 0 for p in files}
    for src, targets in a.graph.edges.items():
        for dst in targets - a.graph.indirect.get(src, set()) - {src}:
            if src in keep and dst in keep:
                adjacent[src].add(dst)
                adjacent[dst].add(src)
                inbound[dst] += 1
    return Snapshot(sha, files, adjacent, inbound)


def snapshots(root: Path, cfg: config.Config, skip: list[str], all_changes: list[Change], months: dict[str, list[Change]], log=None) -> dict[str, Snapshot]:
    """One snapshot per month, of the tree before the month's first change; a month that starts at the first
    commit has none."""
    index = {c.sha: i for i, c in enumerate(all_changes)}
    out: dict[str, Snapshot] = {}
    for n, (month, found) in enumerate(months.items(), 1):
        at = index[found[0].sha] - 1
        if at < 0:
            continue
        base = all_changes[at]
        if log:
            log(f"backtest: graph at {month} ({n} of {len(months)}), tree {base.sha[:9]}")
        out[month] = snapshot(root, cfg, skip, base.sha, found[0].when)
    return out


def pair_classes(files: list[str], adjacent: dict[str, set[str]]) -> tuple[dict[frozenset, str], dict[str, int]]:
    """Each related pair's class, and how many pairs each class holds (the unrelated ones counted, not listed)."""
    classes: dict[frozenset, str] = {}
    for a in files:
        seen = {a: 0}
        queue = deque([a])
        while queue:
            node = queue.popleft()
            if seen[node] >= 2:
                continue
            for nxt in adjacent[node]:
                if nxt not in seen:
                    seen[nxt] = seen[node] + 1
                    queue.append(nxt)
        for b, dist in seen.items():
            if dist:
                classes[frozenset((a, b))] = PAIRS[dist - 1]
    by_dir: dict[str, list[str]] = defaultdict(list)
    for p in files:
        by_dir[p.rpartition("/")[0]].append(p)
    for members in by_dir.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                classes.setdefault(frozenset((a, b)), "same directory")
    counts = {name: 0 for name in PAIRS}
    for name in classes.values():
        counts[name] += 1
    counts["unrelated"] = math.comb(len(files), 2) - sum(counts.values())
    return classes, counts


def cochange(snapshots: dict[str, Snapshot], months: dict[str, list[Change]]) -> dict:
    """Per month: the pairs of code files the tree related at the month's start, by class, against the pairs one
    change of the month touched together. A change touching more than BULK code files is left out."""
    per_month: dict[str, dict] = {}
    for month, found in months.items():
        if month not in snapshots:
            continue  # the month starts at the first commit: no tree before it
        snap = snapshots[month]
        keep = set(snap.files)
        classes, counts = pair_classes(snap.files, snap.adjacent)
        together: set[frozenset] = set()
        bulk = 0
        for change in found:
            inside = sorted(p for p in change.touched if p in keep)
            if len(inside) > BULK:
                bulk += 1
                continue
            for i, a in enumerate(inside):
                for b in inside[i + 1:]:
                    together.add(frozenset((a, b)))
        hits = {name: 0 for name in PAIRS}
        for pair in together:
            hits[classes.get(pair, "unrelated")] += 1
        per_month[month] = {"tree": snap.tree, "files": len(snap.files), "changes": len(found) - bulk, "bulk": bulk, "pairs": counts, "cochanged": hits}
    pooled = []
    for name in PAIRS:
        pairs = sum(m["pairs"][name] for m in per_month.values())
        hit = sum(m["cochanged"][name] for m in per_month.values())
        pooled.append({"pairs": name, "count": pairs, "cochanged": hit, "rate": hit / pairs if pairs else None})
    base_rate = pooled[-1]["rate"]
    for entry in pooled:
        entry["ratio"] = entry["rate"] / base_rate if entry["rate"] is not None and base_rate else None
        monthly = []
        for m in per_month.values():
            u = m["cochanged"]["unrelated"] / m["pairs"]["unrelated"] if m["pairs"]["unrelated"] else 0
            if m["pairs"][entry["pairs"]] and u:
                monthly.append(m["cochanged"][entry["pairs"]] / m["pairs"][entry["pairs"]] / u)
        entry["ratio_range"] = [min(monthly), max(monthly)] if monthly else None
    return {"bulk": BULK, "months": per_month, "pooled": pooled}


# --- the run and its rendering ----------------------------------------------------------------------------------------


def run(root: Path, rev: str = "HEAD", months: int = 12, window: int = 30, active: int = 90, graph: bool = True, log=None) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        raise BacktestError(f"{root}: not a directory")
    sha = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()
    cfg = config.load(root)
    skip = [*inventory.DEFAULT_EXCLUDES, *cfg.exclude]
    all_changes = changes(root, sha, skip)
    touches, fixes = events(root, sha, skip)
    chosen = select(all_changes, months, window, active)
    snaps = snapshots(root, cfg, skip, all_changes, chosen, log) if graph else None
    summary, scored = orders(chosen, touches, fixes, window, active, snaps)
    result = {
        "kind": "backtest",
        "root": str(root),
        "rev": sha,
        "history": {"first": _day(all_changes[0].when), "last": _day(all_changes[-1].when), "changes": len(all_changes)},
        "settings": {"months": months, "window_days": window, "active_days": active, "fix_subject": gitlog.FIX_SUBJECT.pattern},
        "rows": summary,
        "orders": scored,
    }
    if snaps is not None:
        result["cochange"] = cochange(snaps, chosen)
    return result


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _table(head: list[str], body: list[list[str]], right: set[int]) -> str:
    widths = [max(len(row[i]) for row in [head, *body]) for i in range(len(head))]
    lines = []
    for row in [head, *body]:
        cells = [c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(row)]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def text(result: dict) -> str:
    s, rows, h = result["settings"], result["rows"], result["history"]
    first, last = rows["months"][0], rows["months"][-1]
    span = first if first == last else f"{first} to {last}"
    out = [
        f"Tessri backtest of {result['root']} at {result['rev'][:9]} (history {h['first']} to {h['last']}, {h['changes']:,} changes on the first-parent line)",
        "",
        textwrap.fill(
            f"Rows: {rows['count']:,} code file{'s' if rows['count'] != 1 else ''} touched by {rows['changes']:,} change{'s' if rows['changes'] != 1 else ''} "
            f"in {len(rows['months'])} month{'s' if len(rows['months']) != 1 else ''} ({span}); the outcome, a fix or revert "
            f"commit touching the file within {s['window_days']} days, holds for {rows['fixed'] / rows['count']:.0%} of them. Activity is commits in the "
            f"{s['active_days']} days before the change; a deleted file is left out; a moved file counts under its new name.",
            WIDTH,
        ),
        "",
        _table(
            ["Order", "pooled AUC", "mean of months", "ahead of size", "within a change (changes)"],
            [[o["order"], _num(o["pooled"]), _num(o["mean_of_months"]), f"{o['ahead_of_size']} of {o['months_compared']}" if o["order"] != "size" else "-",
              f"{_num(o['within_change']['mean'])} ({o['within_change']['changes']})"] for o in result["orders"]],
            {1, 2, 3, 4},
        ),
    ]  # fmt: skip
    co = result.get("cochange")
    if co:
        bulk = sum(m["bulk"] for m in co["months"].values())
        out += [
            "",
            textwrap.fill(
                f"Pairs of code files (tests apart) in the tree at each month's start, and whether one change of the month touched both; "
                f"{bulk} change{'s' if bulk != 1 else ''} touching more than {co['bulk']} code files left out.",
                WIDTH,
            ),
            "",
            _table(
                ["Pairs", "pairs", "co-changed", "rate", "x unrelated", "over the months"],
                [[e["pairs"], f"{e['count']:,}", f"{e['cochanged']:,}", "-" if e["rate"] is None else f"{e['rate']:.2%}", _num(e["ratio"], 1),
                  "-" if not e["ratio_range"] else f"{e['ratio_range'][0]:.1f} to {e['ratio_range'][1]:.1f}"] for e in co["pooled"]],
                {1, 2, 3, 4, 5},
            ),
        ]  # fmt: skip
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the order `tessri triage` uses and the import graph's claim to predict co-change, on a repository's history.")
    parser.add_argument("path", help="the repository")
    parser.add_argument("--rev", default="HEAD", help="the branch or commit whose first-parent history is read (default HEAD)")
    parser.add_argument("--months", type=int, default=12, help="how many of the last months to score (default 12; 0 for all)")
    parser.add_argument("--window", type=int, default=30, help="days after a change in which a fix counts (default 30)")
    parser.add_argument("--active-days", type=int, default=90, help="days before a change that count as activity (default 90, like triage)")
    parser.add_argument("--no-graph", action="store_true", help="skip the co-change part, which analyses the tree once per month")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--out", help="write here instead of stdout")
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.path), args.rev, args.months, args.window, args.active_days, not args.no_graph, log=lambda line: print(line, file=sys.stderr))
    except (BacktestError, config.ConfigError, since.CheckError) as exc:
        print(f"backtest: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2) + "\n" if args.format == "json" else text(result)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
