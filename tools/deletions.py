"""What became of the names a deletion left behind.

Every change in a repository's first-parent history that deleted or moved a code file is replayed through
`tessri check` against its parent, in a shared clone, and for every name the check says was left behind in a file
the change did not touch (`dangling-reference`: a config, a script, a document or a string in code; `dangling-import`
beside it) the later history says what became of it: a commit removed the name, restored the file or deleted the
referrer, and after how many days, or the name is still there at the end. A name a later commit removed was a real
loose end; one still there today may be a false alarm, a dead script or a stale page, and the listing names the file
to read to tell which.

    python tools/deletions.py path/to/repository --days 365
    python tools/deletions.py path/to/repository --format json --out deletions.json

Zero dependencies, like the tool; it uses the package in this checkout (or the installed one) to run the check. The
repository is cloned once, shared, into a scratch directory and checked out at each change there; the repository
itself is not touched. Each check costs a few seconds on a repository of a few thousand files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import posixpath
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tessri import config, since  # noqa: E402  (the package in this checkout)
from tessri.analyzers import load_analyzers  # noqa: E402

DAY = 86400
RESOLVED = ("name removed", "file restored", "referrer deleted")


class DeletionsError(ValueError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if res.returncode and check:
        raise DeletionsError(res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"git {args[0]} failed")
    return res.stdout


def _day(when: int) -> str:
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%Y-%m-%d")


ANALYZERS = load_analyzers()


def _is_code(path: str) -> bool:
    """A file an analyzer reads: the only kind whose deletion `check` can report."""
    return any(a.handles(path) for a in ANALYZERS)


def deletions(root: Path, rev: str, days: int) -> list[dict]:
    """The first-parent changes of the last `days` (all of history when 0) that deleted or moved a code file, oldest
    first, each with the old paths of the files it removed."""
    args = ["log", "--first-parent", "--diff-merges=first-parent", "-M", "--name-status", "--format=%x00%H %ct"]
    if days:
        args.append(f"--since={days} days ago")
    found: list[dict] = []
    cur = None
    for line in _git(root, *args, rev).splitlines():
        if line.startswith("\0"):
            sha, when = line[1:].split()
            cur = {"sha": sha, "when": int(when), "gone": []}
            found.append(cur)
        elif line and cur is not None:
            parts = line.split("\t")
            if parts[0][:1] in ("D", "R") and _is_code(parts[1]):
                cur["gone"].append(parts[1])
    return [c for c in reversed(found) if c["gone"]]


def tokens(path: str) -> set[str]:
    """The forms a file is named in: its base name, its dotted module path and the last two components of that. A
    package file is named by its directory, so only the dotted forms count for it."""
    stem = path.rsplit(".", 1)[0]
    if posixpath.basename(stem) in ("__init__", "index"):
        dotted = posixpath.dirname(stem).replace("/", ".")
        return {dotted, ".".join(dotted.split(".")[-2:])} if dotted else set()
    dotted = stem.replace("/", ".")
    return {posixpath.basename(path), dotted, ".".join(dotted.split(".")[-2:])}


def fate(clone: Path, sha: str, when: int, gone: str, referrer: str, end: str) -> dict:
    """What the commits after `sha` (up to `end`) that touched the referrer or the deleted path did about the name."""
    toks = tokens(gone)
    for line in _git(clone, "log", "--reverse", "--format=%H %ct", f"{sha}..{end}", "--", referrer, gone).splitlines():
        h, t = line.split()
        days = round((int(t) - when) / DAY)
        if subprocess.run(["git", "-C", str(clone), "cat-file", "-e", f"{h}:{gone}"], capture_output=True).returncode == 0:
            return {"fate": "file restored", "days": days}
        res = subprocess.run(["git", "-C", str(clone), "show", f"{h}:{referrer}"], capture_output=True)
        if res.returncode:
            return {"fate": "referrer deleted", "days": days}
        text = res.stdout.decode("utf-8", "replace")
        if not any(tok in text for tok in toks):
            return {"fate": "name removed", "days": days}
    return {"fate": "still named", "days": None}


def run(root: Path, rev: str = "HEAD", days: int = 365, log=None) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise DeletionsError(f"{root}: not a directory")
    end = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()
    changes = deletions(root, end, days)
    if not changes:
        raise DeletionsError(f"no change of the last {days} days deleted or moved a code file" if days else "no change deleted or moved a code file")
    now = time.time()
    rows: list[dict] = []
    outcomes: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="tessri-deletions-") as tmp:
        clone = Path(tmp) / "clone"
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(root), str(clone)], check=True, capture_output=True)
        for n, c in enumerate(changes, 1):
            _git(clone, "checkout", "-q", c["sha"])
            started = time.time()
            try:
                result = since.check(clone, config.load(clone), c["sha"] + "^", now=now)
            except since.CheckError as exc:
                rows.append({"sha": c["sha"], "date": _day(c["when"]), "gone": c["gone"], "error": str(exc)})
                continue
            row = {
                "sha": c["sha"], "date": _day(c["when"]), "gone": c["gone"], "seconds": round(time.time() - started, 1),
                "dangling_imports": result["dangling_imports"], "dangling_references": result["dangling_references"],
            }
            rows.append(row)
            if log:
                log(f"deletions: {c['sha'][:9]} {row['date']} ({n} of {len(changes)}): {len(c['gone'])} gone, {len(row['dangling_imports'])} still imported, {len(row['dangling_references'])} still named, {row['seconds']} s")
            for ref in row["dangling_references"]:
                for who in ref["referrers"]:
                    outcomes.append({"sha": c["sha"][:9], "date": row["date"], "deleted": ref["deleted"], "moved_to": ref.get("moved_to"), "referrer": who["path"], "kind": who["kind"], **fate(clone, c["sha"], c["when"], ref["deleted"], who["path"], end)})
            for imp in row["dangling_imports"]:
                for who in imp["importers"]:
                    outcomes.append({"sha": c["sha"][:9], "date": row["date"], "deleted": imp["deleted"], "moved_to": imp.get("moved_to"), "referrer": who, "kind": "import", **fate(clone, c["sha"], c["when"], imp["deleted"], who, end)})
    kinds: dict[str, dict] = {}
    for o in outcomes:
        k = kinds.setdefault(o["kind"], {"names": 0, "resolved": 0, "within_30_days": 0, "still_named": 0})
        k["names"] += 1
        if o["fate"] in RESOLVED:
            k["resolved"] += 1
            k["within_30_days"] += o["days"] <= 30
        else:
            k["still_named"] += 1
    checked = [r for r in rows if "error" not in r]
    summary = {
        "changes": len(changes), "checked": len(checked), "files_gone": sum(len(c["gone"]) for c in changes),
        "left_a_name": sum(1 for r in checked if r["dangling_references"] or r["dangling_imports"]),
        "names": len(outcomes), "resolved": sum(1 for o in outcomes if o["fate"] in RESOLVED), "still_named": sum(1 for o in outcomes if o["fate"] not in RESOLVED),
        "seconds_per_check": round(sum(r["seconds"] for r in checked) / len(checked), 1) if checked else None,
    }
    return {"repository": str(root), "rev": end, "days": days, "summary": summary, "kinds": kinds, "outcomes": outcomes, "changes": rows}


def render(result: dict) -> str:
    s = result["summary"]
    span = f"the last {result['days']} days" if result["days"] else "the whole history"
    lines = [
        f"deletions: {s['changes']} changes of {span} deleted or moved a code file ({s['files_gone']} files); "
        f"{s['left_a_name']} left a name behind, {s['names']} names in all: {s['resolved']} later resolved, {s['still_named']} still there"
        + (f"; {s['seconds_per_check']} s per check" if s["seconds_per_check"] is not None else "") + "."
    ]
    for kind, k in sorted(result["kinds"].items()):
        lines.append(f"  {kind}: {k['names']} name{'s' if k['names'] != 1 else ''}, {k['resolved']} resolved ({k['within_30_days']} within 30 days), {k['still_named']} still named")
    for o in result["outcomes"]:
        where = f"{o['deleted']} -> {o['moved_to']}" if o["moved_to"] else o["deleted"]
        after = "" if o["days"] is None else " the same day" if o["days"] == 0 else f" after {o['days']} day{'s' if o['days'] != 1 else ''}"
        lines.append(f"{o['date']} {o['sha']}  {where}  {o['referrer']} ({o['kind']}): {o['fate']}{after}")
    errors = [r for r in result["changes"] if "error" in r]
    for r in errors:
        lines.append(f"{r['date']} {r['sha'][:9]}  not checked: {r['error']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay every change that deleted or moved a code file through `tessri check` and report what became of the names it left behind.")
    parser.add_argument("path", help="the repository")
    parser.add_argument("--rev", default="HEAD", help="the branch or commit whose first-parent history is read (default HEAD)")
    parser.add_argument("--days", type=int, default=365, help="how far back to look (default 365; 0 for the whole history)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--out", help="write here instead of stdout")
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.path), args.rev, args.days, log=lambda line: print(line, file=sys.stderr))
    except (DeletionsError, config.ConfigError, since.CheckError) as exc:
        print(f"deletions: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=1) + "\n" if args.format == "json" else render(result)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
