"""One page to hand a change over: `tessri brief --since <base>`.

A review brief is triage and check from one pair of analyses (the base of the change and the working tree, each
analysed once), composed into what a reviewer needs before opening the diff: the exact state the evidence describes
(base, HEAD, the commits on the way in their authors' words, the uncommitted files in scope), the changed files to
look at first with the reasons triage gives, what the change did to the structure, the candidate tests kept apart
from the checks the host actually ran, who can look, and what needs a person. It selects for reading and shortens
every list with its count; the JSON carries the whole `triage` and `check` objects, so nothing is filtered away.

What the host ran is the host's to say: `--ran` records one line per check, verbatim, and without it the brief says
that no check was recorded. An execution is never inferred from the candidate tests."""

from __future__ import annotations

import dataclasses
import time
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from . import __version__, inventory, meta, since, triage
from .analyze import analyze
from .config import Config
from .model import SCHEMA_VERSION

LISTED = 8  # files in the look-first table
FINDINGS = 6  # findings shown
COMMITS = 8  # commits listed
NAMED = 5  # paths named inline
BUDGET = 800  # words the page aims to stay under

NOTES = [
    "This page selects from `tessri triage` and `tessri check`, run from one analysis of the base and one of the working tree; "
    "the JSON carries both objects whole, so a list shortened here hides nothing there.",
    "Files are ordered by how many commits touched them in the last 90 days, then by how much this change touches; in a backtest on "
    "one repository that predicted later fixes better than the size of the change alone. It says where trouble tends to be, not that "
    "this change is wrong, and a new file has no history, so it sorts by its size.",
    "Dependents, candidate tests and findings rest on what the analyzers see between files of this repository, static imports above all; "
    "a name in a string or a dynamic import is a guess, and the one finding that rests on it, `dangling-reference`, says so. Runtime wiring, "
    "registries and consumers outside the repository are invisible, and no finding is proof that the rest is fine.",
    "History is read up to the base, so the change's own commits do not count as activity and its authors do not count as owners. "
    "The commit subjects are the authors' words; the intent behind a change is not inferred from the files it touches.",
    "Candidate tests are paths that reach the change, never executions; only what `--ran` records was run.",
]


class BriefError(ValueError):
    pass


def _many(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else many or one + 's'}"


def _named(paths: Sequence[str], limit: int = NAMED) -> str:
    text = ", ".join(f"`{p}`" for p in paths[:limit])
    return text + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def commits(root: Path, base: str, head: str) -> list[dict]:
    """The commits of the change, newest first, merges left out: who wrote what, in their words."""
    out = []
    for line in since._git(root, "log", "--no-merges", "--format=%H%x09%aN%x09%s", f"{base}..{head}").splitlines():
        cid, _, rest = line.partition("\t")
        author, _, subject = rest.partition("\t")
        if cid:
            out.append({"id": cid, "author": author, "subject": subject})
    return out


def uncommitted(root: Path) -> list[str]:
    """The paths with uncommitted work, untracked files included, as git lists them."""
    entries = since._git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", binary=True).split(b"\0")
    paths: set[str] = set()
    skip = False
    for entry in entries:
        if skip:  # the original path of a rename or copy, in the record after it
            skip = False
            continue
        if len(entry) > 3:
            paths.add(entry[3:].decode("utf-8", "surrogateescape"))
            skip = entry[0:1] in (b"R", b"C")
    return sorted(paths)


def compute(root: Path, cfg: Config, since_ref: str | None = None, ran: Sequence[str] = (), now: float | None = None, limit: int = LISTED) -> dict:
    """The brief of the change between `since_ref` (`since.default_since` when None) and the working tree, as the
    JSON-ready dict the command prints: its own sections for reading, and the whole triage and check objects under
    `triage` and `check`."""
    root = Path(root).resolve()
    now = time.time() if now is None else now
    if since_ref is None:
        since_ref = since.default_since(root)
    try:
        base, head, prefix = since.resolve_base(root, since_ref)
        changed = since.changed_files(root, base)
    except since.CheckError as exc:
        raise BriefError(str(exc).replace("check needs", "brief needs", 1)) from exc
    skip = [*inventory.DEFAULT_EXCLUDES, *cfg.exclude]
    code = [p for p in sorted(changed) if not inventory.matches(p, skip) and (lang := inventory.language_of(p)) is not None and lang.kind == "code"]
    quiet = dataclasses.replace(cfg, review_days=0)
    head_a = analyze(root, quiet, now=now, rev=base)
    try:
        pair = (since.analyse_base(root, base, prefix, quiet, skip, now), head_a) if code else None
        t = triage.compute(root, cfg, since_ref, now=now, analysis=head_a)
        c = since.check(root, cfg, since_ref, now=now, analyses=pair)
    except (triage.TriageError, since.CheckError) as exc:
        raise BriefError(str(exc)) from exc

    not_analysed: dict[str, list[str]] = defaultdict(list)
    for path in code:
        rec = head_a.records.get(path)
        if rec is not None and rec.kind == "code" and rec.analyzer is None:
            not_analysed[rec.language].append(path)
    dirty = t["change"]["uncommitted"]
    s, cs = t["summary"], c["summary"]
    shown = t["files"][: max(limit, 0)]
    no_owner = [r["path"] for r in t["files"] if "no active owner" in r["flags"]]
    nobody_else = t["nobody_else_can_look"]

    open_items = [{"kind": f["kind"], "text": f"{f['title']}: {f['action']}", "files": f["files"]} for f in c["findings"] if f["needs_human"]]
    if nobody_else:
        open_items.append({"kind": "only-the-author", "text": f"Only the author maintains {_named(nobody_else)}: a second reader has to come from outside the file's history.", "files": nobody_else})
    for language, paths in sorted(not_analysed.items()):
        open_items.append({
            "kind": "not-analysed",
            "text": f"{_named(paths)}: no analyzer covers {language}, so dependents, candidate tests and structure are unknown for {'this file' if len(paths) == 1 else 'these files'}.",
            "files": paths,
        })
    if not ran:
        open_items.append({"kind": "no-checks-recorded", "text": "No check was recorded as run: the candidate tests are paths, not results.", "files": []})

    ids = {"since": since_ref, "base": base, "head": head, "uncommitted": dirty}
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "tessri", "version": __version__},
        "generated_at": meta.stamp(now),
        "repo": {"name": root.name},
        "kind": "brief",
        "meta": meta.of(head_a, change=ids, analysis={"structure": "complete" if pair else "skipped", "reason": None if pair else "no-code-changes"}),
        "change": {
            **ids,
            "uncommitted_files": uncommitted(root) if dirty else [],
            "authors": t["change"]["authors"],
            "commits": commits(root, base, head),
            "files": cs["files"],
            "code_files": cs["code_files"],
            "added": cs["added"],
            "modified": cs["modified"],
            "moved": cs["moved"],
            "deleted": cs["deleted"],
            "lines": cs["lines"],
            "other_files": cs["other_files"],
            "other_lines": s["other_lines"],
        },
        "attention": {"files": shown, "shown": len(shown), "total": len(t["files"]), "window_days": cfg.active_days, "inactive_days": t["inactive_days"]},
        "consequences": {
            "counts": cs["findings"],
            "findings": c["findings"],
            "ripple": s["ripple"],
            "by_area": t["ripple"],
            "modules_touched": c["modules_touched"],
            "not_analysed": [{"language": k, "files": v} for k, v in sorted(not_analysed.items())],
        },
        "validation": {"candidates": {"count": t["tests"]["count"], "nearest": t["tests"]["nearest"]}, "ran": list(ran)},
        "people": {"reviewers": t["reviewers"], "nobody_else_can_look": nobody_else, "no_active_owner": no_owner},
        "open": open_items,
        "triage": t,
        "check": c,
        "notes": NOTES,
    }


# --- Markdown ---------------------------------------------------------------------------------------------


def markdown(b: dict) -> str:
    from .render import _owners, _table  # the report tables, shared

    c, a, q, v, p = b["change"], b["attention"], b["consequences"], b["validation"], b["people"]
    out = [f"# Review brief: {b['repo']['name']}", ""]
    scope = f"`{c['since']}` (base {c['base'][:9]}) to "
    if c["uncommitted"]:
        scope += f"the working tree: HEAD {c['head'][:9]} plus {_many(len(c['uncommitted_files']), 'uncommitted file')}"
        scope += f" ({_named(c['uncommitted_files'])})" if c["uncommitted_files"] else ""
    else:
        scope += f"HEAD {c['head'][:9]}"
    if c["code_files"]:
        kinds = [f"{c['added']} added", f"{c['modified']} modified", *([f"{c['moved']} moved"] if c["moved"] else []), f"{c['deleted']} deleted"]
        what = f"{_many(c['code_files'], 'code file')} changed ({', '.join(kinds)}), **{c['lines']:,}** lines"
    else:
        what = "no code changed"
    what += f"; {_many(c['other_files'], 'other file')} ({c['other_lines']:,} lines of config, docs and the like)" if c["other_files"] else ""
    out += [f"{scope}. {what[0].upper() + what[1:]}.", ""]
    if c["commits"]:
        out += [f"{_many(len(c['commits']), 'commit')} on the way, by {', '.join(c['authors']) or 'unknown authors'}, in their words:", ""]
        out += [f"- `{k['id'][:9]}` {k['subject']} ({k['author']})" for k in c["commits"][:COMMITS]]
        out += [f"- and {len(c['commits']) - COMMITS} more under `change.commits`"] if len(c["commits"]) > COMMITS else []
        out += [""]
    elif c["uncommitted"]:
        out += ["No commits on the way: the change is uncommitted work" + (f" by {', '.join(c['authors'])}" if c["authors"] else "") + ".", ""]

    out += ["## Look first", ""]
    if not a["total"]:
        out += ["No code changed, so there is nothing to rank" + ("; the other files are under `check.changed_files`." if c["other_files"] else "."), ""]
    else:
        rows = []
        for r in a["files"]:
            flags = [f"moved from `{r['from']}`" if f == "moved" and r.get("from") else f for f in r["flags"]]
            rows.append([r["rank"], f"`{r['path']}`", triage._why(r, a["window_days"]), f"+{r['added']} -{r['deleted']}", _owners(r["owners"], a["inactive_days"]) if r["owners"] else "-", "; ".join(flags) or "-"])
        out += _table(["#", "File", "Why", "This change", "Owners", "Flags"], rows, {0})
        if a["total"] > a["shown"]:
            out += [f"{a['total'] - a['shown']} more files, in order, under `triage.files`.", ""]
        if p["reviewers"]:
            out += ["Who can look, other than the authors: " + ", ".join(f"{r['name']} ({_many(r['files'], 'file')})" for r in p["reviewers"]) + ". Git cannot see who reviewed; these are the people who maintain the changed files.", ""]
        else:
            out += ["Nobody other than the authors maintains the changed files, as far as history shows.", ""]

    out += ["## What it did to the structure", ""]
    if not c["code_files"]:
        out += ["Nothing was compared: no code changed.", ""]
    else:
        tally = ", ".join(f"{q['counts'][sev]} {sev}" for sev in reversed(since.SEVERITIES) if q["counts"][sev])
        out += [f"**{tally}.**" if tally else "No structural findings: the change adds no orphan, cycle, dangling import or unowned code that this analysis can see.", ""]
        for f in q["findings"][:FINDINGS]:
            line = f"- **{f['severity']}**: {f['title']}" + (f" ({_named(f['files'])})" if f["files"] else "") + "."
            out.append(line + (f" Do: {f['action']}" if f["action"] else ""))
        if len(q["findings"]) > FINDINGS:
            out.append(f"- and {len(q['findings']) - FINDINGS} more under `check.findings`")
        out += [""] if q["findings"] else []
        ripple = q["ripple"]
        if ripple["direct"] or ripple["second"]:
            areas = ", ".join(f"`{r['module']}` {r['direct'] + r['second']}" for r in q["by_area"][:3])
            out += [f"Code outside the change that imports it: **{_many(ripple['direct'], 'file')}** directly, {_many(ripple['second'], 'file')} through one more step" + (f" (by area: {areas})" if areas else "") + ".", ""]
        else:
            out += ["Nothing outside the change imports it, as far as static imports show.", ""]
        for group in q["not_analysed"]:
            out += [f"Not analysed: {_named(group['files'])} ({group['language']}, no analyzer), so dependents, candidate tests and structure are unknown for {'it' if len(group['files']) == 1 else 'them'}.", ""]

    out += ["## Validation", ""]
    cand = v["candidates"]
    if cand["count"]:
        out += [f"Candidate tests, nearest first: {_named(cand['nearest'])}" + (f" ({cand['count']} in all)" if cand["count"] > len(cand["nearest"][:NAMED]) else "") + ". They reach the changed files; they are paths, not results.", ""]
    elif c["code_files"]:
        out += ["No test file reaches the changed code, as far as static imports show.", ""]
    if v["ran"]:
        out += ["Checks the host ran, as recorded:", ""] + [f"- {line}" for line in v["ran"]] + [""]
    else:
        out += ['Checks the host ran: none recorded. Record each with `--ran "<command>: <result, exit code>"`.', ""]

    out += ["## Open for a person", ""]
    out += [f"- {item['text']}" for item in b["open"]] or ["- Nothing this analysis can name; the diff and the intent are still yours to read."]
    out += ["", "## Read this with care", ""] + [f"- {n}" for n in b["notes"]] + [""]
    return "\n".join(out)
