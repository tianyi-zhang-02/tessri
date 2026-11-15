"""JavaScript / TypeScript analyzer: import graph plus bundler, tsconfig and package.json wiring.

Handles .js .jsx .mjs .cjs .ts .tsx .mts .cts, plus the script blocks of .vue .svelte .astro
files and the import lines of .mdx files, so code imported only from a component is not
reported as unused.
"""

from __future__ import annotations

import posixpath
import re
from typing import Mapping

from . import Analyzer, LanguageResult, Repo, note
from ..cache import digest
from .jslex import Dynamic, Scan, scan
from .jsproject import Resolver

SOURCE_EXTS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
TEMPLATE_EXTS = (".vue", ".svelte", ".astro", ".mdx")

_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_SRC_ATTR = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""")
_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---", re.S)
_MDX_IMPORT = re.compile(r"""^(?:import|export)\b[^'"`;]*?\bfrom\s*(['"])([^'"\n]+)\1|^import\s*(['"])([^'"\n]+)\3""", re.M)

# Files a tool loads by name or by glob rather than by import.
_TOOL_CONFIG = re.compile(r"[\w-]+\.(?:config|conf)(?:\.[\w-]+)?\.[cm]?[jt]s|\.[\w-]+rc(?:\.[\w-]+)?\.[cm]?[jt]s|(?:gulpfile|Gruntfile)\.[cm]?[jt]s")
_STORY = re.compile(r".+\.(?:stories|story)\.[^.]+")
_TEST_NAME = re.compile(r".+[.\-](?:test|spec|e2e|cy)\.[cm]?[jt]sx?|(?:jest|vitest)\.setup\.[^.]+|setupTests\.[^.]+")
_TEST_DIRS = frozenset({"test", "tests", "__tests__", "__mocks__", "spec", "specs", "e2e", "cypress", "playwright"})


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    return bool(_TEST_NAME.fullmatch(parts[-1])) or any(d in _TEST_DIRS for d in parts[:-1])


NAMESPACE = "javascript/1"  # the cache namespace of what `_source` finds; bump the number when that changes


def _to_cache(found: Scan | None) -> dict:
    if found is None:
        return {"unparsed": True}
    return {
        "specs": list(found.specs),
        "strings": sorted(found.strings),
        "dynamic": [[d.head, d.tail, d.deep] for d in found.dynamic],
        "globs": list(found.globs),
        "contexts": [[directory, deep, regex] for directory, deep, regex in found.contexts],
        "main_guard": found.main_guard,
        "hashbang": found.hashbang,
    }


def _from_cache(data: object) -> Scan | None:
    """The `Scan` a cache entry holds, None for a file that did not scan; ValueError when the entry is not one."""
    if not isinstance(data, dict):
        raise ValueError("not an entry")
    if data.get("unparsed") is True:
        return None
    try:
        return Scan(
            specs=[str(s) for s in data["specs"]],
            strings={str(s) for s in data["strings"]},
            dynamic=[Dynamic(str(head), str(tail), bool(deep)) for head, tail, deep in data["dynamic"]],
            globs=[str(g) for g in data["globs"]],
            contexts=[(str(directory), bool(deep), None if regex is None else str(regex)) for directory, deep, regex in data["contexts"]],
            main_guard=bool(data["main_guard"]),
            hashbang=bool(data["hashbang"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed entry: {exc}") from exc


def _scanned(path: str, text: str, store) -> Scan | None:
    """`_source`, from the store when it holds the result for this text and this kind of file."""
    if store is None:
        return _source(path, text)
    key = f"{digest(text)}:{posixpath.splitext(path)[1]}"  # what `_source` does depends on the suffix as well
    kept = store.get(NAMESPACE, key)
    if kept is not None:
        try:
            return _from_cache(kept)
        except ValueError:
            pass  # not an entry of ours: read the file
    found = _source(path, text)
    store.put(NAMESPACE, key, _to_cache(found))
    return found


def _source(path: str, text: str) -> Scan | None:
    """Scan a source file, or the parts of a component / MDX file that hold code."""
    if path.endswith(SOURCE_EXTS):
        return scan(text)
    if path.endswith(".mdx"):
        found = Scan()
        found.specs = [m.group(2) or m.group(4) for m in _MDX_IMPORT.finditer(text)]
        return found
    blocks = _SCRIPT.findall(text)
    code = [body for _, body in blocks]
    if path.endswith(".astro"):
        front = _FRONTMATTER.match(text)
        code.insert(0, front.group(1) if front else "")
    result = scan("\n".join(code))
    if result is not None:
        for attrs, _ in blocks:
            src = _SRC_ATTR.search(attrs)  # <script src="./legacy.ts">
            if src:
                result.specs.append(src.group(1))
    return result


class JavaScriptAnalyzer(Analyzer):
    name = "javascript"

    def handles(self, path: str) -> bool:
        return path.endswith(SOURCE_EXTS + TEMPLATE_EXTS)

    def run(self, files: Mapping[str, str], repo: Repo) -> LanguageResult:
        res = Resolver(repo, files)
        edges: dict[str, set[str]] = {}
        provenance: dict[str, dict[str, str]] = {}
        unparsed: set[str] = set()
        roots: dict[str, list[str]] = {}
        tests = {p for p in files if is_test_path(p)}

        for path, text in files.items():
            found = _scanned(path, text, repo.cache)
            if found is None:
                unparsed.add(path)
                continue
            deps: set[str] = set()
            prov: dict[str, str] = {}  # target -> strongest kind of evidence; see analyzers.KINDS
            for spec in found.specs:  # recognized literal dependency syntax: import, export from, require, literal import(), new URL, reference path, script src
                hit = res.resolve(path, spec)
                deps |= hit
                for t in hit:
                    note(prov, t, "import")
            for value in found.strings:
                hit = res.resolve_string(path, value)
                deps |= hit
                for t in hit:
                    note(prov, t, "string")
            for d in found.dynamic:
                hit = res.dynamic(path, d.head, d.tail, d.deep)
                deps |= hit
                for t in hit:
                    note(prov, t, "dynamic")
            for pattern in found.globs:
                hit = res.glob(path, pattern)
                deps |= hit
                for t in hit:
                    note(prov, t, "dynamic")
            for directory, deep, regex in found.contexts:
                hit = res.context(path, directory, deep, regex)
                deps |= hit
                for t in hit:
                    note(prov, t, "dynamic")
            deps.discard(path)
            prov.pop(path, None)
            edges[path] = deps
            provenance[path] = prov

            why: list[str] = []
            name = posixpath.basename(path)
            if found.hashbang:
                why.append("shebang")
            if found.main_guard:
                why.append("main-guard")
            if _TOOL_CONFIG.fullmatch(name):
                why.append("tool-config")
            if name.endswith((".d.ts", ".d.mts", ".d.cts")):
                why.append("declaration-file")  # picked up by tsconfig include globs, not by import
            if _STORY.fullmatch(name) or ".storybook" in path.split("/")[:-1]:
                why.append("storybook")
            if path.endswith(".mdx"):
                why.append("mdx-content")
            framework = res.framework_entry(path)
            if framework:
                why.append(f"{framework} convention")
            if why:
                roots[path] = why

        for path in unparsed:
            roots.setdefault(path, []).append("unparsed")
        for path, why in res.package_entries().items():
            roots.setdefault(path, []).extend(why)
        roots = {p: why for p, why in roots.items() if p in files and p not in tests}

        return LanguageResult(edges=edges, roots=roots, tests=tests, unparsed=unparsed, resolve_reference=lambda ref: set(), provenance=provenance)
