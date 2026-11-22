"""Which functions and classes a change touched, file by file, from the diff's hunks and each language's definitions.

The hunks of `git diff -U0 -M <base>` say which lines the change added or changed in the working tree and which it
removed from the base. Python's `ast` gives every `def` and `class` with its span, and `analyzers.jsdefs` every
function, class, method, named object and type of a JavaScript or TypeScript file, in the working tree and in the
base, so a line maps to the innermost definition that holds it, named the way a reader names it (`Class.method`,
`outer.inner`); lines outside every definition are module level. A definition whose name is new is added, one whose
name is gone is removed, and the rest that a hunk touches is changed, so a renamed function is a removal and an
addition. A file in another language, or one that cannot be read, says so instead of guessing.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from . import inventory
from . import since as since_mod
from .analyzers import jsdefs
from .coverage import _unquote

LISTED = 6  # names a page shows per file; the JSON holds them all
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
READ = "Python, JavaScript and TypeScript"  # the languages with a reader, as the reason names them


def hunks(root: Path, base: str) -> dict[str, tuple[set[int], set[int]]]:
    """Path as it is now -> (lines the change added or changed in the working tree, lines it removed from the base),
    from one diff of the working tree against `base`; a moved file is under its new name with only the edits made
    on the way. A file git does not know is not here: it is new in full."""
    out: dict[str, tuple[set[int], set[int]]] = {}
    current: tuple[set[int], set[int]] | None = None
    header = False
    for line in since_mod._git(root, "diff", "--relative", "--no-prefix", "-U0", "-M", base).splitlines():
        if line.startswith("diff --git "):
            header, current = True, None
        elif header and line.startswith("+++ "):
            header = False
            name = _unquote(line[4:].rstrip("\t"))
            current = None if name == "/dev/null" else out.setdefault(name, (set(), set()))
        elif current is not None and (m := HUNK.match(line)):
            old_start, old_count, new_start, new_count = (int(m.group(i)) if m.group(i) is not None else None for i in range(1, 5))
            current[1].update(range(old_start, old_start + (1 if old_count is None else old_count)))
            current[0].update(range(new_start, new_start + (1 if new_count is None else new_count)))
    return out


def definitions(text: str) -> list[tuple[str, int, int]] | None:
    """Every `def` and `class` of a Python source as (dotted name, first line, last line), in source order and with
    its decorators; None when the source does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    found: list[tuple[str, int, int]] = []

    def walk(nodes: Iterable[ast.AST], prefix: str) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{node.name}"
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                found.append((name, start, node.end_lineno or node.lineno))
                walk(node.body, name + ".")
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)) or type(node).__name__ in ("TryStar", "Match"):
                walk(ast.iter_child_nodes(node), prefix)  # a definition under a guard still has its name

    walk(tree.body, "")
    return found


Reader = Callable[[str], list[tuple[str, int, int]] | None]
READERS: dict[str, tuple[Reader, str]] = {  # language, lowercased -> (its reader, why it can fail)
    "python": (definitions, "does not parse as Python"),
    "javascript": (jsdefs.definitions, "could not be read as JavaScript: a brace, string, template or comment never closes"),
    "typescript": (jsdefs.definitions, "could not be read as TypeScript: a brace, string, template or comment never closes"),
}


def _holders(lines: Iterable[int], defs: Sequence[tuple[str, int, int]]) -> tuple[list[str], bool]:
    """The innermost definition holding each line, named once each in the order first touched, and whether any line
    lies outside every definition (module level)."""
    names: list[str] = []
    outside = False
    for n in sorted(set(lines)):
        holder = None
        for name, start, end in defs:  # source order: a nested definition comes after its holder and is narrower
            if start <= n <= end:
                holder = name
        if holder is None:
            outside = True
        elif holder not in names:
            names.append(holder)
    return names, outside


def _base_text(root: Path, base: str, path: str) -> str | None:
    text = since_mod._git(root, "show", f"{base}:{path}", check=False, binary=True)
    return text.decode("utf-8", "replace") if text else None


def compute(root: Path, base: str, files: Sequence[tuple[str, str, str | None, str | None]]) -> dict[str, dict]:
    """Path -> what the change did to the definitions of each file in `files`, given as (path, state, path at the
    base when moved, language): `available` with `changed`, `added`, `removed` and `module_level`, or `available`
    false with the reason."""
    found = hunks(root, base) if files else {}
    out: dict[str, dict] = {}
    for path, state, origin, language in files:
        reader = READERS.get((language or "").lower())
        if reader is None:
            out[path] = {"available": False, "reason": f"definitions are read for {READ}, not {language or 'this kind of file'}"}
            continue
        read, failure = reader
        old_text = None if state == "added" else _base_text(root, base, origin or path)
        new_text = None if state == "deleted" else inventory.read_text(Path(root, path))
        old_defs = read(old_text) if old_text is not None else []
        new_defs = read(new_text) if new_text is not None else []
        if old_defs is None or new_defs is None:
            out[path] = {"available": False, "reason": f"the file {failure}" + (" at the base" if old_defs is None and new_defs is not None else "")}
            continue
        new_lines, old_lines = found.get(path, (set(), set()))
        if path not in found and state == "added" and new_text is not None:  # untracked: new in full
            new_lines = set(range(1, len(new_text.splitlines()) + 1))
        if state == "deleted" and old_text is not None:
            old_lines = set(range(1, len(old_text.splitlines()) + 1))
        touched_new, outside_new = _holders(new_lines, new_defs)
        touched_old, outside_old = _holders(old_lines, old_defs)
        old_names = {name for name, _, _ in old_defs}
        new_names = {name for name, _, _ in new_defs}
        touched = set(touched_new) | set(touched_old)
        order = [name for name, _, _ in new_defs] + [name for name, _, _ in old_defs if name not in new_names]
        seen: set[str] = set()
        changed, added, removed = [], [], []
        for name in order:
            if name in seen or name not in touched:
                continue
            seen.add(name)
            if name not in old_names:
                added.append(name)
            elif name not in new_names:
                removed.append(name)
            else:
                changed.append(name)
        out[path] = {"available": True, "changed": changed, "added": added, "removed": removed, "module_level": outside_new or outside_old}
    return out


def line(path: str, s: dict, limit: int = LISTED) -> str | None:
    """One Markdown line for a file's definitions, or None when there is nothing to name."""
    if not s.get("available"):
        return None
    parts = []
    for word, names in (("added", s["added"]), ("changed", s["changed"]), ("removed", s["removed"])):
        if names:
            shown = ", ".join(f"`{n}`" for n in names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")
            parts.append(f"{word} {shown}")
    if s["module_level"]:
        parts.append("module-level code" if parts else "module-level code only")
    return f"`{path}`: " + "; ".join(parts) if parts else None


def lines(rows: Sequence[dict], limit: int = LISTED) -> list[str]:
    """The Markdown block for the rows of a triage table: a bullet per file that has definitions to name, then one
    sentence for the files whose definitions were not read, or nothing at all when no row carries `symbols`."""
    named = [line(r["path"], r["symbols"], limit) for r in rows if "symbols" in r]
    bullets = [f"- {text}" for text in named if text]
    unread = [r for r in rows if "symbols" in r and not r["symbols"].get("available")]
    if not bullets and not unread:
        return []
    out = ["What changed in them, by definition:", ""] if bullets else []
    out += bullets
    if unread:
        reasons = sorted({r["symbols"]["reason"] for r in unread})
        out += ["", f"Not named for {len(unread)} file{'s' if len(unread) != 1 else ''}: " + "; ".join(reasons) + "."] if bullets else [f"Definitions are not named for {len(unread)} file{'s' if len(unread) != 1 else ''}: " + "; ".join(reasons) + "."]
    return out
