"""Which of the tests that reach a changed file name the definitions the change touched.

`triage` lists the test files that reach a change by static imports; `symbols` names the definitions the change
touched. This joins the two: for each touched definition, the reaching tests whose code uses its name. A test's code
is read with the language's own token reader (Python's `tokenize`, the JavaScript reader of `analyzers/jsdefs.py`),
so a name counts when it appears as an identifier in code, not in a string or a comment.

A name in a test is a mention, not an assertion: the test may use the name without checking what it does, and a test
can exercise a definition without naming it, through a caller, a fixture or a dynamic call. The pages say "named in"
and the note says what that is.

Only the last segment of a name is searched (`Shape.area` -> `area`), and only when it is an identifier of at least
`MIN_LENGTH` characters, not private by convention (`_helper`, `#secret`: a test naming one is the exception, so
being named by none is no finding) and not one every module may have (`default`, `constructor`, `exports`, dunder
methods): the rest are listed as not searched rather than said to be named by nobody. Test files in the change and deleted
files are skipped: a test's own definitions are not what other tests name, nothing reaches a file that is gone, and
`check` reports the imports a deletion leaves dangling.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import Mapping, Sequence

from . import inventory
from .analyzers import jsdefs

MIN_LENGTH = 3
LISTED = 6  # names a sentence shows per group; the JSON holds them all
STRUCTURAL = frozenset(("default", "constructor", "exports"))
_IDENT = re.compile(r"[A-Za-z_$#][\w$]*\Z")
_DUNDER = re.compile(r"__\w+__\Z")


def searchable(name: str) -> str | None:
    """The identifier to look for in a test for the definition `name`, or None when it is too short, private or too
    common to mean anything: `Shape.area` -> `area`, `f` -> None, `_join` -> None, `default` -> None, a test title -> None."""
    last = name.rsplit(".", 1)[-1]
    if not _IDENT.match(last) or len(last) < MIN_LENGTH or last[0] in "_#" or last in STRUCTURAL or _DUNDER.match(last):
        return None
    return last


def identifiers(text: str, language: str | None) -> set[str] | None:
    """The identifiers in the code of `text`, strings and comments apart, or None when the language has no token
    reader here or the text does not tokenize."""
    lang = (language or "").lower()
    if lang == "python":
        try:
            return {t.string for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.NAME}
        except (tokenize.TokenError, SyntaxError):
            return None
    if lang in ("javascript", "typescript"):
        toks = jsdefs.tokens(text)
        return None if toks is None else {t.text for t in toks if t.kind == "word"}
    return None


def compute(root: Path, rows: Sequence[dict], reach: Mapping[str, Mapping[str, int]], languages: Mapping[str, str | None]) -> None:
    """Add to the `symbols` of every row whose definitions were read, test rows and deleted files apart: `named_in`,
    each touched definition -> the reaching tests whose code uses its name, nearest first; `unsearched`, the names too
    short or too common to search; and `tests_unread`, the reaching tests that could not be read, when there are any.
    `reach` is path -> test path -> distance in imports, `languages` the language of each test path."""
    cache: dict[str, set[str] | None] = {}

    def names_in(test: str) -> set[str] | None:
        if test not in cache:
            text = inventory.read_text(Path(root, test))
            cache[test] = identifiers(text, languages.get(test)) if text is not None else None
        return cache[test]

    for row in rows:
        s = row.get("symbols")
        if not s or not s.get("available") or row.get("test") or row.get("change") == "deleted":
            continue
        near = reach.get(row["path"], {})
        tests = sorted(near, key=lambda p: (near[p], p))
        readable = [t for t in tests if names_in(t) is not None]
        named_in: dict[str, list[str]] = {}
        unsearched: list[str] = []
        for name in [*s["added"], *s["changed"], *s["removed"]]:
            ident = searchable(name)
            if ident is None:
                unsearched.append(name)
            else:
                named_in[name] = [t for t in readable if ident in (names_in(t) or ())]
        s["named_in"] = named_in
        s["unsearched"] = unsearched
        if len(readable) < len(tests):
            s["tests_unread"] = [t for t in tests if t not in readable]


def summary(rows: Sequence[dict]) -> dict | None:
    """Counts over the rows that carry `named_in`: the definitions touched, those a reaching test names, those none
    does and those not searched; None when no row was searched."""
    searched = [r["symbols"] for r in rows if "named_in" in (r.get("symbols") or {})]
    if not searched:
        return None
    named = sum(1 for s in searched for tests in s["named_in"].values() if tests)
    unnamed = sum(1 for s in searched for tests in s["named_in"].values() if not tests)
    unsearched = sum(len(s["unsearched"]) for s in searched)
    return {"touched": named + unnamed + unsearched, "named": named, "unnamed": unnamed, "unsearched": unsearched}


def _join(items: Sequence[str], limit: int = LISTED) -> str:
    if len(items) > limit:
        return ", ".join(items[:limit]) + f" and {len(items) - limit} more"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _groups(rows: Sequence[dict]) -> tuple[list[tuple[str, str, list[str]]], list[tuple[str, str]], list[tuple[str, str, list[str]]], list[str], list[str]]:
    """(named, unnamed, removed but still named, unsearched, unread tests) over the rows, each name with its file."""
    named: list[tuple[str, str, list[str]]] = []
    unnamed: list[tuple[str, str]] = []
    gone: list[tuple[str, str, list[str]]] = []
    unsearched: list[str] = []
    unread: list[str] = []
    for r in rows:
        s = r.get("symbols") or {}
        if "named_in" not in s:
            continue
        for name, tests in s["named_in"].items():
            if not tests:
                unnamed.append((name, r["path"]))
            elif name in s["removed"]:
                gone.append((name, r["path"], tests))
            else:
                named.append((name, r["path"], tests))
        unsearched += s["unsearched"]
        unread += [t for t in s.get("tests_unread", ()) if t not in unread]
    return named, unnamed, gone, unsearched, unread


def _where(tests: Sequence[str]) -> str:
    return f"`{tests[0]}`" if len(tests) == 1 else f"{len(tests)} test files"


def _labels(rows: Sequence[dict]) -> dict[tuple[str, str], str]:
    """(name, path) -> how the sentence says it: the name alone, or with its file when another file has the same name."""
    seen: dict[str, set[str]] = {}
    for r in rows:
        for name in (r.get("symbols") or {}).get("named_in", {}):
            seen.setdefault(name, set()).add(r["path"])
    return {(n, p): f"`{n}`" + (f" in `{p}`" if len(paths) > 1 else "") for n, paths in seen.items() for p in paths}


def line(rows: Sequence[dict], limit: int = LISTED) -> str | None:
    """One Markdown paragraph: which touched definitions a reaching test names, which none does, which were removed
    but are still named, which were not searched; None when nothing was searched."""
    named, unnamed, gone, unsearched, unread = _groups(rows)
    if not (named or unnamed or gone or unsearched):
        return None
    label = _labels(rows)
    clauses = []
    if named:
        clauses.append(_join([f"{label[n, p]} ({_where(t)})" for n, p, t in named], limit) + (" is named" if len(named) == 1 else " are named"))
    if unnamed:
        clauses.append(_join([label[n, p] for n, p in unnamed], limit) + (" is named in none" if len(unnamed) == 1 else " are named in none"))
    if gone:
        clauses.append(_join([f"{label[n, p]} ({_where(t)})" for n, p, t in gone], limit) + (" was removed but is still named" if len(gone) == 1 else " were removed but are still named"))
    if unsearched:
        clauses.append(_join([f"`{n}`" for n in unsearched], limit) + (" was not searched, being too short, private or too common" if len(unsearched) == 1 else " were not searched, being too short, private or too common"))
    if unread:
        clauses.append(f"{len(unread)} reaching test file{'s' if len(unread) != 1 else ''} could not be read")
    return "By name, in the tests that reach their file: " + "; ".join(clauses) + "."


def open_items(rows: Sequence[dict], limit: int = LISTED) -> list[dict]:
    """What a person has to settle: definitions no reaching test names, and removed definitions a test still names."""
    named, unnamed, gone, _, _ = _groups(rows)
    items = []
    if unnamed:
        one = len(unnamed) == 1
        items.append({
            "kind": "definitions-unnamed",
            "text": f"No test that reaches the file names {_join([f'`{n}` (`{p}`)' for n, p in unnamed], limit)}: find the test that exercises "
                    f"{'it' if one else 'them'} without saying the name, or write one.",
            "files": sorted({p for _, p in unnamed}),
        })
    if gone:
        one = len(gone) == 1
        items.append({
            "kind": "removed-still-named",
            "text": f"{_join([f'`{n}` (`{p}`)' for n, p, _ in gone], limit)} {'was' if one else 'were'} removed, but "
                    f"{_join(sorted({f'`{t}`' for _, _, tests in gone for t in tests}), limit)} still {'names' if one and len(gone[0][2]) == 1 else 'name'} "
                    f"{'it' if one else 'them'}: run or update {'that test' if one and len(gone[0][2]) == 1 else 'those tests'}.",
            "files": sorted({t for _, _, tests in gone for t in tests}),
        })
    return items
