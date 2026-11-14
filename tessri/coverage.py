"""A coverage report the host wrote, held against the lines a change added or changed.

A test report says which tests ran; a coverage report says which statements they executed. The host writes one with
the tools it already has (coverage.py's `coverage xml`, `coverage json` or `coverage lcov`, pytest-cov, jest or c8
with the `lcov`, `cobertura` or `clover` reporter, most CI systems), and `brief --coverage FILE` joins it with the
diff: of the statements the change adds or changes in the code files the analyzers read, tests left out, which ran
under the recorded tests, which did not, and which changed files the report does not measure at all. Nothing is
inferred: a statement the report does not count as executed did not run, as far as the report says, and a changed
line the report has no statement on (a blank line, a comment, a line of a docstring) is neither. The line numbers are
those of the files as they were when the host ran the tests, and the report is read as the host left it.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path

from . import inventory, since
from .runs import locate

NAMED = 5  # unmatched names listed
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class CoverageError(ValueError):
    pass


def _hits(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def _xml(root: ET.Element, path: Path) -> Iterable[tuple[str, int, int]]:
    """(file as the report names it, line, hits) from Cobertura (`class filename`, `line number hits`) or Clover
    (`file path`, `line num count`) XML; both call their root `coverage`."""
    if root.tag != "coverage":
        raise CoverageError(f"{path}: not a coverage report (the root element is `{root.tag}`)")
    seen = False
    for cls in root.iter("class"):
        token = cls.get("filename")
        if token:
            for line in cls.iter("line"):
                if line.get("number"):
                    seen = True
                    yield token, int(line.get("number", "0")), _hits(line.get("hits"))
    for file in root.iter("file"):
        token = file.get("path") or file.get("name")
        if token:
            for line in file.iter("line"):
                if line.get("num"):
                    seen = True
                    yield token, int(line.get("num", "0")), _hits(line.get("count"))
    if not seen:
        raise CoverageError(f"{path}: not a coverage report (no lines under `class` or `file` elements)")


def _lcov(text: str, path: Path) -> Iterable[tuple[str, int, int]]:
    token = None
    seen = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            token = line[3:].strip()
        elif line.startswith("DA:") and token:
            number, _, rest = line[3:].partition(",")
            if number.strip().isdigit():
                seen = True
                yield token, int(number), _hits(rest.split(",")[0])
        elif line == "end_of_record":
            token = None
    if not seen:
        raise CoverageError(f"{path}: not a coverage report (lcov without `DA:` lines)")


def _json(data: object, path: Path) -> Iterable[tuple[str, int, int]]:
    """coverage.py's `coverage json`: `files` as path to `executed_lines` and `missing_lines`."""
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or not all(isinstance(v, dict) and "executed_lines" in v for v in files.values()):
        raise CoverageError(f"{path}: not a coverage report (JSON without `files` of `executed_lines`)")
    for token, entry in files.items():
        for number in entry.get("executed_lines", ()):
            yield token, int(number), 1
        for number in entry.get("missing_lines", ()):
            yield token, int(number), 0


def read(path: Path, files: Collection[str]) -> dict:
    """One report: per file of the repository the lines it executed and the statements it missed, and the files it
    names that no file of the repository could be found for."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CoverageError(f"{path}: {exc.strerror or exc}") from exc
    body = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if body[:1] == b"<":
        try:
            rows = _xml(ET.fromstring(data), path)
        except ET.ParseError as exc:
            raise CoverageError(f"{path}: not well-formed XML ({exc})") from exc
    elif body[:1] == b"{":
        try:
            rows = _json(json.loads(data), path)
        except ValueError as exc:
            raise CoverageError(f"{path}: not JSON ({exc})") from exc
    elif body[:3] in (b"TN:", b"SF:"):
        rows = _lcov(data.decode("utf-8", "replace"), path)
    else:
        raise CoverageError(f"{path}: not a coverage report (neither Cobertura or Clover XML, lcov nor coverage.py's JSON)")
    placed: dict[str, dict[str, set[int]]] = {}
    unmatched: set[str] = set()
    for token, number, hits in rows:
        found = locate(token, files)
        if found is None:
            unmatched.add(token)
            continue
        slot = placed.setdefault(found, {"executed": set(), "missing": set()})
        slot["executed" if hits > 0 else "missing"].add(number)
    for slot in placed.values():
        slot["missing"] -= slot["executed"]
    return {"source": str(path), "files": placed, "unmatched": {"files": len(unmatched), "named": sorted(unmatched)[:NAMED]}}


def merge(reports: Iterable[dict]) -> dict:
    """Several reports as one: a statement ran if any report saw it run, every source kept."""
    out: dict = {"sources": [], "files": {}, "unmatched": {"files": 0, "named": []}}
    for r in reports:
        out["sources"].append(r["source"])
        for f, lines in r["files"].items():
            slot = out["files"].setdefault(f, {"executed": set(), "missing": set()})
            slot["executed"] |= lines["executed"]
            slot["missing"] |= lines["missing"]
        out["unmatched"]["files"] += r["unmatched"]["files"]
        out["unmatched"]["named"] = sorted(set(out["unmatched"]["named"]) | set(r["unmatched"]["named"]))[:NAMED]
    for slot in out["files"].values():
        slot["missing"] -= slot["executed"]
    return out


def load(paths: Sequence[str | Path], files: Collection[str], base: Path | None = None) -> dict:
    """The reports at `paths` (relative ones under `base`, else the working directory) as one."""
    return merge(read(Path(base, p) if base is not None and not Path(p).is_absolute() else Path(p), files) for p in paths)


_ESCAPES = {b"a": b"\a", b"b": b"\b", b"f": b"\f", b"n": b"\n", b"r": b"\r", b"t": b"\t", b"v": b"\v", b"\\": b"\\", b'"': b'"'}


def _unquote(path: str) -> str:
    """A path as git quotes it when it holds a control character, a quote or a backslash: C escapes and `\\ooo`
    octal bytes inside double quotes, undone at the byte level so a non-ASCII name survives."""
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    raw = path[1:-1].encode("utf-8", "surrogateescape")
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i : i + 1] == b"\\" and i + 1 < len(raw):
            if raw[i + 1 : i + 2] in _ESCAPES:
                out += _ESCAPES[raw[i + 1 : i + 2]]
                i += 2
                continue
            if len(raw[i + 1 : i + 4]) == 3 and raw[i + 1 : i + 4].isdigit():
                out.append(int(raw[i + 1 : i + 4], 8))
                i += 4
                continue
        out += raw[i : i + 1]
        i += 1
    return out.decode("utf-8", "surrogateescape")


def changed_lines(root: Path, base: str, paths: Collection[str]) -> dict[str, set[int]]:
    """Path -> the numbers, in the working tree, of the lines the change between `base` and the working tree added
    or changed in each of `paths`, from the diff's hunks; a file git does not know is new in full. The whole diff is
    read, so a moved file counts only the edits made on the way."""
    out: dict[str, set[int]] = {p: set() for p in paths}
    if not paths:
        return out
    wanted = set(paths)
    seen: set[str] = set()
    current: str | None = None
    header = False
    for line in since._git(root, "diff", "--relative", "--no-prefix", "-U0", "-M", base).splitlines():
        if line.startswith("diff --git "):
            header, current = True, None
        elif header and line.startswith("+++ "):
            header = False
            name = _unquote(line[4:].rstrip("\t"))
            current = name if name != "/dev/null" and name in wanted else None
            if current:
                seen.add(current)
        elif current and (m := HUNK.match(line)):
            start, count = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
            out[current].update(range(start, start + count))
    for p in wanted - seen:  # not in the diff: untracked, so new in full
        text = inventory.read_text(Path(root, p))
        out[p] = set(range(1, len(text.splitlines()) + 1)) if text else set()
    return out


def ranges(lines: Iterable[int]) -> list[list[int]]:
    """Sorted line numbers as inclusive [start, end] runs."""
    out: list[list[int]] = []
    for n in sorted(set(lines)):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def spans(runs: Iterable[Sequence[int]]) -> str:
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in runs)


def against(report: dict, changed: Mapping[str, Collection[int]]) -> dict:
    """The changed lines against the report: per measured file, how many of its changed lines the report has a
    statement on, how many of those ran and the runs of lines that did not; the changed files the report does not
    measure, with their changed line counts; and the totals."""
    files: dict[str, dict] = {}
    not_measured: dict[str, int] = {}
    for path in sorted(changed):
        lines = set(changed[path])
        got = report["files"].get(path)
        if got is None:
            not_measured[path] = len(lines)
            continue
        statements = lines & (got["executed"] | got["missing"])
        not_run = statements - got["executed"]
        files[path] = {"changed": len(lines), "statements": len(statements), "ran": len(statements) - len(not_run), "not_run": len(not_run), "not_run_ranges": ranges(not_run)}
    return {
        "sources": report["sources"],
        "measured": len(report["files"]),
        "files": files,
        "not_measured": not_measured,
        "changed": sum(len(v) for v in changed.values()),
        "statements": sum(f["statements"] for f in files.values()),
        "ran": sum(f["ran"] for f in files.values()),
        "not_run": sum(f["not_run"] for f in files.values()),
        "unmatched": report["unmatched"],
    }
