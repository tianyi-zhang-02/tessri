"""Language-neutral references found in non-code text: configs, scripts, CI files, markup, docs.

Frameworks wire code together by name: hydra `_target_: pkg.mod.Class`, registries,
console-script entry points, `python examples/run.py` in a shell script, `<script src>` in a
page. A pure import graph misses all of that, so these references are extracted separately
and resolved against the analyzers' module indexes. A mention in documentation is kept
apart from wiring: it lowers the confidence of a verdict without changing it.
"""

from __future__ import annotations

import configparser
import html
import posixpath
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# A dotted (or `pkg.mod:func`) name that is not the tail of a longer path.
DOTTED = re.compile(r"(?<![\w/.\-])[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)+")
DOTTED_FULL = re.compile(r"[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)+")
PYPATH = re.compile(r"[\w./\-]+\.py\b")
# A source file path in any supported language: `scripts/run.py`, `node scripts/build.mjs`, `/src/main.tsx`.
CODEPATH = re.compile(r"[\w./@\-]+\.(?:py|[cm]?[jt]sx?|vue|svelte|astro)\b")

# `config.yaml` looks like module `config` + attribute `yaml`; it is a file name.
_FILE_EXTS = frozenset(
    "py pyi yaml yml json toml cfg ini md rst mdx txt sh bash zsh js ts tsx jsx mjs cjs mts cts vue svelte astro html css csv jsonl log lock sql so whl gz zip tar png jpg svg pdf ipynb".split()
)


def is_filename(token: str) -> bool:
    """`config.yaml` or `setup.py` looks like module `config` + attribute `yaml`; it is a file name, not a dotted name."""
    return re.split(r"[.:]", token)[-1].lower() in _FILE_EXTS


# Configs that *enumerate* modules for a tool (type checker include lists, lint
# per-file ignores, coverage omit lists). Naming a module there is not evidence
# that anything uses it, so these files are not scanned at all.
TOOLING_CONFIGS = frozenset(
    {
        "pyrefly.toml", "mypy.ini", ".mypy.ini", "pyrightconfig.json", "ruff.toml", ".ruff.toml", ".flake8",
        ".pylintrc", "pylintrc", "tox.ini", ".coveragerc", "codecov.yml", ".codecov.yml", "codecov.yaml",
        ".importlinter", ".pyre_configuration", ".bandit", "bandit.yaml", ".isort.cfg",
    }
)  # fmt: skip

# The JSON files that do wire code together: scripts and entry points, extension manifests, build targets.
WIRING_JSON = frozenset({"package.json", "manifest.json", "angular.json", "project.json", "deno.json", "vercel.json", "firebase.json"})

# Output and documentation areas: a mention there is not a use.
WEAK_DIRS = frozenset({"docs", "doc", "reports", "report", "results", "logs", "outputs", "artifacts"})


def scan_mode(path: str, lang_name: str, kind: str) -> str | None:
    """How a non-code file's references count: "strong" (real wiring), "weak" (a mention) or None (ignore)."""
    name = posixpath.basename(path)
    if name in TOOLING_CONFIGS:
        return None
    if kind == "docs" or any(d in WEAK_DIRS for d in path.split("/")[:-1]):
        return "weak"
    if lang_name == "JSON" and name not in WIRING_JSON:
        return "weak"  # JSON is overwhelmingly data and generated output
    if kind == "config" or lang_name in ("Shell", "HTML"):  # <script src="/src/main.tsx"> is wiring; see scan_html
        return "strong"
    return None


@dataclass
class TextScan:
    dotted: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    weak: bool = False  # documentation: counts as a mention, not as a use


def scan_text(text: str, weak: bool = False) -> TextScan:
    scan = TextScan(weak=weak)
    for m in DOTTED.finditer(text):
        token = m.group()
        if not is_filename(token):
            scan.dotted.add(token)
    scan.paths.update(CODEPATH.findall(text))
    return scan


# Markup. A page wires in what it loads; what it says, and what it links to, is a mention.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HTML_BLOCK = re.compile(r"(<(script|style)\b[^>]*>)(.*?)</\2\s*>", re.S | re.I)  # inline code or style, with its open tag
_HTML_TAG = re.compile(r"<(/?)([A-Za-z][\w:-]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*)\s*/?>", re.S)
_HTML_ATTR = re.compile(r"([^\s=>/]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
LOADED = frozenset({"src", "srcset", "poster", "data"})  # attributes whose value the browser fetches; `href` only on <link>


def scan_html(text: str) -> tuple[TextScan, TextScan]:
    """A page as (wiring, mentions). Wiring is what the page loads (a `src`, a `<link href>`) and the code in its
    inline `<script>` blocks: `<script src="/src/main.tsx">` makes that file an entry point. Everything else is a
    mention: the page's text, a hyperlink (`<a href>`), any other attribute. A landing page or a committed docs
    page that names `pkg/core.py` in a sentence or links to it is documentation, like a README."""
    text = _HTML_COMMENT.sub(" ", text)
    loaded: list[str] = []
    said: list[str] = []

    def keep_tag(m: re.Match) -> str:
        if m.group(2).lower() == "script" and m.group(3).strip():
            loaded.append(m.group(3))
        return m.group(1)  # the open tag stays, so its `src` is read below

    text = _HTML_BLOCK.sub(keep_tag, text)
    for m in _HTML_TAG.finditer(text):
        tag = m.group(2).lower()
        for a in _HTML_ATTR.finditer(m.group(3)):
            name, value = a.group(1).lower(), a.group(2) or a.group(3) or a.group(4) or ""
            (loaded if name in LOADED or (name == "href" and tag == "link") else said).append(html.unescape(value))
    said.append(html.unescape(_HTML_TAG.sub(" ", text)))
    return scan_text("\n".join(loaded)), scan_text("\n".join(said), weak=True)


def scan_pyproject(text: str) -> TextScan:
    """Only entry-point tables count; lint/coverage config names modules without using them."""
    scan = TextScan()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return scan
    tables = [
        data.get("project", {}).get("scripts"),
        data.get("project", {}).get("gui-scripts"),
        data.get("tool", {}).get("poetry", {}).get("scripts"),
        *(data.get("project", {}).get("entry-points", {}) or {}).values(),
    ]
    for table in tables:
        if isinstance(table, dict):
            for value in table.values():
                if isinstance(value, str):
                    scan.dotted.add(value.split()[0])
    return scan


def scan_setup_cfg(text: str) -> TextScan:
    """Only `[options.entry_points]` counts; `[flake8]`/`[mypy]` sections list modules without using them."""
    scan = TextScan()
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except configparser.Error:
        return scan
    for section in parser.sections():
        if section.startswith("options.entry_points"):
            for _, value in parser.items(section):
                for line in value.splitlines():
                    _, _, target = line.partition("=")
                    if target.strip():
                        scan.dotted.add(target.split()[0])
    return scan


# Names Python gives to every package, not to a file in particular: a bare one in a string or a config names nothing.
UNNAMED = frozenset({"__init__.py", "__main__.py"})


class PathIndex:
    """Resolve a path-like token (`./examples/run.py`, `run.py`) to repository files.

    An exact path is itself. Otherwise the token is matched as a path suffix, because the directory a config file
    is read from is unknown, and a suffix that fits exactly one file names it. A suffix that fits several files
    names none of them: `utils.py` in a repository with ninety of them says nothing about any one of them, and
    treating it as all ninety made them all reachable and gave each a string edge. `ambiguous` records those
    tokens and how many files they fit, for a report to say what was not resolved. `allow_many` keeps the old
    behaviour for a caller that means every match, such as an `entry` the user wrote in the configuration."""

    def __init__(self, paths: Iterable[str]):
        self.paths = set(paths)
        self._by_name: dict[str, list[str]] = defaultdict(list)
        for p in self.paths:
            self._by_name[posixpath.basename(p)].append(p)
        self.ambiguous: dict[str, int] = {}

    def resolve(self, token: str, allow_many: bool = False) -> set[str]:
        while token.startswith(("./", "../", "/")):  # the config file's own directory is unknown, so match by suffix
            token = token[token.index("/") + 1 :]
        if token in self.paths:
            return {token}
        name = posixpath.basename(token)
        if name in UNNAMED and "/" not in token:
            return set()
        suffix = "/" + token
        hits = {p for p in self._by_name.get(name, ()) if p.endswith(suffix)}
        if len(hits) > 1 and not allow_many:
            self.ambiguous[token] = len(hits)
            return set()
        return hits
