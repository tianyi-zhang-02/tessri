"""Python analyzer: import graph plus dotted-name and file-path strings found in code."""

from __future__ import annotations

import ast
import posixpath
import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Collection, Mapping

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


def _parse(path: str, text: str) -> _Info | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None

    info = _Info()
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
                info.doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info.imports.extend(_Import(a.name, (), 0) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            info.imports.append(_Import(node.module or "", tuple(a.name for a in node.names if a.name != "*"), node.level))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            s = node.value
            if len(s) > 300:
                continue
            if DOTTED_FULL.fullmatch(s) and not is_filename(s):  # "setup.py" is a path (below), not the module `setup`
                info.dotted.add(s)
            elif s.endswith(".") and DOTTED_FULL.fullmatch(s[:-1]):
                info.dotted.add(s[:-1])  # prefix of a name built at runtime: "pkg.mod." + name, f"pkg.mod.{name}"
            if ".py" in s:
                info.paths.update(PYPATH.findall(s))
            if len(s) <= 80 and _IDENT.fullmatch(s):
                info.idents.add(s)
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            lead = _leading_literal(node.args[0]) if name in ("import_module", "__import__") else None
            m = _DYN_PREFIX.fullmatch(lead) if lead and lead.endswith(".") else None
            if m:
                info.dyn.append((len(m.group("dots")), m.group("rest")))
    info.main_guard = any(_is_main_guard(n) for n in tree.body)
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
        for path, text in files.items():
            info = _parse(path, text)
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
