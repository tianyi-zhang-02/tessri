"""Change triage: for a branch, a range or uncommitted work, which files deserve a human first, what else the
change can ripple into, and who is able to look.

The order is the one backtests on three repositories found hard to beat (`tools/backtest.py`, which runs the
test on any repository): files that were committed to most in the last 90 days first, then by how much this change
touches. Which of those commits were fixes added nothing on two of them and a point on the third, so fix history is shown but does not move a file; the
number of dependents ranked far below activity, so blast radius is shown as what a mistake would cost, and ownership
as who can catch it, which no such score measures. History is read up to the base of the change, so the change's own
commits neither count as activity nor make their author an owner.
"""

from __future__ import annotations

import dataclasses
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from . import companions, gitlog, inventory, mentions, meta, symbols, __version__
from . import since as since_mod
from .analyze import Analysis, analyze
from .config import Config
from .model import SCHEMA_VERSION
from .modules import assign
from .ownership import LISTED_MIN, UNOWNED, owner_rows, rollup

RIPPLE_HOPS = 2  # on one repository, files one import apart changed together 18 times as often as unrelated ones, two apart 9 times, the same directory twice (tools/backtest.py)
TEST_HOPS = 3
EXAMPLES = 3
REVIEWERS_LISTED = 3
LISTED = 8


class TriageError(ValueError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> str:
    try:
        res = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TriageError(f"git could not run: {exc}") from exc
    if check and res.returncode != 0:
        raise TriageError((res.stderr.strip().splitlines() or ["git failed"])[-1])
    return res.stdout


def resolve_base(root: Path, since: str) -> tuple[str, str]:
    """(commit to compare with, HEAD): the point where `since` and HEAD part, as a pull request would be judged."""
    try:
        base, head, _prefix = since_mod.resolve_base(root, since)
    except since_mod.CheckError as exc:
        raise TriageError(str(exc).replace("check needs", "triage needs", 1)) from exc
    return base, head


def _diff(root: Path, base: str) -> dict[str, gitlog.FileChange]:
    """Path -> what changed between `base` and the working tree, untracked files included; a file git sees as moved is
    one entry under its new name, with the lines edited on the way."""
    found = gitlog.diff(root, base)
    if found is None:
        raise TriageError("git could not read what changed since the base")
    return found


def _authors(root: Path, base: str, dirty: bool) -> dict[str, str]:
    """identity -> name for the people who wrote the change: its commits, and whoever is configured here when work is uncommitted."""
    found: dict[str, str] = {}
    for line in _git(root, "log", "--no-merges", "--format=%aN%x09%aE", f"{base}..HEAD").splitlines():
        name, _, email = line.partition("\t")
        if name and not gitlog.is_ignored(name, email, ()):
            found.setdefault(gitlog.identity(name, email), name)
    if dirty:
        name = _git(root, "config", "user.name", check=False).strip()
        email = _git(root, "config", "user.email", check=False).strip()
        if name:
            found.setdefault(gitlog.identity(name, email), name)
    return found


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _reverse(a: Analysis) -> dict[str, set[str]]:
    """file -> files that import it by statement (a package's `__init__` running on the way does not count)."""
    g = a.graph
    rev: dict[str, set[str]] = defaultdict(set)
    for src, targets in g.edges.items():
        for dst in targets - g.indirect.get(src, set()) - {src}:
            rev[dst].add(src)
    return rev


def _reach(rev: dict[str, set[str]], start: str, hops: int) -> dict[str, int]:
    seen = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if seen[node] >= hops:
            continue
        for nxt in rev.get(node, ()):
            if nxt not in seen:
                seen[nxt] = seen[node] + 1
                queue.append(nxt)
    del seen[start]
    return seen


def compute(root: Path, cfg: Config, since: str | None = None, now: float | None = None, analysis: Analysis | None = None) -> dict:
    """The triage of the change between `since` (`since.default_since` when None) and the working tree, as the
    JSON-ready dict the commands print. `analysis` is the working tree analysed with history read up to the base and
    review load off, when the caller has made it already (`brief` makes one for triage and check); otherwise it is
    made here."""
    root = Path(root).resolve()
    if since is None:
        since = since_mod.default_since(root)
    base, head = resolve_base(root, since)
    diff = _diff(root, base)
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal").strip())
    a = analysis if analysis is not None else analyze(root, dataclasses.replace(cfg, review_days=0), now=now, rev=base)
    if a.activity is None or a.ownership is None:
        raise TriageError("triage needs git history")
    own, g = a.ownership, a.graph
    authors = _authors(root, base, dirty)
    skip = [*inventory.DEFAULT_EXCLUDES, *cfg.exclude]

    code: dict[str, gitlog.FileChange] = {}
    other_files = other_lines = 0
    for path, change in diff.items():
        if inventory.matches(path, skip):
            continue
        lang = inventory.language_of(path)
        if lang is not None and lang.kind == "code":
            code[path] = change
        else:
            other_files += 1
            other_lines += change.lines

    def is_test(path: str) -> bool:
        return a.records[path].is_test if path in a.records else path in g.tests

    rev = _reverse(a)
    pool = [p for p, r in a.records.items() if r.kind == "code" and r.analyzer and not r.is_test]
    module_of = assign(pool)
    changed = set(code)
    ripple: dict[str, int] = {}
    tests: dict[str, int] = {}
    test_reach: dict[str, dict[str, int]] = defaultdict(dict)  # per changed file: the tests that reach it, with the distance
    rows = []
    for path, change in code.items():
        added, deleted, state = change.added, change.deleted, change.state
        rec = a.records.get(path)
        act = a.activity.files.get(path)
        fixes = act.fixes_90 if act else 0
        busy = act.commits_active if act else 0
        found = own.files.get(path) if rec else None
        shares = found.shares if found else {}
        holders = {who for who, s in shares.items() if s >= LISTED_MIN} or ({max(shares, key=lambda w: (shares[w], w))} if shares else set())
        direct = deeper = 0
        if rec and rec.analyzer:
            for other, dist in _reach(rev, path, max(RIPPLE_HOPS, TEST_HOPS)).items():
                if is_test(other):
                    if dist <= TEST_HOPS:
                        tests[other] = min(tests.get(other, 99), dist)
                        test_reach[path][other] = dist
                    continue
                if dist <= RIPPLE_HOPS:
                    if dist == 1:
                        direct += 1
                    else:
                        deeper += 1
                    if other not in changed:
                        ripple[other] = min(ripple.get(other, 99), dist)
        flags = []
        if state == "added" or (rec is not None and act is None):
            flags.append("new file")
        if state == "deleted":
            flags.append("deleted")
        if state == "moved":
            flags.append("moved")
        if found is not None and found.state == UNOWNED:
            flags.append("no active owner")
        if authors and holders and not (holders & set(authors)):
            flags.append("author is not among the owners")
        if rec and rec.status == "ORPHAN":
            flags.append("orphan: nothing reaches it")
        if rec is not None and rec.is_test:
            flags.append("test file")
        fresh = state == "added" or (rec is not None and act is None)
        tier = "busy" if busy else "new" if fresh else "quiet"
        lang = rec.language if rec else (found_lang.name if (found_lang := inventory.language_of(path)) else None)
        row = {
            "path": path,
            "change": state,
            "added": added,
            "deleted": deleted,
            "lines": added + deleted,
            "language": lang,
            "test": bool(rec.is_test) if rec else False,
            "tier": tier,
            "fixes_90": fixes,
            "fixes_year": act.fixes_year if act else 0,
            "commits_active": busy,
            "commits_year": act.commits_year if act else 0,
            "last_commit": _day(act.last) if act else None,
            "owners": owner_rows(own.owners(shares)) if shares else [],
            "ownership": found.state if found else None,
            "dependents": {"direct": direct, "within_2": direct + deeper},
            "flags": flags,
        }
        if change.origin:
            row["from"] = change.origin
        rows.append(row)
    by_path = {r["path"]: r for r in rows}
    rows.sort(key=lambda r: (-r["commits_active"], -r["lines"], r["path"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    # what the change did to each file's definitions: the functions and classes its hunks touch, from Python's parser
    for path, s in symbols.compute(root, base, [(r["path"], r["change"], r.get("from"), r["language"]) for r in rows]).items():
        by_path[path]["symbols"] = s
    # and which of the tests that reach each file use the names of those definitions in their code
    mentions.compute(root, rows, test_reach, {t: a.records[t].language if t in a.records else None for near in test_reach.values() for t in near})
    # and what usually changes with each file, that this change leaves untouched
    usually = companions.compute(root, base, a.now, rows, set(diff), a.records)

    # who can look: the people, other than the authors, who committed to the changed files in the last year or hold a share of
    # them, most commits first: on two repositories' pull requests that count matched who reviewed better than the share did
    # (docs/guide/reviewer-match.md); the share orders the rest
    commits_to: dict[str, set[int]] = defaultdict(set)
    weight: dict[str, float] = defaultdict(float)
    covers: dict[str, set[str]] = defaultdict(set)
    nobody_else: list[str] = []
    for row in rows:
        found = own.files.get(row["path"])
        shares = found.shares if found else {}
        recent = a.activity.recent.get(row["path"], {})
        able = [who for who in sorted({who for who, s in shares.items() if s >= LISTED_MIN} | set(recent)) if own.is_active(who) and who not in authors]
        if shares and not able:
            nobody_else.append(row["path"])
        for who in able:
            commits_to[who] |= recent.get(who, set())
            weight[who] += row["lines"] * shares.get(who, 0.0)
            covers[who].add(row["path"])
    reviewers = [
        {"name": own.authors[who].name, "files": len(covers[who]), "commits": len(commits_to[who]), "idle_days": own.idle_days(who), "weight": round(weight[who], 1)}
        for who in sorted(covers, key=lambda who: (-len(commits_to[who]), -weight[who], own.authors[who].name))[:REVIEWERS_LISTED]
    ]

    # the repository's regulars: who committed most, repository-wide, in the active window; where a few people review
    # everything they are the reviewers whatever the files, and on a small repository they beat the file-level list
    window = sum(au.commits_active for au in own.authors.values())
    busy = sorted((who for who, au in own.authors.items() if au.commits_active), key=lambda who: (-own.authors[who].commits_active, own.authors[who].name))
    regulars = {
        "window_days": cfg.active_days,
        "commits": window,
        "committers": len(busy),
        "people": [{"name": own.authors[who].name, "commits": own.authors[who].commits_active, "share": round(own.authors[who].commits_active / window, 2)} for who in busy if who not in authors][:REVIEWERS_LISTED],
    }

    by_module: dict[str, dict[str, int]] = defaultdict(lambda: {"direct": 0, "second": 0})
    for other, dist in ripple.items():
        by_module[module_of.get(other, ".")]["direct" if dist == 1 else "second"] += 1
    areas: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "lines": 0})
    area_of = assign({*pool, *code})
    for row in rows:
        slot = areas[area_of.get(row["path"], ".")]
        slot["files"] += 1
        slot["lines"] += row["lines"]
    nearest = sorted(tests, key=lambda p: (tests[p], p))

    notes = [
        "Files are ordered by how many commits touched them in the last 90 days, then by how much this change touches. In backtests on three repositories "
        "that predicted later fixes better than the size of the change alone; it says where trouble tends to be, not that this change is wrong. "
        "Fix and revert history is shown but does not reorder: it added little or nothing beyond activity.",
        "Dependents, tests and owners are context: they show what a mistake could reach and who is able to look; dependents predicted later fixes far less well than activity, and ownership is not a prediction at all. "
        "Dependents are static imports; dynamic loading and consumers outside the repository are invisible.",
        "History is read up to the base of the change and under the name each file has now, so a moved file keeps its past, "
        "the change's own commits do not count as trouble and its authors do not count as owners.",
        "A definition is named in a test when the identifier appears in the test's code, strings and comments apart; that is a mention, not an "
        "assertion, and a test can exercise code without naming it.",
        f"A companion is a file that changed in at least half of a changed file's commits in the last {gitlog.COMPANION_DAYS} days (three at least; merges and bulk commits apart), "
        "read up to the base under the name each file has now, and that this change leaves untouched: a prompt to check whether it should have changed too, not a rule that it must.",
    ]
    if not a.activity.files:
        notes.append("The repository has little history, so the ordering falls back to the size of the change.")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "tessri", "version": __version__},
        "generated_at": datetime.fromtimestamp(a.now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {"name": root.name},
        "kind": "triage",
        "meta": meta.of(a, change={"since": since, "base": base, "head": head, "uncommitted": dirty}),
        "change": {"since": since, "base": base[:9], "head": head[:9], "uncommitted": dirty, "authors": sorted(authors.values())},
        "summary": {
            "files": len(rows),
            "lines": sum(r["lines"] for r in rows),
            "recently_fixed": sum(1 for r in rows if r["fixes_90"]),
            "busy": sum(1 for r in rows if r["tier"] == "busy"),
            "new": sum(1 for r in rows if "new file" in r["flags"]),
            "moved": sum(1 for r in rows if "moved" in r["flags"]),
            "no_active_owner": sum(1 for r in rows if "no active owner" in r["flags"]),
            "nobody_else_can_look": len(nobody_else),
            "other_files": other_files,
            "other_lines": other_lines,
            "areas": len(areas),
            "ripple": {"direct": sum(1 for d in ripple.values() if d == 1), "second": sum(1 for d in ripple.values() if d == 2)},
            "tests": len(tests),
            "definitions": mentions.summary(rows),
            "companions": len(usually),
        },
        "files": rows,
        "companions": usually,
        "areas": [{"path": k, **v} for k, v in sorted(areas.items(), key=lambda kv: (-kv[1]["lines"], kv[0]))],
        "ripple": [{"module": k, **v} for k, v in sorted(by_module.items(), key=lambda kv: (-(kv[1]["direct"] + kv[1]["second"]), kv[0]))],
        "ripple_examples": sorted(ripple, key=lambda p: (ripple[p], p))[: 2 * LISTED],
        "tests": {"count": len(tests), "nearest": nearest[:LISTED], "paths": nearest},
        "reviewers": reviewers,
        "regulars": regulars,
        "nobody_else_can_look": sorted(nobody_else)[:LISTED],
        "inactive_days": own.inactive_days,
        "notes": notes,
    }


# --- Markdown ---------------------------------------------------------------------------------------------


def _many(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else many or one + 's'}"


CAVEAT = "Git cannot see who reviewed; these are the people who committed to the changed files in the last year, most commits first, then the people who maintain them."


def people(reviewers: list[dict]) -> str:
    """`Alice Adams (2 files, 5 commits in the last year)`, the same on the triage page and in the brief."""
    return ", ".join(f"{r['name']} ({_many(r['files'], 'file')}, {_many(r['commits'], 'commit') + ' in the last year' if r['commits'] else 'no commits in the last year'})" for r in reviewers)


def regulars_line(t: dict) -> str | None:
    """The repository's regulars who are neither authors nor already offered, with their share of the window's commits;
    None when there is nobody to add."""
    g = t.get("regulars")
    if not g:
        return None
    named = {r["name"] for r in t["reviewers"]}
    rest = [p for p in g["people"] if p["name"] not in named]
    if not rest:
        return None
    listed = ", ".join(f"{p['name']} ({_many(p['commits'], 'commit')}, {p['share']:.0%})" for p in rest)
    apart = "apart from the authors and the people above" if named else "apart from the authors"
    return (
        f"The repository's regulars in the last {g['window_days']} days, {apart}: {listed}, of {_many(g['commits'], 'commit')} by {_many(g['committers'], 'person', 'people')}. "
        "Where a few people review everything they are the reviewers whatever the files; where review is spread, the people behind the files are the better offer."
    )


def _why(row: dict, active_days: int) -> str:
    if row["commits_active"]:
        text = _many(row["commits_active"], "commit") + f" in {active_days} days"
        if row["fixes_90"]:
            text += f", {row['fixes_90']} of them fixes or reverts"
        return text
    if "new file" in row["flags"]:
        return "new file"
    return f"quiet since {row['last_commit']}" if row["last_commit"] else "no history"


def markdown(t: dict, limit: int = 20, active_days: int = 90) -> str:
    from .render import _owners, _table  # the report tables, shared

    c, s = t["change"], t["summary"]
    out = [f"# Change triage: {t['repo']['name']}", ""]
    scope = f"`{c['since']}` (base {c['base']}) to {'the working tree' if c['uncommitted'] else 'HEAD ' + c['head']}"
    out += [f"{scope}. {_many(s['files'], 'code file')} changed, **{s['lines']:,}** lines, in {_many(s['areas'], 'area')}"
            + (f"; {_many(s['other_files'], 'other file')} ({s['other_lines']:,} lines of config, docs and the like) not ranked." if s["other_files"] else "."), ""]
    if not t["files"]:
        return "\n".join(out + ["No code changed.", ""])
    def count(n: int, one: str, many: str) -> str:
        return f"**{n}** file {one}" if n == 1 else f"**{n}** files {many}"

    bullets = []
    if s["recently_fixed"]:
        bullets.append(count(s["recently_fixed"], "was fixed or reverted in the last 90 days", "were fixed or reverted in the last 90 days"))
    if s["no_active_owner"]:
        bullets.append(count(s["no_active_owner"], "has no active owner", "have no active owner") + ": nobody who maintains the code has committed lately")
    if s["nobody_else_can_look"]:
        bullets.append(count(s["nobody_else_can_look"], "is maintained by nobody but the author", "are maintained by nobody but the author"))
    if s["ripple"]["direct"] or s["ripple"]["second"]:
        bullets.append(f"code outside the change that imports it: **{_many(s['ripple']['direct'], 'file')}** directly, {_many(s['ripple']['second'], 'file')} through one more step")
    if s["tests"]:
        bullets.append(f"**{s['tests']}** test {'file reaches' if s['tests'] == 1 else 'files reach'} it")
    if (d := s.get("definitions")) and d["touched"]:
        bullets.append(f"**{d['named']}** of the {_many(d['touched'], 'definition')} it touched {'is' if d['named'] == 1 else 'are'} named in a test that reaches the file")
    if bullets:
        out += [f"- {b}" for b in bullets] + [""]

    gone = t["inactive_days"]
    rows = []
    for r in t["files"][:limit]:
        who = _owners(r["owners"], gone) if r["owners"] else "-"
        flags = [f"moved from `{r['from']}`" if f == "moved" and r.get("from") else f for f in r["flags"]]
        rows.append([r["rank"], f"`{r['path']}`", _why(r, active_days), f"+{r['added']} -{r['deleted']}", who, r["dependents"]["direct"], "; ".join(flags) or "-"])
    out += ["Look at these first:", ""]
    out += _table(["#", "File", "Why", "This change", "Owners", "Imported by", "Flags"], rows, {0, 5})
    if named := symbols.lines(t["files"][:limit]):
        out += [*named, ""]
    if len(t["files"]) > limit:
        out += [f"{len(t['files']) - limit} more files in the JSON output.", ""]
    if t["reviewers"]:
        out += [f"Who can look, other than the authors: {people(t['reviewers'])}. {CAVEAT}", ""]
    if line := regulars_line(t):
        out += [line, ""]
    if t["nobody_else_can_look"]:
        out += ["Only the author maintains: " + ", ".join(f"`{p}`" for p in t["nobody_else_can_look"][:5]) + (" ..." if s["nobody_else_can_look"] > 5 else ""), ""]
    if t["ripple"]:
        out += ["Not in the change, but importing it (by area):", ""]
        out += _table(["Area", "Directly", "One more step"], [[f"`{r['module']}`", r["direct"], r["second"]] for r in t["ripple"][:10]], {1, 2})
    if t["tests"]["nearest"]:
        out += ["Tests that reach it, nearest first: " + ", ".join(f"`{p}`" for p in t["tests"]["nearest"][:5]) + (f" and {t['tests']['count'] - 5} more" if t["tests"]["count"] > 5 else ""), ""]
    if named := mentions.line(t["files"]):
        out += [named, ""]
    if usual := companions.line(t.get("companions") or []):
        out += [usual, ""]
    out += ["## Read this with care", ""] + [f"- {n}" for n in t["notes"]] + [""]
    return "\n".join(out)
