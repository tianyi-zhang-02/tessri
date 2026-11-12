"""A test report the host wrote, read into the test files it covers and how each fared.

JUnit XML is what pytest (`--junitxml`), jest-junit, go-junit-report, Gradle, Maven and most CI systems write, so one
reader covers them: every `testcase` is one run, its `file` attribute (or its suite's) or its dotted `classname` says
which file it belongs to, and a `failure`, `error` or `skipped` child says how it went. Nothing is inferred: a test
file the report does not mention did not run, as far as the report says, and a case no file of the repository can be
found for is counted as unmatched, not guessed at.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection, Iterable, Sequence
from pathlib import Path

NAMED = 5  # unmatched names listed
STATUSES = ("passed", "failed", "skipped")


class RunsError(ValueError):
    pass


def _locate(token: str, files: Collection[str]) -> str | None:
    """The repository file a report's `file` attribute names: as written, or the longest suffix that is a file."""
    parts = [p for p in token.replace("\\", "/").split("/") if p not in ("", ".")]
    for i in range(len(parts)):
        candidate = "/".join(parts[i:])
        if candidate in files:
            return candidate
    return None


def _from_classname(classname: str, files: Collection[str]) -> str | None:
    """`tests.test_x.CaseClass` names `tests/test_x.py`: the longest dotted prefix that is a module or a package."""
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        stem = "/".join(parts[:i])
        for candidate in (stem + ".py", stem + "/__init__.py"):
            found = _locate(candidate, files)
            if found:
                return found
    return None


def read(path: Path, files: Collection[str]) -> dict:
    """One report: its `cases`, per test file of the repository the counts of its cases by outcome, and the cases no
    file of the repository could be found for."""
    try:
        root = ET.parse(path).getroot()
    except OSError as exc:
        raise RunsError(f"{path}: {exc.strerror or exc}") from exc
    except ET.ParseError as exc:
        raise RunsError(f"{path}: not JUnit XML ({exc})") from exc
    if root.tag not in ("testsuites", "testsuite"):
        raise RunsError(f"{path}: not a JUnit report (the root element is `{root.tag}`)")
    parents = {child: parent for parent in root.iter() for child in parent}
    by_file: dict[str, dict[str, int]] = {}
    unmatched: dict[str, int] = {}
    cases = 0
    for case in root.iter("testcase"):
        cases += 1
        status = "failed" if case.find("failure") is not None or case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
        token = case.get("file")
        suite = parents.get(case)
        while not token and suite is not None:  # the suite's file, when the cases carry none
            token, suite = suite.get("file"), parents.get(suite)
        found = _locate(token, files) if token else None
        if found is None and case.get("classname"):
            found = _from_classname(case.get("classname", ""), files)
        if found is None:
            name = token or case.get("classname") or case.get("name") or "?"
            unmatched[name] = unmatched.get(name, 0) + 1
            continue
        by_file.setdefault(found, dict.fromkeys(STATUSES, 0))[status] += 1
    return {"source": str(path), "cases": cases, "files": by_file, "unmatched": {"cases": sum(unmatched.values()), "named": sorted(unmatched, key=lambda n: (-unmatched[n], n))[:NAMED]}}


def merge(reports: Iterable[dict]) -> dict:
    """Several reports as one: the counts summed per file, every source kept."""
    out: dict = {"sources": [], "cases": 0, "files": {}, "unmatched": {"cases": 0, "named": []}}
    for r in reports:
        out["sources"].append(r["source"])
        out["cases"] += r["cases"]
        for f, counts in r["files"].items():
            slot = out["files"].setdefault(f, dict.fromkeys(STATUSES, 0))
            for k in STATUSES:
                slot[k] += counts[k]
        out["unmatched"]["cases"] += r["unmatched"]["cases"]
        out["unmatched"]["named"] = sorted(set(out["unmatched"]["named"]) | set(r["unmatched"]["named"]))[:NAMED]
    return out


def load(paths: Sequence[str | Path], files: Collection[str], base: Path | None = None) -> dict:
    """The reports at `paths` (relative ones under `base`, else the working directory) as one."""
    return merge(read(Path(base, p) if base is not None and not Path(p).is_absolute() else Path(p), files) for p in paths)


def against(report: dict, candidates: Iterable[str]) -> dict:
    """The candidate test files against what ran: each one's outcome (failed when any of its cases failed, else
    skipped when none passed, else passed), and the ones the report does not mention, in the candidates' order."""
    ran: dict[str, str] = {}
    not_run: list[str] = []
    for p in candidates:
        counts = report["files"].get(p)
        if not counts or not sum(counts.values()):
            not_run.append(p)
            continue
        ran[p] = "failed" if counts["failed"] else "passed" if counts["passed"] else "skipped"
    return {
        "sources": report["sources"],
        "cases": report["cases"],
        "ran": ran,
        "passed": sum(1 for s in ran.values() if s == "passed"),
        "failed": [p for p, s in ran.items() if s == "failed"],
        "skipped": sum(1 for s in ran.values() if s == "skipped"),
        "not_run": not_run,
        "unmatched": report["unmatched"],
    }
