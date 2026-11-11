"""What a change did to the map of the repository.

`tessri scan` describes a repository as it is. This compares two states of it, the point where a branch left
its base and the working tree now, and reports what the change altered in structure: files nothing reaches any
more, modules that now depend on each other, imports of files the change deleted, and changed code that nobody
active maintains. It is meant for the moment an agent (or a person) finishes a task, before the change is merged.

The base is read from git objects into a scratch directory and analysed there; the repository itself is never
touched. Ownership comes from history up to the base, so the change's own commits cannot make its author the owner
of what they just changed. Everything is static imports, with one exception that says so: a file the change deleted or
moved that an untouched file still names in a string or a dynamic import is a warning for a person, because such a
name may load the file at run time. Anything else that is only wrong at run time shows nothing here.
"""

from __future__ import annotations

import dataclasses
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, gitlog, inventory, meta, modules
from .analyze import HINT_DIRS, Analysis, analyze
from .config import Config
from .model import SCHEMA_VERSION
from .ownership import UNOWNED

SEVERITIES = ("info", "warn", "block")  # least to most serious
LISTED = 10  # files or edges named in one finding
EXAMPLES = 3
REACHED = ("import", "package", "config", "dynamic", "string", "unknown")  # how a stranded file's former links are listed: statements first, guesses last

NOTES = [
    "Dependencies are static imports between files of this repository; a deleted or moved file that an untouched file still names in a string "
    "or a dynamic import is a warning for a person, since such a name is a guess that the file is loaded at run time. Registries and consumers "
    "outside the repository are invisible, so a clean result does not mean nothing else depends on the change.",
    "Orphans, cycles and imports are compared between the base of the change and the working tree with the same settings; modules are the same "
    "directories on both sides, and a file git sees as moved is one file under its new name on both sides.",
    "Ownership is read from history up to the base, so the author of the change does not count as having maintained what they changed.",
]


class CheckError(ValueError):
    pass


def _git(root: Path, *args: str, check: bool = True, binary: bool = False):
    try:
        res = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CheckError(f"git could not run: {exc}") from exc
    if check and res.returncode != 0:
        message = res.stderr.decode("utf-8", "replace").strip().splitlines()
        raise CheckError(message[-1] if message else "git failed")
    return res.stdout if binary else res.stdout.decode("utf-8", "replace")


DEFAULT_BRANCHES = ("origin/main", "origin/master", "main", "master")  # tried in this order when the remote declares no default


def default_since(root: Path) -> str:
    """The ref a change is compared with when the caller names none: the branch the remote declares as its default
    (`origin/HEAD`), else the first of `DEFAULT_BRANCHES` that exists, else `HEAD`, which is the uncommitted work
    alone. A remote-tracking branch comes before a local one of the same name because the local one may be stale."""
    declared = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).strip()
    if declared:
        return declared
    for name in DEFAULT_BRANCHES:
        ref = f"refs/remotes/{name}" if name.startswith("origin/") else f"refs/heads/{name}"
        if _git(root, "rev-parse", "--verify", "--quiet", ref, check=False).strip():
            return name
    return "HEAD"


def resolve_base(root: Path, since: str) -> tuple[str, str, str]:
    """(commit to compare with, HEAD, path of `root` inside the repository): the point where `since` and HEAD part,
    which is how a pull request is judged."""
    if _git(root, "rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
        raise CheckError("check needs a git repository")
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False).strip()
    if not head:
        raise CheckError("this repository has no commits yet")
    found = _git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}", check=False).strip()
    if not found:
        raise CheckError(f"`{since}` is not a commit, branch or tag in this repository")
    base = _git(root, "merge-base", found, head, check=False).strip()
    if not base:
        raise CheckError(f"`{since}` and HEAD share no history")
    return base, head, _git(root, "rev-parse", "--show-prefix").strip()


def changed_files(root: Path, base: str) -> dict[str, gitlog.FileChange]:
    """Path -> what changed between `base` and the working tree, untracked files included. A file git sees as moved is
    one entry under its new name, its `origin` the path it had at the base and its lines the edits made on the way."""
    found = gitlog.diff(root, base)
    if found is None:
        raise CheckError("git could not read what changed since the base")
    return found


def _renamed(a: Analysis, moves: dict[str, str]) -> Analysis:
    """`a` with every path in `moves` spelled as the working tree spells it now, so that the base of a change and the
    change itself name a moved file the same way. Records and the graph are translated; the base side carries no
    history, so nothing else needs to be."""
    if not moves:
        return a

    def new(path: str | None) -> str | None:
        return moves.get(path, path) if path is not None else None

    g = a.graph
    graph = dataclasses.replace(
        g,
        analyzed={new(p) for p in g.analyzed},
        edges={new(s): {new(t) for t in ts} for s, ts in g.edges.items()},
        indirect={new(s): {new(t) for t in ts} for s, ts in g.indirect.items()},
        roots={new(p): r for p, r in g.roots.items()},
        tests={new(p) for p in g.tests},
        config_refs=defaultdict(set, {new(p): {new(c) for c in cs} for p, cs in g.config_refs.items()}),
        doc_refs=defaultdict(set, {new(p): {new(c) for c in cs} for p, cs in g.doc_refs.items()}),
        inbound=defaultdict(set, {new(p): {new(x) for x in xs} for p, xs in g.inbound.items()}),
        provenance={new(s): {new(t): k for t, k in ts.items()} for s, ts in g.provenance.items()},
        prod_parent={new(p): new(q) for p, q in g.prod_parent.items()},
        test_parent={new(p): new(q) for p, q in g.test_parent.items()},
    )
    records = {new(p): dataclasses.replace(r, path=new(p)) for p, r in a.records.items()}
    return dataclasses.replace(a, records=records, graph=graph)


def analyse_base(root: Path, base: str, prefix: str, cfg: Config, skip: list[str], now: float) -> Analysis:
    """The base of the change analysed in a scratch directory, straight from git objects; the repository is not touched."""
    with tempfile.TemporaryDirectory(prefix="tessri-base-") as scratch:
        extract_tree(root, base, prefix, Path(scratch), skip)
        return analyze(Path(scratch), cfg, now=now)


def extract_tree(root: Path, base: str, prefix: str, dest: Path, skip: list[str]) -> int:
    """Write the files of the base commit (below `prefix`) into `dest`, straight from git objects: unlike
    `git archive` this ignores `export-ignore`, which would make files vanish from the base. Files the analysis
    skips (excluded, too large, links, submodules) are not written. Returns how many were."""
    tree = f"{base}:{prefix.rstrip('/')}" if prefix else base
    try:
        listing = _git(root, "ls-tree", "-r", "-z", "-l", tree, binary=True).decode("utf-8", "surrogateescape")
    except CheckError:
        return 0  # the directory did not exist yet: everything in it is new
    wanted: list[tuple[str, str]] = []
    for record in listing.split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split(None, 3)
        if len(parts) != 4 or parts[1] != "blob" or parts[0] == "120000" or not parts[3].isdigit():
            continue
        if int(parts[3]) > inventory.MAX_FILE_BYTES or inventory.matches(path, skip):
            continue
        wanted.append((parts[2], path))
    if not wanted:
        return 0
    try:
        proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise CheckError(f"git could not run: {exc}") from exc
    assert proc.stdin is not None and proc.stdout is not None
    written = 0
    with proc:
        for sha, path in wanted:
            proc.stdin.write(f"{sha}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise CheckError(f"git could not read {path} at the base of the change")
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)  # the newline after the content
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written += 1
        proc.stdin.close()
    return written


def _finding(kind: str, severity: str, key: str, title: str, detail: str, files: list[str], action: str, needs_human: bool = False) -> dict:
    return {"id": f"{kind}:{key}", "kind": kind, "severity": severity, "title": title, "detail": detail, "files": files, "action": action, "needs_human": needs_human}


def _link(path: str, kind: str) -> str:
    """A file and, unless the link is an import statement, the kind of evidence behind it, marked as `why` marks it."""
    return f"`{path}`" if kind == "import" else f"`{path}` ({kind})"


def _edge_row(e: dict) -> dict:
    return {"from": e["from"], "to": e["to"], "imports": e["imports"], "files": e["files"], "examples": e["examples"][:EXAMPLES], "against_flow": e["cut"]}


def _describe(e: dict) -> str:
    sample = f" (for example `{e['examples'][0][0]}` imports `{e['examples'][0][1]}`)" if e["examples"] else ""
    return f"`{e['from']}` → `{e['to']}`, {e['imports']} import{'s' if e['imports'] != 1 else ''}{sample}"


def compare(base_a: Analysis, head_a: Analysis, changed: dict[str, gitlog.FileChange]) -> dict:
    """The structural difference between two analyses of one repository, and the findings it adds up to. The base is
    read under the names the working tree uses now, so a moved file is one file on both sides."""
    findings: list[dict] = []
    touched = set(changed)
    base_a = _renamed(base_a, {c.origin: p for p, c in changed.items() if c.origin})

    # orphans: files nothing reaches
    base_orphans = {p for p, r in base_a.records.items() if r.status == "ORPHAN"}
    head_orphans = {p for p, r in head_a.records.items() if r.status == "ORPHAN"}
    new_orphans = []
    for path in sorted(head_orphans - base_orphans):
        how = "added" if path not in base_a.records else "stranded"
        row = {"path": path, "how": how, "code": head_a.records[path].code}
        if how == "stranded":
            links = {s: base_a.graph.kind(s, path) for s in base_a.graph.inbound.get(path, ())}
            links.update({s: "config" for s in base_a.graph.config_refs.get(path, ())})
            shown = sorted(links, key=lambda s: (REACHED.index(links[s]), s))[:EXAMPLES]
            row["was_reached_from"] = shown
            row["reached_kinds"] = {s: links[s] for s in shown}  # an import, a package file, a config, or a guess from a string or a dynamic import
        new_orphans.append(row)
    fixed_orphans = [
        {"path": p, "how": "removed" if p not in head_a.records else "wired"} for p in sorted(base_orphans - head_orphans)
    ]
    added = [r for r in new_orphans if r["how"] == "added"]
    stranded = [r for r in new_orphans if r["how"] == "stranded"]
    if added:
        by_hand = [r for r in added if any(d in HINT_DIRS for d in r["path"].split("/")[:-1])]
        detail = "No entry point, test or config reaches these files, so as far as the analysis can tell they are dead on arrival."
        if by_hand:
            detail += f" {len(by_hand)} of them are under directories such as scripts/ or examples/, where files are often run by hand."
        findings.append(
            _finding(
                "new-orphan", "warn" if len(by_hand) < len(added) else "info", "added", f"{len(added)} new file{'s' if len(added) != 1 else ''} that nothing reaches",
                detail, [r["path"] for r in added][:LISTED],
                "Import them from where they are meant to be used, add a test that does, or drop them. `tessri why <file>` shows the evidence.",
            )
        )
    if stranded:
        findings.append(
            _finding(
                "new-orphan", "warn", "stranded", f"{len(stranded)} file{'s' if len(stranded) != 1 else ''} nothing reaches any more",
                "These were reachable before the change; it removed the last way to reach them. " + "; ".join(f"`{r['path']}` was reached from " + ", ".join(_link(s, r["reached_kinds"][s]) for s in r["was_reached_from"]) for r in stranded[:3] if r["was_reached_from"]),
                [r["path"] for r in stranded][:LISTED], "Check whether they are meant to go too (delete them in this change) or whether the change cut a link it should not have.",
            )
        )

    # imports of deleted files, and of moved files under their old name
    dangling = []
    for path, change in sorted(changed.items()):
        rec = base_a.records.get(path)
        if change.state not in ("deleted", "moved") or rec is None or not rec.analyzer:
            continue
        users = sorted(
            s
            for s in base_a.graph.inbound.get(path, ())
            if path in modules._imported(base_a, s) and s in head_a.records and s not in touched and path not in modules._imported(head_a, s)
        )
        if users:
            gone = change.origin or path
            row = {"deleted": gone, "importers": users}
            if change.origin:
                row["moved_to"] = path
            dangling.append(row)
            findings.append(
                _finding(
                    "dangling-import", "block", gone,
                    f"`{gone}` was moved to `{path}` but is still imported under its old name" if change.origin else f"`{path}` was deleted but is still imported",
                    "Untouched by this change, still importing it: " + ", ".join(f"`{u}`" for u in users[:LISTED]) + (f" and {len(users) - LISTED} more" if len(users) > LISTED else ""),
                    users[:LISTED],
                    "Update every importer to the new path in the same change." if change.origin else "Restore the file, or update every importer in the same change.",
                )
            )

    # names of deleted or moved files in strings and dynamic imports of untouched files: a guess that the file is
    # loaded at run time, so a warning for a person rather than a block
    references = []
    for path, change in sorted(changed.items()):
        rec = base_a.records.get(path)
        if change.state not in ("deleted", "moved") or rec is None or not rec.analyzer:
            continue
        referrers = sorted(
            (s, base_a.graph.kind(s, path))
            for s in base_a.graph.inbound.get(path, ())
            if base_a.graph.kind(s, path) in modules.REFERENCE_KINDS
            and path not in modules._imported(base_a, s)
            and s in head_a.records
            and s not in touched
            and path not in head_a.graph.edges.get(s, ())
        )
        if referrers:
            gone = change.origin or path
            row = {"deleted": gone, "referrers": [{"path": s, "kind": k} for s, k in referrers]}
            if change.origin:
                row["moved_to"] = path
            references.append(row)
            listed = ", ".join(_link(s, k) for s, k in referrers[:LISTED]) + (f" and {len(referrers) - LISTED} more" if len(referrers) > LISTED else "")
            findings.append(
                _finding(
                    "dangling-reference", "warn", gone,
                    f"`{gone}` was moved to `{path}` but is still named by its old name" if change.origin else f"`{path}` was deleted but is still named in code",
                    f"Untouched by this change, still naming it in a string or a dynamic import: {listed}. "
                    "A name in a string is the analysis's guess that the file is loaded at run time, not a statement the code made.",
                    [s for s, _ in referrers[:LISTED]],
                    "Check whether the name loads the file at run time; if it does, update it in the same change or restore the file.",
                    needs_human=True,
                )
            )

    # module dependencies and cycles, with one module split for both sides
    pool = {*modules._members(base_a, False), *modules._members(head_a, False)}
    assignment = modules.assign(pool)
    gb = modules.build_graph(base_a, assignment=assignment)
    gh = modules.build_graph(head_a, assignment=assignment)
    base_edges = {(e["from"], e["to"]) for e in gb["edges"]}
    head_edges = {(e["from"], e["to"]): e for e in gh["edges"]}
    new_edges = [e for k, e in head_edges.items() if k not in base_edges]
    gone_edges = sorted(k for k in base_edges if k not in head_edges)
    base_cycles = [set(c["modules"]) for c in gb["cycles"]]
    head_cycle_sets = [set(c["modules"]) for c in gh["cycles"]]
    cycles_new, cycles_grown, cycles_resolved = [], [], []
    for c in gh["cycles"]:
        members = set(c["modules"])
        overlap = [b for b in base_cycles if b & members]
        if overlap and not (members - set().union(*overlap)):
            continue
        closing = sorted((e for e in new_edges if e["from"] in members and e["to"] in members), key=lambda e: (-e["imports"], e["from"], e["to"]))
        row = {"modules": c["modules"], "imports": c["imports"], "closing": [_edge_row(e) for e in closing[:LISTED]]}
        if overlap:
            row["added_modules"] = sorted(members - set().union(*overlap))
            cycles_grown.append(row)
        else:
            cycles_new.append(row)
        word = "now depend on each other" if not overlap else "have been drawn into an existing cycle"
        subject = ", ".join(f"`{m}`" for m in (row["modules"] if not overlap else row["added_modules"])[:6])
        findings.append(
            _finding(
                "cycle-grew" if overlap else "new-cycle", "warn", "+".join(c["modules"][:4]),
                f"Modules {subject} {word}",
                "Because of the new dependency " + "; ".join(_describe(e) for e in closing[:3]) + "." if closing else "Dependencies added by the change close the loop.",
                [ex[0] for e in closing[:3] for ex in e["examples"][:1]],
                "Remove or invert the new dependency, or move what both need into a module they both depend on.",
            )
        )
    for b in base_cycles:
        if not any(b & h for h in head_cycle_sets):
            cycles_resolved.append({"modules": sorted(b)})
    new_deps = [_edge_row(e) for e in sorted(new_edges, key=lambda e: (-e["imports"], e["from"], e["to"]))]
    if new_deps:
        against = sum(1 for e in new_deps if e["against_flow"])
        findings.append(
            _finding(
                "new-dependency", "info", "modules", f"{len(new_deps)} new dependenc{'ies' if len(new_deps) != 1 else 'y'} between modules",
                "; ".join(_describe(e) for e in sorted(new_edges, key=lambda e: (-e["imports"], e["from"], e["to"]))[:5])
                + (f". {against} of them point{'s' if against == 1 else ''} against the dominant direction inside a cycle." if against else "."),
                [], "Check that each belongs: a new arrow between two modules is a new reason for them to change together.",
            )
        )

    # changed code that nobody active maintains
    unowned = []
    for path, change in sorted(changed.items()):
        rec = head_a.records.get(path)
        if change.state == "deleted" or rec is None or rec.kind != "code" or rec.ownership != UNOWNED:
            continue
        unowned.append({"path": path, "lines": change.lines, "last_owner": rec.owner, "owner_idle_days": rec.owner_idle_days})
    unowned.sort(key=lambda r: (-r["lines"], r["path"]))
    if unowned:
        gone = head_a.cfg.owner_inactive_days
        findings.append(
            _finding(
                "no-active-owner", "warn", "changed", f"{len(unowned)} changed file{'s' if len(unowned) != 1 else ''} nobody active maintains",
                f"Nobody who maintained these files has committed anywhere in the last {gone} days, so nobody who knows them is likely to look at the change.",
                [r["path"] for r in unowned][:LISTED], "Have a human who knows the code look before merging, or assign an owner; the last maintainers are listed with `tessri why <file>`.",
                needs_human=True,
            )
        )
    if fixed_orphans:
        removed = sum(r["how"] == "removed" for r in fixed_orphans)
        findings.append(
            _finding("orphan-resolved", "info", "all", f"{len(fixed_orphans)} orphan file{'s' if len(fixed_orphans) != 1 else ''} gone",
                     f"{removed} deleted, {len(fixed_orphans) - removed} now reached.", [r["path"] for r in fixed_orphans][:LISTED], "")
        )
    for r in cycles_resolved:
        findings.append(_finding("cycle-resolved", "info", "+".join(r["modules"][:4]), "A cycle is gone", "Modules " + ", ".join(f"`{m}`" for m in r["modules"][:6]) + " no longer depend on each other.", [], ""))

    order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    findings.sort(key=lambda f: (order[f["severity"]], f["kind"], f["id"]))
    return {
        "findings": findings,
        "orphans": {"new": new_orphans, "resolved": fixed_orphans},
        "dangling_imports": dangling,
        "dangling_references": references,
        "cycles": {"new": cycles_new, "grown": cycles_grown, "resolved": cycles_resolved},
        "dependencies": {"new": new_deps, "removed": [{"from": a, "to": b} for a, b in gone_edges]},
        "unowned": unowned,
        "modules_touched": sorted({assignment[p] for p in touched if p in assignment}),
    }


def check(root: Path, cfg: Config, since: str | None = None, now: float | None = None, analyses: tuple[Analysis, Analysis] | None = None) -> dict:
    """The JSON-ready result of comparing `since` (as it was where it left HEAD; `default_since` when None) with the
    working tree. `analyses` is the pair (base, working tree with history up to the base), both with review load off,
    when the caller has made them already (`brief` makes one pair for triage and check); otherwise they are made here."""
    root = Path(root).resolve()
    now = time.time() if now is None else now
    if since is None:
        since = default_since(root)
    base, head, prefix = resolve_base(root, since)
    skip = [*inventory.DEFAULT_EXCLUDES, *cfg.exclude]
    changed = {p: c for p, c in sorted(changed_files(root, base).items()) if not inventory.matches(p, skip)}
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal").strip())
    files = []
    for path, c in changed.items():
        lang = inventory.language_of(path)
        row = {"path": path, "change": c.state, "added": c.added, "deleted": c.deleted, "lines": c.lines, "code": bool(lang is not None and lang.kind == "code")}
        if c.origin:
            row["from"] = c.origin
        files.append(row)
    code = [f for f in files if f["code"]]
    change_ids = {"since": since, "base": base, "head": head, "uncommitted": dirty}
    result: dict = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "tessri", "version": __version__},
        "generated_at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {"name": root.name},
        "kind": "change-check",
        # Until the trees are compared below, the metadata says so: no history was read and no structure was checked.
        "meta": meta.block(now, root, gitlog.GitState(False, "not-requested", head, None), change=change_ids, analysis={"structure": "skipped", "reason": "no-code-changes"}),
        "change": {"since": since, "base": base[:9], "head": head[:9], "uncommitted": dirty},
        "summary": {
            "files": len(files),
            "code_files": len(code),
            "added": sum(f["change"] == "added" for f in code),
            "modified": sum(f["change"] == "modified" for f in code),
            "moved": sum(f["change"] == "moved" for f in code),
            "deleted": sum(f["change"] == "deleted" for f in code),
            "lines": sum(f["lines"] for f in code),
            "other_files": len(files) - len(code),
        },
        "changed_files": files,
        "notes": NOTES,
    }
    if not code:
        result.update({"findings": [], "orphans": {"new": [], "resolved": []}, "dangling_imports": [], "dangling_references": [], "cycles": {"new": [], "grown": [], "resolved": []}, "dependencies": {"new": [], "removed": []}, "unowned": [], "modules_touched": []})
        result["summary"]["findings"] = {s: 0 for s in SEVERITIES}
        return result
    if analyses is not None:
        base_a, head_a = analyses
    else:
        quiet = dataclasses.replace(cfg, review_days=0)
        base_a = analyse_base(root, base, prefix, quiet, skip, now)
        head_a = analyze(root, quiet, now=now, rev=base)
    result["meta"] = meta.of(head_a, change=change_ids, analysis={"structure": "complete", "reason": None})
    result.update(compare(base_a, head_a, changed))
    result["summary"]["findings"] = {s: sum(f["severity"] == s for f in result["findings"]) for s in SEVERITIES}
    result["summary"]["modules"] = len(result["modules_touched"])
    return result


def failing(result: dict, fail_on: str) -> bool:
    """Whether the findings reach the severity the caller asked to fail on ("never" never does)."""
    if fail_on == "never":
        return False
    floor = SEVERITIES.index(fail_on)
    return any(SEVERITIES.index(f["severity"]) >= floor for f in result["findings"])
