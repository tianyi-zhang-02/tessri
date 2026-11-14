"""Build the Tessri site: the landing page from `site/index.html` and the guide from `docs/guide/*.md`.

Zero dependencies, like the tool. The landing page's example is lifted from the README so the two cannot drift; every
guide page is Markdown rendered by the small converter below (headings, paragraphs, fenced code, tables, lists,
links, code spans, bold and italic are all the guide uses). Links between guide pages become links between the
rendered pages; links out of the guide point at the repository on GitHub. With `--demo`, the package in this
checkout runs on the checkout itself: `demo/report.html` is the HTML report, and `demo/` the brief of the latest
commit against its first parent, which on `main` is the last merged pull request; the landing page then opens with
the first sections of that brief.

    python tools/build_site.py --out _site --demo
    python -m http.server --directory _site

The output directory is created, or reused when it holds the marker this script writes; anything else is refused.
"""

from __future__ import annotations

import argparse
import functools
import html
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
GUIDE = ROOT / "docs" / "guide"
REPO = "https://github.com/tianyi-zhang-02/tessri"
BLOB = f"{REPO}/blob/main/"
TREE = f"{REPO}/tree/main/"
MARKER = ".tessri-site"
ASSETS = ("tessri.css", "favicon.svg", "liquid.js")
FONTS = SITE / "fonts"  # the type, served next to its notices
ICONS = SITE / "icons"  # the icon set, inlined where a page uses one; its notice ships at icons/LICENSE
NOTICES = "<!-- Type: Inter and Commit Mono, SIL Open Font License, the notices in fonts/. Icons: Lucide, ISC licence, icons/LICENSE. -->"

# The guide's navigation: README.md (the guide index) gives the labels and the order; this gives the groups. A page
# the index names but no group claims lands under "More", so adding a page never hides it.
GROUPS = [
    ("Start", ["getting-started", "when"]),
    ("Questions", ["scan", "ownership", "review-load", "graph", "impact"]),
    ("Changes", ["triage", "check", "brief"]),
    ("Output", ["html-report", "json"]),
    ("Setup", ["integration", "hooks", "mcp", "configuration"]),
    ("Reference", ["architecture", "backtest", "limits", "formerly-repolife"]),
]

MARK = (
    '<svg viewBox="0 0 32 32" aria-hidden="true" fill="currentColor"><path d="M7 6h18v3H7zM15 7h3v20h-3z"/>'
    '<rect x="3" y="2" width="11" height="10" rx="3"/><rect x="19" y="2" width="11" height="10" rx="3"/>'
    '<rect x="12" y="15" width="9" height="7" rx="2"/><rect x="12" y="25" width="9" height="7" rx="2"/></svg>'
)

SCRIPTS = """<script>
(function () {
  var root = document.documentElement;
  var motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
  var button = document.querySelector(".theme");
  if (button) {
    button.addEventListener("click", function () {
      var chosen = root.getAttribute("data-theme");
      var dark = chosen === "dark" || (!chosen && matchMedia("(prefers-color-scheme: dark)").matches);
      var next = dark ? "light" : "dark";
      if (motion) { root.classList.add("switching"); setTimeout(function () { root.classList.remove("switching"); }, 300); }
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("tessri-theme", next); } catch (e) {}
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll(".copy"), function (b) {
    b.addEventListener("click", function () {
      if (!navigator.clipboard) { return; }
      navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () {
        var label = b.querySelector("span");
        var was = label ? label.textContent : "";
        b.classList.add("done");
        if (label) { label.textContent = "Copied"; }
        setTimeout(function () { b.classList.remove("done"); if (label) { label.textContent = was; } }, 1200);
      });
    });
  });
  var rail = document.querySelectorAll(".toc a");
  if (rail.length && "IntersectionObserver" in window) {
    var byId = {};
    Array.prototype.forEach.call(rail, function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var current = null;
    var follow = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) { return; }
        if (current) { current.removeAttribute("aria-current"); }
        current = byId[e.target.id];
        current.setAttribute("aria-current", "true");
      });
    }, { rootMargin: "0px 0px -70% 0px" });
    Object.keys(byId).forEach(function (id) { var h = document.getElementById(id); if (h) { follow.observe(h); } });
  }
  if (!motion || !("IntersectionObserver" in window)) { return; }
  var below = Array.prototype.filter.call(document.querySelectorAll("main .band"), function (s) { return s.getBoundingClientRect().top > innerHeight * 0.9; });
  var arrive = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); arrive.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -10% 0px" });
  below.forEach(function (s) { s.classList.add("reveal"); arrive.observe(s); });
  var cmd = document.querySelector(".example .cmdline b");
  var output = document.querySelector(".example .output");
  if (cmd && output) {
    var text = cmd.textContent;
    var caret = document.createElement("span");
    caret.className = "caret";
    cmd.textContent = "";
    cmd.parentNode.appendChild(caret);
    output.classList.add("pending");
    var seen = new IntersectionObserver(function (entries) {
      if (!entries[0].isIntersecting) { return; }
      seen.disconnect();
      var i = 0;
      var tick = setInterval(function () {
        cmd.textContent = text.slice(0, ++i);
        if (i >= text.length) {
          clearInterval(tick);
          setTimeout(function () { output.classList.remove("pending"); caret.remove(); }, 260);
        }
      }, 34);
    }, { threshold: 0.3 });
    seen.observe(cmd.parentNode);
  }
})();
</script>"""

THEME_BOOT = '<script>try{var t=localStorage.getItem("tessri-theme");if(t)document.documentElement.setAttribute("data-theme",t)}catch(e){}</script>'


class BuildError(Exception):
    pass


@functools.lru_cache(maxsize=None)
def icon(name: str, cls: str = "icon") -> str:
    """One icon of the set, inline: its own size dropped, hidden from readers, classed `icon icon-<name>`."""
    path = ICONS / f"{name}.svg"
    if not path.is_file():
        raise BuildError(f"no icon named {name} in site/icons/")
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    m = re.search(r"<svg\b([^>]*)>(.*)</svg>", text, re.S)
    if not m:
        raise BuildError(f"site/icons/{name}.svg is not an SVG icon")
    attrs = re.sub(r'\s+(?:class|width|height|xmlns)="[^"]*"', "", m.group(1))
    attrs = re.sub(r"\s+", " ", attrs).strip()
    body = re.sub(r">\s+<", "><", m.group(2).strip())
    return f'<svg class="{cls} icon-{name}" aria-hidden="true" {attrs}>{body}</svg>'


def theme_button() -> str:
    return (
        '<button class="theme" type="button" aria-label="Switch between dark and light">'
        f'{icon("sun", "icon sun")}{icon("moon", "icon moon")}</button>'
    )


def copy_button(text: str, label: str | None = "Copy") -> str:
    """A button that copies `text`; with no label, the small one that sits on a code block."""
    cls = "copy" if label else "copy mini"
    aria = "" if label else ' aria-label="Copy"'
    inner = icon("copy", "icon copy-icon") + icon("check", "icon check") + (f"<span>{html.escape(label)}</span>" if label else "")
    return f'<button class="{cls}" type="button" data-copy="{html.escape(text, quote=True)}"{aria}>{inner}</button>'


# --- Code, as the reader reads it ------------------------------------------------------------------------------------

_SHELL = {"bash", "sh", "shell", "zsh", "console"}
_PYTHON = {"python", "py"}
_DATA = {"toml", "yaml", "yml", "json", "ini"}
_PY_KEYWORDS = frozenset({
    "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
    "return", "try", "while", "with", "yield", "None", "True", "False",
})
_SH_TOKEN = re.compile(r"""(?P<c>(?<!\S)#[^\n]*)|(?P<s>"(?:[^"\\]|\\.)*"|'[^']*')|(?P<f>(?<!\S)--?[A-Za-z][\w-]*)|(?P<w>[^\s"'#]+)""")
_PY_TOKEN = re.compile(r"""(?P<c>#[^\n]*)|(?P<s>"{3}[\s\S]*?"{3}|'{3}[\s\S]*?'{3}|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(?P<d>@[\w.]+)|(?P<n>\b\d+(?:\.\d+)?\b)|(?P<w>[A-Za-z_]\w*)""")
_DATA_TOKEN = re.compile(r"""(?P<c>(?<!\S)#[^\n]*)|(?P<k>"(?:[^"\\]|\\.)*"(?=\s*:)|^[ \t]*(?:-[ \t]+)?[\w.-]+(?=[ \t]*[:=]))|(?P<s>"(?:[^"\\]|\\.)*"|'[^']*')|(?P<n>\b(?:\d+(?:\.\d+)?|true|false|null)\b)""", re.M)
_CLASS = {"c": "tk-c", "s": "tk-s", "f": "tk-f", "n": "tk-n", "k": "tk-k", "d": "tk-f"}


def _spans(code: str, pattern: re.Pattern, keywords: frozenset = frozenset()) -> str:
    out: list[str] = []
    at = 0
    for m in pattern.finditer(code):
        out.append(html.escape(code[at : m.start()], quote=False))
        kind, text = m.lastgroup, html.escape(m.group(), quote=False)
        if kind == "w":
            out.append(f'<span class="tk-k">{text}</span>' if m.group() in keywords else text)
        else:
            out.append(f'<span class="{_CLASS[kind]}">{text}</span>')
        at = m.end()
    out.append(html.escape(code[at:], quote=False))
    return "".join(out)


def _shell(code: str) -> str:
    """A prompt is quiet, the command is the keyword, then flags, strings and comments."""
    lines: list[str] = []
    for line in code.split("\n"):
        out: list[str] = []
        rest = line
        if rest.startswith("$ "):
            out.append('<span class="tk-p">$ </span>')
            rest = rest[2:]
        start = True
        at = 0
        for m in _SH_TOKEN.finditer(rest):
            out.append(html.escape(rest[at : m.start()], quote=False))
            kind, text = m.lastgroup, html.escape(m.group(), quote=False)
            if kind == "w":
                out.append(f'<span class="tk-k">{text}</span>' if start and m.group()[0].isalpha() else text)
                start = m.group() in {"|", "&&", "||", ";"}
            else:
                out.append(f'<span class="{_CLASS[kind]}">{text}</span>')
            at = m.end()
        out.append(html.escape(rest[at:], quote=False))
        lines.append("".join(out))
    return "\n".join(lines)


def highlight(code: str, lang: str) -> str:
    """The fenced block's HTML: escaped, and for shell, Python and data files, a span per comment, string, keyword, flag and number."""
    if lang in _SHELL:
        return _shell(code)
    if lang in _PYTHON:
        return _spans(code, _PY_TOKEN, _PY_KEYWORDS)
    if lang in _DATA:
        return _spans(code, _DATA_TOKEN)
    return html.escape(code, quote=False)


# --- Markdown ------------------------------------------------------------------------------------------------------

_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\s](?:[^*]*?[^*\s])?)\*(?![\w*])")
_HEADING = re.compile(r"(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"[-*]\s+(.*)")
_NUMBERED = re.compile(r"\d+\.\s+(.*)")


def rewrite_link(url: str) -> str:
    """A link as the guide writes it (relative to docs/guide) -> a link as the site needs it."""
    if re.match(r"[a-z][a-z0-9+.-]*:", url) or url.startswith("#"):
        return url
    path, _, fragment = url.partition("#")
    tail = f"#{fragment}" if fragment else ""
    if "/" not in path and path.endswith(".md"):
        name = "index.html" if path == "README.md" else path[:-3] + ".html"
        return name + tail
    inside = posixpath.normpath(posixpath.join("docs/guide", path))
    if inside.startswith("../"):
        raise BuildError(f"link leaves the repository: {url}")
    return (TREE if path.endswith("/") or "." not in posixpath.basename(inside) else BLOB) + inside + tail


def inline(text: str) -> str:
    """Code spans, links, bold and italic; everything else escaped."""
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE.sub(keep, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(rewrite_link(m.group(2)), quote=True)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub("\x00(\\d+)\x00", lambda m: spans[int(m.group(1))], text)


def plain(text: str) -> str:
    """Heading text without its markup, for titles and labels."""
    text = _CODE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    return _BOLD.sub(r"\1", text).replace("*", "").strip()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-")


def _table(rows: list[str]) -> str:
    def cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip().strip("|").split("|")]

    head = cells(rows[0])
    align = [c.endswith(":") for c in cells(rows[1])] if len(rows) > 1 and set(rows[1]) <= set("|-: ") else [False] * len(head)
    body = rows[2:] if len(rows) > 1 and set(rows[1]) <= set("|-: ") else rows[1:]
    def attr(i: int) -> str:
        return ' class="num"' if i < len(align) and align[i] else ""

    out = ['<div class="table"><table>', "<thead><tr>" + "".join(f"<th{attr(i)}>{inline(c)}</th>" for i, c in enumerate(head)) + "</tr></thead>"]
    if body:
        out.append("<tbody>")
        for row in body:
            out.append("<tr>" + "".join(f"<td{attr(i)}>{inline(c)}</td>" for i, c in enumerate(cells(row))) + "</tr>")
        out.append("</tbody>")
    out.append("</table></div>")
    return "\n".join(out)


def render_markdown(text: str) -> tuple[str, str]:
    """(title, body HTML) for one guide page. The title is the first level-one heading."""
    lines = text.splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    title = ""
    i = 0

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{inline(' '.join(s.strip() for s in paragraph))}</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            lang = line[3:].strip()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            attr = f' class="language-{html.escape(lang)}"' if lang else ""
            text = chr(10).join(code)
            out.append(f'<div class="code"><pre><code{attr}>{highlight(text, lang)}</code></pre>{copy_button(text, None)}</div>')
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        if re.fullmatch(r"-{3,}|\*{3,}", line.strip()):
            flush()
            out.append("<hr>")
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level, body = len(heading.group(1)), heading.group(2)
            if level == 1 and not title:
                title = plain(body)
            out.append(f'<h{level} id="{slug(body)}">{inline(body)}</h{level}>')
            i += 1
            continue
        if line.startswith("|"):
            flush()
            rows: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        bullet, numbered = _BULLET.match(line), _NUMBERED.match(line)
        if bullet or numbered:
            flush()
            tag, pattern = ("ul", _BULLET) if bullet else ("ol", _NUMBERED)
            items: list[str] = []
            while i < len(lines):
                m = pattern.match(lines[i])
                if m:
                    items.append(m.group(1))
                elif lines[i].startswith("  ") and items and lines[i].strip():
                    items[-1] += " " + lines[i].strip()  # a wrapped item
                else:
                    break
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
            continue
        paragraph.append(line)
        i += 1
    flush()
    return title, "\n".join(out)


# --- The reach of one file, drawn -------------------------------------------------------------------------------------

EXAMPLE_TARGET = re.compile(r"tessri impact (\S+)")
NOTES_IN_BRIEF = {"look-first": "ranked by history: commits in 90 days, fixes and reverts, and who went quiet"}


def reach(g, target: str) -> dict:
    """What depends on `target`, by distance: the code files that import it, the code one step further, the tests that
    reach it at any distance (nearest first), and the kind of evidence behind every edge drawn."""
    inbound = g.inbound
    direct = sorted(p for p in inbound.get(target, ()) if p not in g.tests)
    second = sorted({q for p in direct for q in inbound.get(p, ()) if q not in g.tests and q != target and q not in direct})
    kinds = {f"{p}>{target}": g.kind(p, target) for p in direct}
    kinds.update({f"{q}>{p}": g.kind(q, p) for p in direct for q in inbound.get(p, ()) if q in second})
    distance = {target: 0}
    queue = [target]
    tests: list[str] = []
    for p in queue:
        for q in sorted(inbound.get(p, ())):
            if q not in distance:
                distance[q] = distance[p] + 1
                queue.append(q)
                if q in g.tests:
                    tests.append(q)
    return {"target": target, "direct": direct, "second": second, "tests": tests, "kinds": kinds}


def _short(path: str, limit: int = 18) -> str:
    name = path.rsplit("/", 1)[-1]
    return name if len(name) <= limit else name[: limit - 1] + "…"


def drawing(r: dict, limit: int = 9) -> str:
    """The reach as a blueprint: the file, what imports it, what imports those, with each edge drawn in the kind of
    evidence behind it (dashed when no import statement makes it), and under it the tests that reach the file."""
    direct, second = r["direct"][:limit], r["second"][:limit]
    dmore, smore = len(r["direct"]) - len(direct), len(r["second"]) - len(second)
    rows = max(1, len(direct) + bool(dmore), len(second) + bool(smore))
    top, step, xs = 48, 24, (12, 170, 322)
    height = top + rows * step + 8

    def y(i: float) -> float:
        return top + i * step + 8

    def width(path: str) -> float:
        return 14 + len(_short(path)) * 6.9

    out = [f'<svg class="blueprint" viewBox="0 0 460 {height}" role="img" aria-label="The reach of {html.escape(r["target"])}: {len(r["direct"])} files import it, {len(r["second"])} more import those, {len(r["tests"])} tests reach it.">']
    for text, n, x in (("the file", None, xs[0]), ("imports it", len(r["direct"]), xs[1]), ("one step further", len(r["second"]), xs[2])):
        out.append(f'<text class="bp-head" x="{x}" y="16">{text}</text>')
        if n is not None:
            out.append(f'<text class="bp-count" x="{x}" y="32">{n} file{"s" if n != 1 else ""}</text>')
    ty = y((rows - 1) / 2)
    tx_end = xs[0] + width(r["target"])
    for i, p in enumerate(direct):
        kind = r["kinds"].get(f"{p}>{r['target']}", "unknown")
        out.append(f'<path class="bp-edge kind-{kind}" d="M{xs[1] - 6},{y(i)} C{xs[1] - 50},{y(i)} {tx_end + 40},{ty} {tx_end},{ty}"/>')
    for j, q in enumerate(second):
        for i, p in enumerate(direct):
            kind = r["kinds"].get(f"{q}>{p}")
            if kind:
                out.append(f'<path class="bp-edge kind-{kind}" d="M{xs[2] - 6},{y(j)} C{xs[2] - 50},{y(j)} {xs[1] + width(p) + 40},{y(i)} {xs[1] + width(p)},{y(i)}"/>')

    def node(x: float, yy: float, path: str, cls: str = "") -> str:
        return f'<g class="bp-file{cls}"><rect class="bp-node" x="{x}" y="{yy - 3.5}" width="7" height="7" rx="1.5"/><text class="bp-label" x="{x + 13}" y="{yy + 4}">{html.escape(_short(path))}</text></g>'

    out.append(node(xs[0], ty, r["target"], " bp-target"))
    for i, p in enumerate(direct):
        out.append(node(xs[1], y(i), p))
    if dmore:
        out.append(f'<text class="bp-more" x="{xs[1] + 13}" y="{y(len(direct)) + 4}">+{dmore} more</text>')
    for j, q in enumerate(second):
        out.append(node(xs[2], y(j), q))
    if smore:
        out.append(f'<text class="bp-more" x="{xs[2] + 13}" y="{y(len(second)) + 4}">+{smore} more</text>')
    out.append("</svg>")
    tests = r["tests"]
    if tests:
        named = ", ".join(f"<code>{html.escape(_short(t, 40))}</code>" for t in tests[:5])
        rest = f", and {len(tests) - 5} more" if len(tests) > 5 else ""
        line = f'<p class="tests"><b>{len(tests)} test file{"s" if len(tests) != 1 else ""} reach it</b>, candidates to run, not runs: {named}{rest}.</p>'
    else:
        line = '<p class="tests"><b>No test file reaches it</b> through the imports the analysis can see.</p>'
    return (
        f'<figure class="drawing">\n<figcaption>The reach of <code>{html.escape(r["target"])}</code>, drawn from this build\'s analysis: solid edges are import statements, dashed ones the names that are only a guess.</figcaption>\n'
        + "\n".join(out)
        + f"\n{line}\n</figure>"
    )


# --- Pages -----------------------------------------------------------------------------------------------------------


def guide_index() -> list[tuple[str, str]]:
    """(slug, label) for every page the guide index links, in its order."""
    text = (GUIDE / "README.md").read_text(encoding="utf-8")
    found = []
    for m in _LINK.finditer(text):
        label, url = m.group(1), m.group(2)
        if "/" not in url and url.endswith(".md") and url != "README.md":
            found.append((url[:-3], plain(label)))
    return found


def head(title: str, description: str, depth: int) -> str:
    up = "../" * depth
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f'<meta name="description" content="{html.escape(description, quote=True)}">\n'
        f'<link rel="icon" href="{up}favicon.svg" type="image/svg+xml">\n<link rel="stylesheet" href="{up}tessri.css">\n'
        f"{NOTICES}\n{THEME_BOOT}\n</head>\n"
    )


def top(depth: int, current: str | None, demo: bool = False) -> str:
    up = "../" * depth
    guide = ' aria-current="page"' if current == "guide" else ""
    here = ' aria-current="page"' if current == "demo" else ""
    demo_link = f'<a href="{up}demo/"{here}>Demo</a>' if demo else ""
    return (
        f'<div class="sky">\n<header class="wrap top">\n  <a class="wordmark" href="{up or "./"}" aria-label="Tessri home">{MARK}<span>tessri<span class="dot">.</span></span></a>\n'
        f'  <nav aria-label="Site"><a href="{up}guide/"{guide}>Guide</a>{demo_link}<a href="{REPO}">GitHub {icon("arrow-up-right")}</a>{theme_button()}</nav>\n</header>\n</div>\n'
    )


def foot(depth: int) -> str:
    up = "../" * depth
    return (
        f'<footer class="wrap foot">\n  <span class="brand">{MARK}<span>tessri<span class="dot">.</span></span></span>\n  <nav aria-label="Footer">'
        f'<a href="{up}guide/">Guide</a><a href="{up}guide/integration.html">Integration</a><a href="{up}guide/json.html">JSON</a>'
        f'<a href="{up}guide/limits.html">Limits</a><a href="{BLOB}CHANGELOG.md">Changelog</a><a href="{REPO}">GitHub</a></nav>\n'
        f'  <span>MIT. <a href="{up}guide/formerly-repolife.html">Formerly repolife</a>, until 0.2.x.</span>\n</footer>\n'
    )


def nav(pages: list[tuple[str, str]], current: str) -> str:
    labels = dict(pages)
    placed: set[str] = set()
    groups: list[tuple[str, list[str]]] = []
    for name, slugs in GROUPS:
        members = [s for s in slugs if s in labels]
        placed.update(members)
        if members:
            groups.append((name, members))
    rest = [s for s, _ in pages if s not in placed]
    if rest:
        groups.append(("More", rest))

    def link(s: str, label: str) -> str:
        mark = ' aria-current="page"' if s == current else ""
        return f'<li><a href="{s}.html"{mark}>{html.escape(label)}</a></li>'

    out = ['<aside class="guide-nav"><details open><summary>Guide pages</summary>']
    out.append('<p class="group">Guide</p><ul>' + ('<li><a href="./" aria-current="page">Overview</a></li>' if current == "index" else '<li><a href="./">Overview</a></li>') + "</ul>")
    for name, members in groups:
        out.append(f'<p class="group">{html.escape(name)}</p><ul>' + "".join(link(s, labels[s]) for s in members) + "</ul>")
    out.append('</details><script>if(matchMedia("(max-width: 880px)").matches){document.currentScript.previousElementSibling.removeAttribute("open")}</script></aside>')
    return "\n".join(out)


def rail(body: str) -> str:
    """The page's own sections, for the rail beside the prose: its level-two headings, when there are at least two."""
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    if len(heads) < 2:
        return ""
    items = "".join(f'<li><a href="#{i}">{re.sub(r"<[^>]+>", "", text)}</a></li>' for i, text in heads)
    return f'<nav class="toc" aria-label="On this page"><p class="group">On this page</p><ul>{items}</ul></nav>\n'


def guide_page(name: str, title: str, body: str, pages: list[tuple[str, str]], demo: bool = False) -> str:
    description = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body.split("<p>", 1)[1].split("</p>", 1)[0])) if "<p>" in body else title
    source = f"docs/guide/{name}.md"
    article = (
        f'<article class="prose">\n{body}\n<p class="source">Source: <a href="{BLOB}{source}">{source}</a>. The guide is Markdown in the repository; this page is built from it.</p>\n</article>'
    )
    return (
        head(f"{title} · Tessri guide", description[:300], 1)
        + "<body>\n"
        + top(1, "guide", demo)
        + f'<div class="wrap guide">\n{nav(pages, name if name != "README" else "index")}\n{article}\n{rail(body)}</div>\n'
        + foot(1)
        + SCRIPTS
        + "\n</body>\n</html>\n"
    )


def readme_example() -> str:
    """The fenced block under "A complete example" in the README, as it is."""
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## A complete example")
        fence = next(i for i in range(start, len(lines)) if lines[i].startswith("```"))
    except StopIteration as exc:
        raise BuildError("README.md has no fenced example under '## A complete example'") from exc
    end = next(i for i in range(fence + 1, len(lines)) if lines[i].startswith("```"))
    return "\n".join(lines[fence + 1 : end])


def cmdline(command: str) -> str:
    """The panel's title bar: the window's dots, then the command as typed."""
    return f'<div class="cmdline"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span><span>$ <b>{html.escape(command)}</b></span></div>'


def example_panel() -> str:
    """The README's example as a reader sees it: the command line, then the Markdown output rendered."""
    first, _, rest = readme_example().partition("\n")
    if not first.startswith("$ "):
        raise BuildError("the README example should start with the command that produced it")
    _, body = render_markdown(rest)
    return f'{cmdline(first[2:])}\n<div class="output prose">\n{body}\n</div>'


def landing(demo: dict | None) -> str:
    template = (SITE / "index.html").read_text(encoding="utf-8")
    example = example_panel()
    filled = (
        template.replace("{{mark}}", MARK)
        .replace("{{repo}}", REPO)
        .replace("{{notices}}", NOTICES)
        .replace("{{theme_button}}", theme_button())
        .replace("{{demo_link}}", '<a href="demo/">Demo</a>' if demo else "")
        .replace("{{demo_head}}", demo_head(demo) if demo else "")
        .replace("{{demo}}", demo_section(demo) if demo else "")
        .replace("{{example}}", example)
        .replace("{{drawing}}", drawing(demo["reach"]) if demo else "")
        .replace("{{drawing_class}}", " with-drawing" if demo else "")
        .replace("{{foot}}", foot(0))
        .replace("{{scripts}}", SCRIPTS)
    )
    filled = re.sub(r"{{icon:([\w-]+)}}", lambda m: icon(m.group(1)), filled)
    filled = re.sub(r"{{copy:([^}]+)}}", lambda m: copy_button(m.group(1)), filled)
    left = re.findall(r"{{[\w:-]+}}", filled)
    if left:
        raise BuildError(f"unfilled placeholders in site/index.html: {', '.join(sorted(set(left)))}")
    return filled


# --- The demo: Tessri on this checkout --------------------------------------------------------------------------


def _git(*args: str) -> str:
    """Standard output of a git command run in this checkout, stripped; empty when git fails."""
    try:
        res = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def latest_change() -> dict:
    """The commit this checkout is at, in the words the demo uses: the pull request it merged (number and title, from
    the merge commit GitHub writes) or, for any other commit, its subject."""
    lines = _git("log", "-1", "--format=%H%n%s%n%b").splitlines()
    if len(lines) < 2:
        raise BuildError("the demo needs a git checkout with a commit")
    sha, subject, body = lines[0], lines[1], [line for line in lines[2:] if line.strip()]
    merged = re.match(r"Merge pull request #(\d+)", subject)
    if merged:
        return {"sha": sha, "pr": int(merged.group(1)), "title": body[0] if body else subject}
    return {"sha": sha, "pr": None, "title": subject}


def demo_content() -> dict:
    """Tessri on this checkout, from the package in it: the HTML report, the brief of the latest commit against its
    first parent (`base`), and what that commit is. Nothing of the site has been written when this runs, so the brief
    cannot see the site's own output as a change."""
    base = _git("rev-parse", "--short=9", "HEAD^1")
    if not base:
        raise BuildError("the demo needs a commit with a parent in a full checkout (not a shallow one)")
    sys.path.insert(0, str(ROOT))
    from tessri import brief, config, htmlreport  # noqa: E402  (the package in this checkout)
    from tessri.analyze import analyze  # noqa: E402
    from tessri.report import build_report  # noqa: E402

    cfg = config.load(ROOT)
    analysis = analyze(ROOT, cfg)
    try:
        page = brief.markdown(brief.compute(ROOT, cfg, base))
    except brief.BriefError as exc:
        raise BuildError(f"the demo brief: {exc}") from exc
    found = EXAMPLE_TARGET.search(readme_example().partition("\n")[0])
    if not found:
        raise BuildError("the README example should be a `tessri impact <path>` command, for the drawing beside it")
    return {"report": htmlreport.build_html(analysis, build_report(analysis)), "brief": page, "change": latest_change(), "base": base, "reach": reach(analysis.graph, found.group(1))}


def _annotate(body: str) -> str:
    """A sketch note under the headings of the brief that the landing page explains: the heading stays as it is."""
    for slug_, note in NOTES_IN_BRIEF.items():
        body = re.sub(rf'(<h3 id="{slug_}">[^<]*</h3>)', rf'\1\n<p class="annot">{html.escape(note)}</p>', body, count=1)
    return body


def _demote(body: str) -> str:
    """Every heading one level down, so a rendered page sits under the page's own heading."""
    return re.sub(r"<(/?)h([1-5])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", body)


def _what(change: dict) -> str:
    title = html.escape(change["title"])
    if change["pr"]:
        return f'pull request <a href="{REPO}/pull/{change["pr"]}">#{change["pr"]}</a>, \u201c{title}\u201d, merged as <code>{change["sha"][:9]}</code>'
    return f'the commit \u201c{title}\u201d (<code>{change["sha"][:9]}</code>)'


def demo_head(demo: dict) -> str:
    """The band's tail on the landing page: the demo's heading, in the band's ink, above the panel that straddles the edge."""
    return (
        '<div class="wrap demo-head">\n  <span class="label">See it on this repository</span>\n'
        '  <h2>A change is done. This is the page the person it goes to gets.</h2>\n</div>\n'
    )


def demo_section(demo: dict) -> str:
    """The landing page's first section: the brief's first sections (scope, commits, look first) as the glass panel, then its caption."""
    page = demo["brief"]
    cut = page.find("\n## What it did to the structure")
    excerpt = page[:cut] if cut != -1 else page
    if excerpt.startswith("# "):
        excerpt = excerpt.split("\n", 1)[1]  # the panel has a command line instead of the page's title
    _, body = render_markdown(excerpt)
    return (
        '  <section class="band" id="demo">\n'
        '    <div class="example">\n      <div class="panel glass">\n'
        f'{cmdline("tessri brief --since " + demo["base"])}\n<div class="output prose">\n{_annotate(_demote(body))}\n</div>\n'
        '      </div>\n'
        f'      <p class="after">The latest change on Tessri\'s own <code>main</code> is {_what(demo["change"])}. Its brief, as of this build: the first sections above, '
        '<a href="demo/">the whole page</a> with the findings, the candidate tests and what needs a person, and <a href="demo/report.html">the HTML report</a> of the repository, with the module graph and the impact explorer.</p>\n'
        '    </div>\n  </section>\n'
    )


def demo_page(demo: dict) -> str:
    """`demo/index.html`: the whole brief, under a heading that says what it is."""
    _, body = render_markdown(demo["brief"])
    base = html.escape(demo["base"])
    intro = (
        '<h1 id="tessri-on-itself">Tessri on itself</h1>\n'
        f'<p>The latest change on this repository\'s <code>main</code> is {_what(demo["change"])}. Below is the page <code>tessri brief --since {base}</code> hands a person for it: '
        f'the change compared with <code>main</code> as it was before it (<code>{base}</code>), built when the site was deployed, and every push to <code>main</code> rebuilds it. '
        '<a href="report.html">The HTML report of the repository</a>, with the module graph and the impact explorer, is what <code>tessri scan . --format html</code> writes, built the same way.</p>\n'
    )
    article = (
        f'<article class="prose">\n{intro}{_demote(body)}\n'
        f'<p class="source">Built from this checkout by <a href="{BLOB}tools/build_site.py">tools/build_site.py</a> with <code>--demo</code>; the <a href="../guide/brief.html">brief guide</a> explains every section, and the <a href="../guide/html-report.html">report guide</a> the explorer.</p>\n</article>'
    )
    return (
        head("Tessri on itself · demo", "The brief of the latest change on Tessri's own repository, and the HTML report of the repository, rebuilt on every push.", 1)
        + "<body>\n"
        + top(1, "demo", True)
        + f'<div class="wrap demo-page">\n{article}\n</div>\n'
        + foot(1)
        + SCRIPTS
        + "\n</body>\n</html>\n"
    )


def build(out: Path, demo: bool = False) -> list[Path]:
    """Write the site into `out` and return the files written. With `demo`, the pages that run Tessri on this checkout."""
    content = demo_content() if demo else None  # before anything is written
    out = out.resolve()
    if out.exists():
        if out.is_file() or (any(out.iterdir()) and not (out / MARKER).exists()):
            raise BuildError(f"{out} is not empty and was not built by this script; choose another directory")
        shutil.rmtree(out)
    (out / "guide").mkdir(parents=True)
    written: list[Path] = []

    def write(rel: str, text: str) -> None:
        target = out / rel
        target.write_text(text, encoding="utf-8")
        written.append(target)

    for asset in ASSETS:
        shutil.copyfile(SITE / asset, out / asset)
        written.append(out / asset)
    shutil.copytree(FONTS, out / "fonts")
    written.extend(sorted(p for p in (out / "fonts").iterdir() if p.is_file()))
    (out / "icons").mkdir()
    shutil.copyfile(ICONS / "LICENSE", out / "icons" / "LICENSE")
    written.append(out / "icons" / "LICENSE")
    write("index.html", landing(content))
    pages = guide_index()
    known = {s for s, _ in pages}
    for md in sorted(GUIDE.glob("*.md")):
        name = md.stem
        if name != "README" and name not in known:
            raise BuildError(f"docs/guide/{md.name} is not linked from docs/guide/README.md, so the guide index would not show it")
        title, body = render_markdown(md.read_text(encoding="utf-8"))
        if not title:
            raise BuildError(f"docs/guide/{md.name} has no level-one heading")
        write(f"guide/{'index' if name == 'README' else name}.html", guide_page(name, title, body, pages, demo))
    if content:
        (out / "demo").mkdir()
        write("demo/report.html", content["report"])
        write("demo/index.html", demo_page(content))
    write(".nojekyll", "")
    write(MARKER, "built by tools/build_site.py\n")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Tessri site from site/ and docs/guide/.")
    parser.add_argument("--out", default="_site", help="output directory (default: _site)")
    parser.add_argument("--demo", action="store_true", help="also run Tessri on this checkout: demo/report.html and the brief of the latest commit at demo/")
    args = parser.parse_args(argv)
    try:
        written = build(Path(args.out), demo=args.demo)
    except BuildError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 2
    print(f"{len(written)} files written to {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
