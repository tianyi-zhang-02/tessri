"""Language analyzer plugin API.

The reachability engine (graph.py) knows nothing about any language. It consumes the
`LanguageResult` that an analyzer returns for the files it handles:

  edges      file -> files it depends on (imports, includes, requires ...)
  indirect   optional: the part of `edges` that no import statement makes: a parent package that runs as a
             side effect of `import a.b.c`, a name in a string, a dynamic import. Reachability counts these;
             the module graph does not
  roots      file -> why it is an entry point (script guard, main(), CLI entry ...)
  tests      files that are tests; code reached only from these is "test-only"
  unparsed   files the analyzer could not parse; they are treated as entry points
             so that nothing they might import is wrongly reported as unused
  resolve_reference
             maps a name found in config/scripts (`pkg.mod.Class`) to files
  provenance optional: file -> target -> the kind of evidence behind that edge, one of KINDS below, the
             strongest when several apply. `impact` uses it to follow only recognized dependency syntax
             on request; an analyzer that leaves it empty keeps working and its edges count as "unknown"

To support a new language, subclass `Analyzer` and register it, either in
`BUILTIN` below or from a third-party package through the `tessri.analyzers`
entry-point group (the entry point must resolve to an `Analyzer` subclass). The group the package had under its old
name is read as well through 0.2.x.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from importlib import metadata

from typing import Callable, Mapping


@dataclass(frozen=True)
class Repo:
    """What an analyzer may know beyond the files it handles: every path, and any file's text.

    Project metadata lives in files no analyzer owns (`tsconfig.json`, `package.json`,
    `go.mod`), so resolution needs to read them.
    """

    paths: frozenset[str]
    read: Callable[[str], str | None]  # None when the file is missing, binary or too large


# Kinds of evidence behind an edge, strongest first. "import": recognized literal dependency syntax names the
# target (a Python import statement; for JS/TS an import, export-from, require, literal import(), new URL or
# reference path). "package": a parent package initializer that Python runs for such a statement. "dynamic": a
# supported computed-import, glob or context pattern expands to the target. "string": a dotted name or path in an
# ordinary string resolves to it. "unknown": the analyzer gave no provenance. The names describe evidence, not
# what runs.
KINDS = ("import", "package", "dynamic", "string", "unknown")
_RANK = {kind: i for i, kind in enumerate(KINDS)}


def note(provenance: dict[str, str], target: str, kind: str) -> None:
    """Record `kind` for `target`, keeping the strongest evidence seen for the pair."""
    old = provenance.get(target)
    if old is None or _RANK[kind] < _RANK[old]:
        provenance[target] = kind


@dataclass
class LanguageResult:
    edges: dict[str, set[str]] = field(default_factory=dict)
    indirect: dict[str, set[str]] = field(default_factory=dict)  # edges that no import statement makes; see above
    roots: dict[str, list[str]] = field(default_factory=dict)
    tests: set[str] = field(default_factory=set)
    unparsed: set[str] = field(default_factory=set)
    comment_lines: dict[str, set[int]] = field(default_factory=dict)  # extra lines to count as comments (docstrings)
    resolve_reference: Callable[[str], set[str]] = lambda ref: set()
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)  # file -> target -> kind, see KINDS
    ambiguous: dict[str, int] = field(default_factory=dict)  # a file name in a string that fits several files -> how many; it named none, and the report lists it. Last, so positional callers keep working


class Analyzer(ABC):
    name: str = ""

    @abstractmethod
    def handles(self, path: str) -> bool:
        """Whether this analyzer covers the file at repo-relative posix `path`."""

    @abstractmethod
    def run(self, files: Mapping[str, str], repo: Repo) -> LanguageResult:
        """Analyse every handled file at once. `files` maps path -> text."""


def load_analyzers() -> list[Analyzer]:
    from .javascript import JavaScriptAnalyzer
    from .python import PythonAnalyzer

    classes: list[type[Analyzer]] = [PythonAnalyzer, JavaScriptAnalyzer]
    try:
        for ep in metadata.entry_points(group="tessri.analyzers"):
            try:
                cls = ep.load()
            except Exception:  # a broken third-party plugin must not break the scan
                continue
            if isinstance(cls, type) and issubclass(cls, Analyzer) and cls not in classes:
                classes.append(cls)
    except Exception:
        pass
    return [cls() for cls in classes]
