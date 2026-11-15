"""Python analyzer: import graph plus dotted-name and file-path strings found in code."""

from __future__ import annotations

import ast
import posixpath
import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Collection, Mapping

from ..cache import digest
from ..textrefs import DOTTED_FULL, PYPATH, PathIndex, is_filename
from . import Analyzer, LanguageResult, Repo, note

# Files that something outside the repository runs or imports by convention.
SPECIAL_FILES = frozenset({"__main__.py", "setup.py", "manage.py", "wsgi.py", "asgi.py", "noxfile.py", "fabfile.py", "conf.py"})


_IDENT = re.compile(r"[A-Za-z_]\w*")
# Leading literal of a dynamic import such as f".{name}" or "pkg.sub." + name.
_DYN_PREFIX = re.compile(r"(?P<dots>\.*)(?P<rest>(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)?)\.?")


def _leading_literal(arg: ast.expr) -> str | None:
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
    elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        first = arg.left
    else:
        return None
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


@dataclass(frozen=True)
class _Import:
    module: str  # "" for `from . import x`
    names: tuple[str, ...]
    level: int


@dataclass
class _Info:
    imports: list[_Import] = field(default_factory=list)
    dotted: set[str] = field(default_factory=set)  # strings that look like `pkg.mod.Name`
    paths: set[str] = field(default_factory=set)  # strings that mention `some/file.py`
    idents: set[str] = field(default_factory=set)  # bare-name strings: candidate submodule names for a dynamic import
    dyn: list[tuple[int, str]] = field(default_factory=list)  # (relative level, prefix) of import_module(f"prefix.{x}")
    main_guard: bool = False
    doc_lines: set[int] = field(default_factory=set)
    modname: str = ""
    is_package: bool = False


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(d in ("test", "tests") or d.endswith("_tests") for d in parts[:-1])


def _is_main_guard(node: ast.stmt) -> bool:
    if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)):
        return False
    test = node.test
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, *test.comparators]
    return any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides) and any(
        isinstance(s, ast.Constant) and s.value == "__main__" for s in sides
    )


_SKIP_FIELDS = frozenset({"ctx", "op", "ops", "type_comment", "type_ignores"})  # fields that never hold a string or a call
_STMT_LISTS = ("body", "orelse", "finalbody", "handlers", "cases")  # a statement's children that are statements, handlers or cases
_DEFS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)  # the nodes a docstring can open
_FIELDS: dict[type, tuple[str, ...]] = {}
NAMESPACE = "python/1"  # the cache namespace of what `_parse` finds; bump the number when that changes


def _fields(cls: type) -> tuple[str, ...]:
    found = _FIELDS.get(cls)
    if found is None:
        found = _FIELDS[cls] = tuple(name for name in cls._fields if name not in _SKIP_FIELDS)
    return found


def _quote_counts(text: str) -> list[int]:
    """counts[i] = how many of the first i lines hold a quote. Every string literal does, so a statement whose lines
    hold none holds no string and no dynamic import, and its expressions need no visit."""
    counts = [0]
    n = 0
    for line in text.split("\n"):
        if '"' in line or "'" in line:
            n += 1
        counts.append(n)
    return counts


def _parse(path: str, text: str) -> _Info | None:
    """One pass over the tree. The statements are walked for imports and docstrings; the expressions of a statement,
    for strings and dynamic imports, only when one of its lines holds a quote. Children are taken by type, leaving
    out the fields that cannot hold a string, so the walk reads a fraction of what `ast.walk` would and finds the
    same things."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    info = _Info()
    docstrings: set[int] = set()
    counts = _quote_counts(text)
    last = len(counts) - 1

    def quoted(first: int, end: int) -> bool:
        first, end = max(first, 1), min(end, last)
        return end >= first and counts[end] > counts[first - 1]

    def string(s: str) -> None:
        if len(s) > 300:
            return
        if DOTTED_FULL.fullmatch(s) and not is_filename(s):  # "setup.py" is a path (below), not the module `setup`
            info.dotted.add(s)
        elif s.endswith(".") and DOTTED_FULL.fullmatch(s[:-1]):
            info.dotted.add(s[:-1])  # prefix of a name built at runtime: "pkg.mod." + name, f"pkg.mod.{name}"
        if ".py" in s:
            info.paths.update(PYPATH.findall(s))
        if len(s) <= 80 and _IDENT.fullmatch(s):
            info.idents.add(s)

    def expressions(top: ast.AST) -> None:
        stack = [top]
        while stack:
            node = stack.pop()
            cls = type(node)
            if cls is ast.Constant:
                if type(node.value) is str and id(node) not in docstrings:
                    string(node.value)
                continue
            if cls is ast.Call and node.args:
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                lead = _leading_literal(node.args[0]) if name in ("import_module", "__import__") else None
                m = _DYN_PREFIX.fullmatch(lead) if lead and lead.endswith(".") else None
                if m:
                    info.dyn.append((len(m.group("dots")), m.group("rest")))
            for field_name in _fields(cls):
                value = getattr(node, field_name)
                if isinstance(value, list):
                    stack.extend(x for x in reversed(value) if isinstance(x, ast.AST))
                elif isinstance(value, ast.AST):
                    stack.append(value)

    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        cls = type(node)
        if cls is ast.Import:
            info.imports.extend(_Import(a.name, (), 0) for a in node.names)
            continue
        if cls is ast.ImportFrom:
            info.imports.append(_Import(node.module or "", tuple(a.name for a in node.names if a.name != "*"), node.level))
            continue
        body = getattr(node, "body", None)
        if not isinstance(body, list):  # a simple statement: its expressions, when one of its lines holds a quote
            if quoted(node.lineno, node.end_lineno or node.lineno):
                expressions(node)
            continue
        # The module, a compound statement, an exception handler or a match case: its statements go on the stack in
        # source order, and its header (decorators, defaults, a test, a pattern) is walked when a line of it holds a
        # quote. A docstring is noted before its statement is reached, so the walk leaves it alone.
        if cls in _DEFS and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
                info.doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
        children: list[ast.AST] = []
        for field_name in _STMT_LISTS:
            children.extend(getattr(node, field_name, None) or ())
        stack.extend(reversed(children))
        if cls is ast.Module or not body:
            continue
        start = node.lineno if hasattr(node, "lineno") else node.pattern.lineno  # a match case has no line of its own
        decorators = getattr(node, "decorator_list", None)
        if decorators:
            start = min(start, decorators[0].lineno)
        if quoted(start, body[0].lineno):
            for field_name in _fields(cls):
                if field_name in _STMT_LISTS:
                    continue
                value = getattr(node, field_name)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, ast.AST):
                            expressions(item)
                elif isinstance(value, ast.AST):
                    expressions(value)
    info.main_guard = any(_is_main_guard(n) for n in tree.body)
    return info


def _ranges(lines: set[int]) -> list[list[int]]:
    """Runs of consecutive line numbers as [first, last] pairs."""
    out: list[list[int]] = []
    for n in sorted(lines):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def _to_cache(info: _Info | None) -> dict:
    """What `_parse` found, as JSON. The names the tree gives a file are set by `run` and are not in it."""
    if info is None:
        return {"unparsed": True}
    return {
        "imports": [[i.module, list(i.names), i.level] for i in info.imports],
        "dotted": sorted(info.dotted),
        "paths": sorted(info.paths),
        "idents": sorted(info.idents),
        "dyn": [[level, prefix] for level, prefix in info.dyn],
        "main_guard": info.main_guard,
        "doc_lines": _ranges(info.doc_lines),
    }


def _from_cache(data: object) -> _Info | None:
    """The `_Info` a cache entry holds, None for a file that did not parse; ValueError when the entry is not one."""
    if not isinstance(data, dict):
        raise ValueError("not an entry")
    if data.get("unparsed") is True:
        return None
    try:
        info = _Info(
            imports=[_Import(str(module), tuple(str(n) for n in names), int(level)) for module, names, level in data["imports"]],
            dotted={str(s) for s in data["dotted"]},
            paths={str(s) for s in data["paths"]},
            idents={str(s) for s in data["idents"]},
            dyn=[(int(level), str(prefix)) for level, prefix in data["dyn"]],
            main_guard=bool(data["main_guard"]),
        )
        for first, end in data["doc_lines"]:
            info.doc_lines.update(range(int(first), int(end) + 1))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed entry: {exc}") from exc
    return info


def _names(path: str, pyset: Collection[str]) -> tuple[str, bool, list[str]]:
    """Return (primary dotted name, is __init__, every dotted alias the file can be imported as)."""
    parts = path.split("/")
    stem = parts[-1][:-3]
    is_pkg = stem == "__init__"
    dirs = parts[:-1]

    primary = [] if is_pkg else [stem]
    i = len(dirs)
    while i > 0 and "/".join(dirs[:i]) + "/__init__.py" in pyset:
        primary.insert(0, dirs[i - 1])
        i -= 1

    aliases: list[str] = []

    def add(chunks: list[str]) -> None:
        if chunks and all(c.isidentifier() for c in chunks):
            name = ".".join(chunks)
            if name not in aliases:
                aliases.append(name)

    add(primary)
    from_root = dirs + ([] if is_pkg else [stem])
    add(from_root)
    if from_root and from_root[0] in ("src", "lib"):
        add(from_root[1:])
    return ".".join(primary), is_pkg, aliases


class PythonAnalyzer(Analyzer):
    name = "python"

    def handles(self, path: str) -> bool:
        return path.endswith(".py")

    def run(self, files: Mapping[str, str], repo: Repo) -> LanguageResult:
        pyset = set(files)
        infos: dict[str, _Info] = {}
        unparsed: set[str] = set()
        store = repo.cache
        for path, text in files.items():
            info: _Info | None = None
            key = digest(text) if store is not None else None
            fresh = True
            if key is not None:
                kept = store.get(NAMESPACE, key)
                if kept is not None:
                    try:
                        info, fresh = _from_cache(kept), False
                    except ValueError:
                        pass  # not an entry of ours: read the file
            if fresh:
                info = _parse(path, text)
                if key is not None:
                    store.put(NAMESPACE, key, _to_cache(info))
            if info is None:
                unparsed.add(path)
            else:
                infos[path] = info

        index: dict[str, list[str]] = defaultdict(list)
        for path in pyset:
            primary, is_pkg, aliases = _names(path, pyset)
            if path in infos:
                infos[path].modname, infos[path].is_package = primary, is_pkg
            for alias in aliases:
                index[alias].append(path)

        def chain(name: str) -> set[str]:
            """`a.b.c` runs a/__init__, a/b/__init__ and a/b/c, so all of them are depended on."""
            parts = name.split(".")
            found: set[str] = set()
            for i in range(1, len(parts) + 1):
                found.update(index.get(".".join(parts[:i]), ()))
            return found

        def resolve_reference(ref: str) -> set[str]:
            parts = re.split(r"[.:]", ref)
            for i in range(len(parts), 0, -1):
                name = ".".join(parts[:i])
                if name in index:
                    return chain(name)
            return set()

        def qualify(info: _Info, level: int, module: str) -> str | None:
            """Absolute dotted name of `module` as written in `info`'s file at relative `level`."""
            if not level:
                return module
            pkg = info.modname if info.is_package else info.modname.rpartition(".")[0]
            parts = pkg.split(".") if pkg else []
            if level - 1 > len(parts):
                return None
            return ".".join(x for x in (".".join(parts[: len(parts) - (level - 1)]), module) if x)

        def dynamic_targets(info: _Info) -> set[str]:
            """`for name in ("a", "b"): import_module(f"pkg.{name}")` loads pkg.a and pkg.b."""
            found: set[str] = set()
            for level, prefix in info.dyn:
                base = qualify(info, level, prefix)
                if base is None:
                    continue
                for ident in info.idents:
                    found.update(index.get(f"{base}.{ident}" if base else ident, ()))
            return found

        def targets(info: _Info, imp: _Import) -> tuple[set[str], set[str]]:
            """(every file the import runs, the ones the statement itself names)."""
            full = qualify(info, imp.level, imp.module)
            if full is None:
                return set(), set()
            named: set[str] = set()
            found = chain(full) if full else set()
            symbols = not imp.names  # `import a.b` and `from a import *` use the module itself
            for name in imp.names:
                hit = index.get(f"{full}.{name}" if full else name, ())
                if hit:
                    named.update(hit)
                    found.update(hit)
                else:
                    symbols = True  # a name defined in the module, not a submodule
            if symbols and full:
                named.update(index.get(full, ()))
            return found, named

        paths = PathIndex(pyset)
        edges: dict[str, set[str]] = {}
        indirect: dict[str, set[str]] = {}
        provenance: dict[str, dict[str, str]] = {}
        for path, info in infos.items():
            found: set[str] = set()
            imported: set[str] = set()  # what the import statements name, as opposed to what they run on the way
            prov: dict[str, str] = {}  # target -> strongest kind of evidence; see analyzers.KINDS
            for imp in info.imports:
                ran, said = targets(info, imp)
                found |= ran
                imported |= said
                for t in said:
                    note(prov, t, "import")
                for t in ran - said:
                    note(prov, t, "package")
            for ref in info.dotted:  # a dotted name in a string, including the argument of a literal import_module() call
                hit = resolve_reference(ref)
                found |= hit
                for t in hit:
                    note(prov, t, "string")
            for token in info.paths:
                hit = paths.resolve(token)
                found |= hit
                for t in hit:
                    note(prov, t, "string")
            dyn = dynamic_targets(info)
            found |= dyn
            for t in dyn:
                note(prov, t, "dynamic")
            found.discard(path)
            prov.pop(path, None)
            edges[path] = found
            indirect[path] = found - imported
            provenance[path] = prov

        tests = {p for p in pyset if is_test_path(p)}
        roots: dict[str, list[str]] = {}
        for path in pyset - tests:
            why = []
            if path in unparsed:
                why.append("unparsed")
            if path in infos and infos[path].main_guard:
                why.append("main-guard")
            if posixpath.basename(path) in SPECIAL_FILES:
                why.append("special-file")
            if why:
                roots[path] = why

        return LanguageResult(
            edges=edges,
            indirect=indirect,
            roots=roots,
            tests=tests,
            unparsed=unparsed,
            comment_lines={p: i.doc_lines for p, i in infos.items()},
            resolve_reference=resolve_reference,
            provenance=provenance,
            ambiguous=dict(paths.ambiguous),
        )
