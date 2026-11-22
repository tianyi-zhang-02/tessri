"""Build the Tessri site: the landing page from `site/index.html` and the guide from `docs/guide/*.md`.

Zero dependencies, like the tool. The landing page's example is lifted from the README so the two cannot drift; every
guide page is Markdown rendered by the small converter below (headings, paragraphs, fenced code, tables, lists,
links, code spans, bold and italic are all the guide uses). Links between guide pages become links between the
rendered pages; links out of the guide point at the repository on GitHub. With `--demo`, the package in this
checkout runs on the checkout itself: `demo/report.html` is the HTML report, and `demo/` the brief of the latest
commit against its first parent, which on `main` is the last merged pull request. That brief sits below the
task and evidence sections; the hero always starts with the reproducible teaching review at `example/`.

    python tools/build_site.py --out _site --demo
    python -m http.server --directory _site

The output directory is created, or reused when it holds the marker this script writes; anything else is refused.
"""

from __future__ import annotations

import argparse
import functools
import html
import json
import posixpath
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figures  # noqa: E402  (tools/figures.py: the drawings, one source for the site, the guide and the README)
import review_example  # noqa: E402  (one isolated, reproducible teaching fixture)

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
GUIDE = ROOT / "docs" / "guide"
FIGURES = GUIDE / "figures"  # the standalone SVG files, for Markdown viewers; the site inlines the same drawings
BLOG = ROOT / "docs" / "blog"  # posts as `YYYY-MM-DD-slug.md` (or `YYYY-MM-DD-NN-slug.md` to order a day's posts): a level-one heading, a first paragraph that is the summary, figures as image lines
REPO = "https://github.com/tianyi-zhang-02/tessri"
SITE_URL = "https://tianyi-zhang-02.github.io/tessri/"  # where the site is served; link previews and the sitemap need absolute addresses
DEFAULT_BRANCH = "main"  # the branch the deployed site builds from; any other checkout is a preview and says so
BLOB = f"{REPO}/blob/main/"
TREE = f"{REPO}/tree/main/"
MARKER = ".tessri-site"
ASSETS = ("tessri.css", "favicon.svg", "og.png")  # og.png is the card a link to the site shows elsewhere
FONTS = SITE / "fonts"  # the type, served next to its notices
ICONS = SITE / "icons"  # the icon set, inlined where a page uses one; its notice ships at icons/LICENSE
NOTICES = "<!-- Type: Inter, Newsreader and Commit Mono, SIL Open Font License, the notices in fonts/. Icons: Lucide, ISC licence, icons/LICENSE. -->"

# The guide's navigation: README.md (the guide index) gives the labels and the order; this gives the groups. A page
# the index names but no group claims lands under "More", so adding a page never hides it.
GROUPS = [
    ("Start", ["getting-started", "when"]),
    ("Questions", ["scan", "ownership", "review-load", "graph", "impact"]),
    ("Changes", ["triage", "check", "brief"]),
    ("Output", ["html-report", "json"]),
    ("Setup", ["integration", "hooks", "mcp", "configuration"]),
    ("Reference", ["architecture", "backtest", "reviewer-match", "limits", "formerly-repolife"]),
]

MARK = (
    '<svg viewBox="0 0 32 32" aria-hidden="true" fill="currentColor"><path d="M7 6h18v3H7zM15 7h3v20h-3z"/>'
    '<rect x="3" y="2" width="11" height="10" rx="3"/><rect x="19" y="2" width="11" height="10" rx="3"/>'
    '<rect x="12" y="15" width="9" height="7" rx="2"/><rect x="12" y="25" width="9" height="7" rx="2"/></svg>'
)

SCRIPTS = r"""<script>
(function () {
  var root = document.documentElement;
  var motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
  var looks = Array.prototype.slice.call(document.querySelectorAll(".look select"));  // the top bar's and the footer's, kept in step
  looks.forEach(function (look) {
    look.value = root.getAttribute("data-look") || "editorial";
    look.addEventListener("change", function () {
      if (motion) { root.classList.add("switching"); setTimeout(function () { root.classList.remove("switching"); }, 300); }
      root.setAttribute("data-look", look.value);
      looks.forEach(function (other) { other.value = look.value; });
      try { localStorage.setItem("tessri-look", look.value); } catch (e) {}
    });
  });
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
  var opener = document.querySelector(".search-open");
  var dialog = document.querySelector(".search");
  if (opener && dialog) {
    var input = dialog.querySelector("input");
    var list = dialog.querySelector('[role="listbox"]');
    var hint = dialog.querySelector(".hint");
    var base = dialog.getAttribute("data-base");
    var index = null, loading = null, rows = [], active = -1, lastFocus = null;
    function load() {
      if (index) { return Promise.resolve(index); }
      if (!loading) {
        loading = fetch(base + "search.json").then(function (r) { return r.json(); }).then(function (data) { index = data; return data; });
      }
      return loading;
    }
    function open() {
      lastFocus = document.activeElement;
      dialog.hidden = false;
      document.body.classList.add("searching");
      input.focus();
      load().then(function () { show(input.value); }, function () { hint.textContent = "The index did not load"; });
    }
    function close() {
      dialog.hidden = true;
      document.body.classList.remove("searching");
      if (lastFocus && lastFocus.focus) { lastFocus.focus(); }
    }
    function escapeHtml(s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function pattern(ws) { return new RegExp("(" + ws.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")", "i"); }
    function marked(text, ws) {
      return text.split(pattern(ws)).map(function (piece, i) { return i % 2 ? "<mark>" + escapeHtml(piece) + "</mark>" : escapeHtml(piece); }).join("");
    }
    function snippet(body, ws) {
      var low = body.toLowerCase(), at = -1;
      for (var i = 0; i < ws.length && at < 0; i++) { at = low.indexOf(ws[i]); }
      var start = at < 0 ? 0 : Math.max(0, at - 60);
      var piece = body.slice(start, start + 170);
      return (start > 0 ? "… " : "") + marked(piece, ws) + (start + 170 < body.length ? " …" : "");
    }
    function score(e, ws) {
      var t = e.t.toLowerCase(), h = e.h.toLowerCase(), b = e.b.toLowerCase(), s = 0;
      for (var i = 0; i < ws.length; i++) {
        var w = ws[i];
        if (t.indexOf(w) >= 0) { s += 4; } else if (h.indexOf(w) >= 0) { s += 3; } else if (b.indexOf(w) >= 0) { s += 1; } else { return 0; }
      }
      return s + (e.h ? 0 : 0.5);
    }
    function mark() {
      var items = list.children;
      for (var i = 0; i < items.length; i++) { items[i].setAttribute("aria-selected", i === active ? "true" : "false"); }
      if (active >= 0) { input.setAttribute("aria-activedescendant", "search-" + active); items[active].scrollIntoView({ block: "nearest" }); }
      else { input.removeAttribute("aria-activedescendant"); }
    }
    function show(q) {
      var ws = q.toLowerCase().split(/\s+/).filter(Boolean);
      rows = [];
      active = -1;
      if (!index || !ws.length) { list.innerHTML = ""; hint.textContent = "Type to search the guide"; mark(); return; }
      var found = index.map(function (e) { return { e: e, s: score(e, ws) }; }).filter(function (x) { return x.s > 0; });
      found.sort(function (a, b) { return b.s - a.s || a.e.t.length - b.e.t.length; });
      rows = found.slice(0, 8).map(function (x) { return x.e; });
      list.innerHTML = "";
      rows.forEach(function (e, i) {
        var item = document.createElement("li");
        item.setAttribute("role", "option");
        item.id = "search-" + i;
        item.setAttribute("aria-selected", "false");
        var link = document.createElement("a");
        link.href = base + e.u;
        var where = document.createElement("span");
        where.className = "where";
        where.innerHTML = e.h ? escapeHtml(e.t) + ' <span class="sep">›</span> ' + marked(e.h, ws) : marked(e.t, ws);
        var snip = document.createElement("span");
        snip.className = "snip";
        snip.innerHTML = snippet(e.b, ws);
        link.appendChild(where);
        link.appendChild(snip);
        item.appendChild(link);
        list.appendChild(item);
      });
      hint.textContent = rows.length ? (found.length > rows.length ? rows.length + " of " + found.length + " places; keep typing" : rows.length + (rows.length === 1 ? " place" : " places")) : "Nothing in the guide says that";
      mark();
    }
    opener.addEventListener("click", open);
    dialog.querySelector(".search-backdrop").addEventListener("click", close);
    dialog.querySelector(".search-close").addEventListener("click", close);
    input.addEventListener("input", function () { show(input.value); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); if (rows.length) { active = (active + 1) % rows.length; mark(); } }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (rows.length) { active = (active - 1 + rows.length) % rows.length; mark(); } }
      else if (e.key === "Enter") { var pick = list.children[active >= 0 ? active : 0]; if (pick) { e.preventDefault(); location.href = pick.querySelector("a").href; } }
    });
    list.addEventListener("mousemove", function (e) {
      var item = e.target.closest("li");
      if (item) { var i = Array.prototype.indexOf.call(list.children, item); if (i !== active) { active = i; mark(); } }
    });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (dialog.hidden) { open(); } else { close(); } return; }
      if (e.key === "Escape" && !dialog.hidden) { e.preventDefault(); close(); return; }
      var tag = document.activeElement ? document.activeElement.tagName : "";
      if (e.key === "/" && dialog.hidden && tag !== "INPUT" && tag !== "TEXTAREA" && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); open(); }
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll('[role="tablist"]'), function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var panels = tabs.map(function (t) { return document.getElementById(t.getAttribute("aria-controls")); });
    var box = list.closest(".handoff");
    if (box) { box.classList.add("js"); }
    function select(i, focus) {
      tabs.forEach(function (t, j) {
        var on = j === i;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        if (panels[j]) { panels[j].hidden = !on; }
      });
      if (focus) { tabs[i].focus(); }
    }
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { select(i, false); });
      t.addEventListener("keydown", function (e) {
        var n = tabs.length, j;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") { j = (i + 1) % n; }
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { j = (i - 1 + n) % n; }
        else if (e.key === "Home") { j = 0; }
        else if (e.key === "End") { j = n - 1; }
        else { return; }
        e.preventDefault();
        select(j, true);
      });
    });
    var asked = location.hash && panels.indexOf(document.getElementById(location.hash.slice(1)));
    select(asked > 0 ? asked : 0, false);
    var jump = document.querySelector(".jump");
    if (jump && box) {
      jump.addEventListener("click", function () {
        setTimeout(function () {
          var on = list.querySelector('[role="tab"][aria-selected="true"]');
          if (on) { on.focus({ preventScroll: true }); }
        }, 0);
      });
    }
  });
  if (!motion || !("IntersectionObserver" in window)) { return; }
  var below = Array.prototype.filter.call(document.querySelectorAll("main .band"), function (s) { return s.getBoundingClientRect().top > innerHeight * 0.9; });
  var arrive = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); arrive.unobserve(e.target); } });
  }, { rootMargin: "0px 0px -10% 0px" });
  below.forEach(function (s) { s.classList.add("reveal"); arrive.observe(s); });
  var cmd = document.querySelector(".handoff .cmdline b");
  var output = document.querySelector(".handoff .body");
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

LOOKS = (("editorial", "Editorial"), ("panel", "Panel"), ("swiss", "Swiss"))  # the visitor's pick; the first is the default
THEME_BOOT = (
    '<script>(function(r){try{var t=localStorage.getItem("tessri-theme");if(t)r.setAttribute("data-theme",t);'
    'var l=localStorage.getItem("tessri-look");r.setAttribute("data-look",l==="panel"||l==="swiss"?l:"editorial")}'
    'catch(e){r.setAttribute("data-look","editorial")}})(document.documentElement)</script>'
)


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


def look_control() -> str:
    options = "".join(f'<option value="{value}">{label}</option>' for value, label in LOOKS)
    return f'<label class="look"><select aria-label="Look of the site">{options}</select></label>'


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
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")  # an image on a line of its own
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


def figure(alt: str, src: str) -> str:
    """An image line of a guide page. One of the generated figures (`figures/<name>.svg`) is inlined, so it follows the
    page's theme and its toggle, with the alt text as its caption; any other image is an image."""
    name = src.removeprefix("figures/").removesuffix(".svg")
    if src.startswith("figures/") and src.endswith(".svg") and name in figures.FIGURES:
        kind = " chart" if figures.FIGURES[name].kind == "chart" else ""
        return f'<figure class="fig{kind}"><div class="art">{figures.inline(name)}</div><figcaption>{inline(alt)}</figcaption></figure>'
    return f'<p><img src="{html.escape(rewrite_link(src), quote=True)}" alt="{html.escape(plain(alt), quote=True)}"></p>'


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
        image = _IMAGE.fullmatch(line.strip())
        if image:
            flush()
            out.append(figure(image.group(1), image.group(2)))
            i += 1
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
        line = f'<p class="tests"><span class="tag guess">Candidates</span><b>{len(tests)} test file{"s" if len(tests) != 1 else ""} reach it</b>, paths to run, not runs: {named}{rest}.</p>'
    else:
        line = '<p class="tests"><b>No test file reaches it</b> through the imports the analysis can see.</p>'
    return (
        f'<figure class="drawing">\n<figcaption>The reach of <code>{html.escape(r["target"])}</code>, drawn from this build\'s analysis, each edge in the kind of evidence behind it.</figcaption>\n'
        '<p class="key"><span class="k-import">an import statement</span><span class="k-guess">a name in a string, a config or a dynamic import: a guess</span></p>\n'
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


def social(title: str, description: str, path: str) -> str:
    """The page's address and what a link to it shows elsewhere: the canonical address, the Open Graph card, the
    summary card. `path` is the page's place under SITE_URL ("" for the landing page, "guide/" for the guide's index)."""
    where = html.escape(SITE_URL + path, quote=True)
    text = html.escape(description, quote=True)
    return (
        f'<link rel="canonical" href="{where}">\n'
        f'<meta property="og:type" content="website">\n<meta property="og:site_name" content="Tessri">\n'
        f'<meta property="og:title" content="{html.escape(title, quote=True)}">\n<meta property="og:description" content="{text}">\n'
        f'<meta property="og:url" content="{where}">\n<meta property="og:image" content="{SITE_URL}og.png">\n'
        '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
        '<meta property="og:image:alt" content="tessri. Keep code understandable.">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
    )


def skip() -> str:
    """The first thing on every page: a link a keyboard reader uses to pass the top bar."""
    return '<a class="skip" href="#main">Skip to content</a>\n'


def head(title: str, description: str, depth: int, path: str = "", base: bool = False) -> str:
    """`base` pins every relative address to SITE_URL: the not-found page is served at whatever address was asked for."""
    up = "../" * depth
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + (f'<base href="{SITE_URL}">\n' if base else "")
        + f"<title>{html.escape(title)}</title>\n"
        f'<meta name="description" content="{html.escape(description, quote=True)}">\n'
        + social(title, description, path)
        + f'<link rel="icon" href="{up}favicon.svg" type="image/svg+xml">\n<link rel="stylesheet" href="{up}tessri.css">\n'
        f"{NOTICES}\n{THEME_BOOT}\n</head>\n"
    )


def top(depth: int, current: str | None, demo: bool = False) -> str:
    up = "../" * depth
    def mark(name: str) -> str:
        return ' aria-current="page"' if current == name else ""

    demo_link = f'<a href="{up}demo/"{mark("demo")}>Demo</a>' if demo else ""
    return (
        f'<div class="sky">\n<header class="wrap top">\n  <a class="wordmark" href="{up or "./"}" aria-label="Tessri home">{MARK}<span>tessri<span class="dot">.</span></span></a>\n'
        f'  <nav aria-label="Site"><a href="{up}guide/"{mark("guide")}>Guide</a><a href="{up}blog/"{mark("blog")}>Blog</a>{demo_link}<a class="repo" href="{REPO}">GitHub {icon("arrow-up-right")}</a>{search_button()}{look_control()}{theme_button()}</nav>\n</header>\n</div>\n'
    )


def search_button() -> str:
    return f'<button class="search-open" type="button" aria-label="Search the guide">{icon("search")}<kbd aria-hidden="true">/</kbd></button>'


def search_dialog(depth: int) -> str:
    """The search over the guide, closed until asked for: the index is fetched on the first opening. Outside the band,
    which isolates and clips what it holds, so that the dialog can sit over the whole page."""
    up = "../" * depth
    return (
        f'<div class="search" role="dialog" aria-modal="true" aria-label="Search the guide" hidden data-base="{up}">\n'
        '  <div class="search-backdrop"></div>\n  <div class="search-panel">\n'
        f'    <div class="search-row">{icon("search")}<input type="search" role="combobox" aria-expanded="true" aria-controls="search-results" aria-autocomplete="list" aria-label="Search the guide" placeholder="Search the guide" autocomplete="off" spellcheck="false">'
        '<button class="search-close" type="button" aria-label="Close">Esc</button></div>\n'
        '    <ul id="search-results" role="listbox" aria-label="Places in the guide"></ul>\n'
        '    <p class="hint" aria-live="polite">Type to search the guide</p>\n  </div>\n</div>\n'
    )


def foot(depth: int, board: bool = False) -> str:
    up = "../" * depth
    demo_links = f'<a href="{up}demo/">Demo</a><a href="{up}board/">Board</a>' if board else ""
    return (
        f'<footer class="wrap foot">\n  <span class="brand">{MARK}<span>tessri<span class="dot">.</span></span></span>\n  <nav aria-label="Footer">'
        f'<a href="{up}guide/">Guide</a><a href="{up}blog/">Blog</a>{demo_links}<a href="{up}guide/integration.html">Integration</a><a href="{up}guide/json.html">JSON</a>'
        f'<a href="{up}guide/limits.html">Limits</a><a href="{BLOB}CHANGELOG.md">Changelog</a><a href="{REPO}">GitHub</a></nav>\n'
        f'  <span class="foot-end">{look_control()}<span>MIT. <a href="{up}guide/formerly-repolife.html">Formerly repolife</a>, until 0.2.x.</span></span>\n</footer>\n'
        + search_dialog(depth)
    )


def grouped(pages: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """The guide's pages by group, in the order the navigation shows them; pages no group names come last."""
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
    return groups


def order(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(slug, label) of every guide page in reading order: the overview, then the groups."""
    labels = dict(pages)
    return [("index", "Overview")] + [(s, labels[s]) for _, members in grouped(pages) for s in members]


def pager(pages: list[tuple[str, str]], current: str) -> str:
    """The page before and the page after, in reading order."""
    ordered = order(pages)
    at = next((i for i, (s, _) in enumerate(ordered) if s == current), None)
    if at is None:
        return ""

    def link(i: int, rel: str, word: str) -> str:
        s, label = ordered[i]
        return f'<a class="{rel}" rel="{rel}" href="{"./" if s == "index" else s + ".html"}"><span>{word}</span>{html.escape(label)}</a>'

    before = link(at - 1, "prev", "Previous") if at > 0 else ""
    after = link(at + 1, "next", "Next") if at + 1 < len(ordered) else ""
    return f'<nav class="pager" aria-label="Guide pages, in order">{before}{after}</nav>\n'


def nav(pages: list[tuple[str, str]], current: str) -> str:
    labels = dict(pages)
    groups = grouped(pages)

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
    current = name if name != "README" else "index"
    article = (
        f'<article class="prose" id="main">\n{body}\n<p class="source">Source: <a href="{BLOB}{source}">{source}</a>, Markdown in the repository; this page is built from it. '
        f'<a href="{REPO}/edit/main/{source}">Edit it on GitHub</a>.</p>\n{pager(pages, current)}</article>'
    )
    return (
        head(f"{title} · Tessri guide", description[:300], 1, "guide/" if current == "index" else f"guide/{name}.html")
        + "<body>\n"
        + skip()
        + top(1, "guide", demo)
        + f'<div class="wrap guide">\n{nav(pages, current)}\n{article}\n{rail(body)}</div>\n'
        + foot(1, demo)
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
    """The README's example as a reader sees it: the command line, the opening sentence and its counts, then the rest of
    the output (the table, the people, the tests, the dependencies and the caveat) folded under a summary that says
    what it holds, so the page shows the shape of the answer and keeps the whole of it one click away."""
    first, _, rest = readme_example().partition("\n")
    if not first.startswith("$ "):
        raise BuildError("the README example should start with the command that produced it")
    head, sep, tail = rest.partition("\n\n| ")
    if not sep:  # an example without a table is shown whole
        _, body = render_markdown(rest)
        return f'{cmdline(first[2:])}\n<div class="output prose">\n{body}\n</div>'
    _, top = render_markdown(head)
    _, more = render_markdown("| " + tail)
    return (
        f'{cmdline(first[2:])}\n<div class="output prose">\n{top}\n'
        '<details class="fold"><summary>The rest of the output: the modules, the people, the tests and what the analysis cannot see</summary>\n'
        f'{more}\n</details>\n</div>'
    )


LANDING_DESCRIPTION = (
    "Keep code understandable. Tessri follows code beyond the diff: "
    "where to look first, who can look, what a change did to the structure, and what nobody maintains. Offline, zero dependencies."
)


def review_diagram(b: dict) -> str:
    """Draw the teaching case only when its actual evidence still supports the illustrated relationships."""
    rows = {r["path"]: r for r in b["triage"]["files"]}
    changed, deleted, outside, test = "billing/invoices.py", "util/money.py", "reports/summary.py", "tests/test_invoices.py"
    dangling = b["check"]["dangling_imports"]
    expected_run = f": {review_example.TEST_CASES} passed (exit 0)"
    if (
        changed not in rows or deleted not in rows or outside in rows
        or rows[deleted]["change"] != "deleted"
        or "cents" not in rows[changed].get("symbols", {}).get("added", [])
        or "cents" not in rows[deleted].get("symbols", {}).get("removed", [])
        or {"deleted": deleted, "importers": [outside]} not in dangling
        or test not in b["triage"]["tests"]["paths"]
        or not any(expected_run in line for line in b["validation"]["ran"])
    ):
        raise BuildError("the worked example no longer supports the home diagram; update the fixture and drawing together")
    # These edges describe the authored fixture, not inferred architectural intent.
    # Both importers named the old module at the base; only the unchanged importer still does.
    import_line = "from util.money import cents"
    if import_line not in review_example.BASE[changed] or import_line not in review_example.BASE[outside]:
        raise BuildError("the home diagram's removed and retained imports must exist in the fixture's base")
    template = (SITE / "review-diagram.html").read_text(encoding="utf-8")
    values = {
        "changed_path": changed, "deleted_path": deleted, "outside_path": outside,
        "test_path": test, "test_count": review_example.TEST_CASES, "symbol": "cents",
        "code_files": b["change"]["code_files"], "lines": b["change"]["lines"],
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", html.escape(str(value)))
    if re.search(r"{{[\w:-]+}}", template):
        raise BuildError("unfilled placeholders in site/review-diagram.html")
    return template


def landing(demo: dict | None, worked: dict) -> str:
    template = (SITE / "index.html").read_text(encoding="utf-8")
    example = example_panel()
    filled = (
        template.replace("{{mark}}", MARK)
        .replace("{{repo}}", REPO)
        .replace("{{notices}}", NOTICES)
        .replace("{{theme_boot}}", THEME_BOOT)
        .replace("{{theme_button}}", theme_button())
        .replace("{{search_button}}", search_button())
        .replace("{{social}}", social("Tessri", LANDING_DESCRIPTION, ""))
        .replace("{{review_diagram}}", review_diagram(worked))
        .replace("{{live_review}}", '<section class="band" id="live-review"><span class="label">Tessri on itself</span><h2>The latest change, with its evidence.</h2>' + handoff(demo) + '</section>' if demo else "")
        .replace("{{field_notes}}", '<ul class="review-notes">' + ''.join(f'<li><time datetime="{p["date"]}">{_day(p["date"])}</time><h3><a href="blog/{p["slug"]}.html">{html.escape(p["title"])}</a></h3><p>{html.escape(p["summary"].split(". ", 1)[0])}.</p></li>' for p in posts()[:2]) + '</ul>')
        .replace("{{example}}", example)
        .replace("{{drawing}}", drawing(demo["reach"]) if demo else "")
        .replace("{{drawing_class}}", " with-drawing" if demo else "")
        .replace("{{foot}}", foot(0, bool(demo)))
        .replace("{{scripts}}", SCRIPTS)
    )
    filled = re.sub(r"{{icon:([\w-]+)}}", lambda m: icon(m.group(1)), filled)
    filled = re.sub(r"{{fig:([\w-]+)}}", lambda m: figures.inline(m.group(1)), filled)
    filled = re.sub(r"{{copy:([^}]+)}}", lambda m: copy_button(m.group(1)), filled)
    left = re.findall(r"{{[\w:-]+}}", filled)
    if left:
        raise BuildError(f"unfilled placeholders in site/index.html: {', '.join(sorted(set(left)))}")
    return filled


# --- The handoff: the brief, read in three steps --------------------------------------------------------------------

# (slug, the brief's heading, the step's name, what the step rests on)
STEPS = (
    ("look-first", "Look first", "Look first", "Ranked by history: commits in 90 days, fixes and reverts, and who went quiet. The owners are the people who changed the file, up to the base."),
    ("what-changed", "What it did to the structure", "What changed", "What the change did to the import graph, from one analysis of the base and one of the working tree: orphans, cycles, dangling imports, changed code nobody active maintains, and what outside the change imports it."),
    ("validation", "Validation", "Validation", "The candidate tests are paths that reach the change; a check counts as run only when the host recorded it. Nothing here claims that a test passed."),
)
# The two kinds of line the validation section writes: a candidate is a path, a run is a record.
VALIDATION_TAGS = (
    (("Candidate tests", "No test file reaches"), "guess", "Candidates"),
    (("Checks the host ran",), "fact", "Ran"),
)


def sections(page: str) -> dict[str, str]:
    """The brief's level-two sections by heading, and under "" the text before the first of them."""
    out: dict[str, str] = {}
    name = ""
    body: list[str] = []
    for line in page.splitlines():
        if line.startswith("## "):
            out[name] = "\n".join(body).strip()
            name, body = line[3:].strip(), []
        else:
            body.append(line)
    out[name] = "\n".join(body).strip()
    return out


def _tag_validation(body: str) -> str:
    """The validation section's HTML with a label on each kind of line: the candidates, and what the host recorded as run."""
    for starts, cls, label in VALIDATION_TAGS:
        for start in starts:
            marker = f"<p>{start}"
            if marker in body:
                body = body.replace(marker, f'<p class="val {cls}"><span class="tag {cls}">{label}</span>{start}', 1)
                break
    return body


def handoff(demo: dict) -> str:
    """The hero's artifact: the brief of the latest change under its command line, its scope, then three of its sections
    as steps (tabs with script, stacked without), and the way to the whole page and the report."""
    parts = sections(demo["brief"])
    pre = parts.get("", "")
    if pre.startswith("# "):
        pre = pre.partition("\n")[2]  # the panel has a command line instead of the page's title
    scope = pre.strip().split("\n\n")[0]
    _, scope_html = render_markdown(scope)
    scope_html = scope_html.replace("<p>", '<p class="scope">', 1)
    tabs: list[str] = []
    panels: list[str] = []
    for i, (slug_, heading, name, caption) in enumerate(STEPS):
        if heading not in parts:
            raise BuildError(f"the demo brief has no section named {heading!r}")
        _, body = render_markdown(parts[heading])
        if slug_ == "validation":
            body = _tag_validation(body)
        first = i == 0
        selected = "true" if first else "false"
        extra = "" if first else ' tabindex="-1"'
        tabs.append(f'<button class="step" role="tab" type="button" id="tab-{slug_}" aria-controls="step-{slug_}" aria-selected="{selected}"{extra}><span class="n">{i + 1}</span>{html.escape(name)}</button>')
        panels.append(
            f'<section class="step-panel" role="tabpanel" id="step-{slug_}" aria-labelledby="tab-{slug_}">\n'
            f'<h3 class="step-name">{html.escape(heading)}</h3>\n<p class="caption">{html.escape(caption)}</p>\n<div class="output prose">\n{body}\n</div>\n</section>'
        )
    return (
        '  <div class="handoff" id="brief" tabindex="-1">\n'
        f'{cmdline("tessri brief --since " + demo["base"])}\n'
        '<div class="body">\n'
        f"{scope_html}\n"
        f'<div class="steps-bar" role="tablist" aria-label="The brief, step by step">{"".join(tabs)}</div>\n'
        + "\n".join(panels)
        + f'\n<div class="more"><p>{_analysed(demo)}. Three of the page\'s five sections; '
        '<a href="demo/">the whole page</a> adds the commits, what needs a person and the caveats, and <a href="demo/report.html">the HTML report</a> has the module graph and the impact explorer.</p>'
        f'<a class="button quiet" href="demo/">Open the full demo {icon("arrow-right")}</a></div>\n'
        "</div>\n  </div>\n"
    )


# --- The blog: notes from building Tessri, illustrated -----------------------------------------------------------------

POST_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(?:(\d{2})-)?([a-z][a-z0-9-]*)\.md$")  # an optional two-digit ordinal orders posts of one day
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def posts() -> list[dict]:
    """The posts under docs/blog, newest first: `date` and `slug` from the file name, `title` from the level-one heading,
    `summary` from the first paragraph, `figure` the first drawing the post places, `body` the rendered Markdown."""
    found = []
    if not BLOG.is_dir():
        return found
    for md in sorted(BLOG.glob("*.md")):
        m = POST_NAME.match(md.name)
        if not m:
            raise BuildError(f"docs/blog/{md.name}: a post is named YYYY-MM-DD-slug.md, or YYYY-MM-DD-NN-slug.md to order a day's posts")
        text = md.read_text(encoding="utf-8")
        title, body = render_markdown(text)
        if not title:
            raise BuildError(f"docs/blog/{md.name} has no level-one heading")
        first = re.search(r"<p>(.*?)</p>", body, re.S)
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", first.group(1))).strip() if first else ""
        figure = re.search(r"!\[[^\]]*\]\(figures/([\w-]+)\.svg\)", text)
        found.append({"date": m.group(1), "order": m.group(2) or "", "slug": m.group(3), "title": title, "summary": html.unescape(summary), "figure": figure.group(1) if figure and figure.group(1) in figures.FIGURES else None, "body": body, "source": f"docs/blog/{md.name}"})
    found.sort(key=lambda p: (p["order"], p["slug"]))
    found.sort(key=lambda p: p["date"], reverse=True)  # newest day first, a day's posts in their own order
    return found


def _day(date: str) -> str:
    """`2026-11-20` as `20 November 2026`."""
    year, month, day = date.split("-")
    return f"{int(day)} {MONTHS[int(month) - 1]} {year}"


def blog_index(all_posts: list[dict], demo: bool = False) -> str:
    cards = []
    for post in all_posts:
        art = f'<div class="art">{figures.inline(post["figure"])}</div>' if post["figure"] else ""
        cards.append(
            f'<article class="post-card">{art}<div class="text"><time datetime="{post["date"]}">{_day(post["date"])}</time>'
            f'<h2><a href="{post["slug"]}.html">{html.escape(post["title"])}</a></h2><p>{html.escape(post["summary"])}</p></div></article>'
        )
    body = (
        '<div class="wrap blog" id="main">\n<header class="blog-head"><span class="label">Blog</span><h1>Notes from building Tessri</h1>'
        "<p>How the numbers were tested, what the pages are for and how the code is put together, with the drawings: for the people who read Tessri's output, and for the ones who might change its code.</p></header>\n"
        + ('<div class="posts">\n' + "\n".join(cards) + "\n</div>" if cards else "<p>No posts yet.</p>")
        + "\n</div>\n"
    )
    return head("Blog · Tessri", "Notes from building Tessri: how the numbers were tested, what the pages are for, how the code is put together.", 1, "blog/") + "<body>\n" + skip() + top(1, "blog", demo) + body + foot(1, demo) + SCRIPTS + "\n</body>\n</html>\n"


def post_page(post: dict, all_posts: list[dict], demo: bool = False) -> str:
    i = next(k for k, p in enumerate(all_posts) if p["slug"] == post["slug"])
    older = all_posts[i + 1] if i + 1 < len(all_posts) else None
    newer = all_posts[i - 1] if i > 0 else None
    links = []
    if newer:
        links.append(f'<a class="prev" rel="prev" href="{newer["slug"]}.html"><span>Newer</span>{html.escape(newer["title"])}</a>')
    if older:
        links.append(f'<a class="next" rel="next" href="{older["slug"]}.html"><span>Older</span>{html.escape(older["title"])}</a>')
    body = post["body"].replace("</h1>", f'</h1>\n<p class="date"><time datetime="{post["date"]}">{_day(post["date"])}</time></p>', 1)
    article = (
        f'<article class="prose post" id="main">\n{body}\n<p class="source">Source: <a href="{BLOB}{post["source"]}">{post["source"]}</a>, Markdown in the repository; this page is built from it. '
        f'<a href="{REPO}/edit/main/{post["source"]}">Edit it on GitHub</a>.</p>\n'
        + (f'<nav class="pager" aria-label="Other posts">{"".join(links)}</nav>\n' if links else "")
        + "</article>"
    )
    return (
        head(f"{post['title']} · Tessri blog", post["summary"][:300] or post["title"], 1, f"blog/{post['slug']}.html")
        + "<body>\n" + skip() + top(1, "blog", demo)
        + f'<div class="wrap blog">\n{article}\n</div>\n'
        + foot(1, demo) + SCRIPTS + "\n</body>\n</html>\n"
    )


# --- The board: Tessri on its own history, for fun ---------------------------------------------------------------------

BOARD_ROWS = 12


def board_content(analysis, now: float | None = None) -> dict:
    """Who committed in the last 90 days, who maintains what and who has been quiet, from this checkout's history as
    Tessri reads it: bots and ignored authors apart, names as git has them, never an address."""
    from tessri import gitlog  # noqa: E402  (the package in this checkout)

    now = time.time() if now is None else now
    act = analysis.activity
    if act is None:
        raise BuildError("the board needs git history")
    total: dict[str, int] = {}
    for line in _git("log", "--format=%aN%x09%aE").splitlines():
        name, _, email = line.partition("\t")
        if name and not gitlog.is_ignored(name, email, ()):
            who = gitlog.identity(name, email)
            total[who] = total.get(who, 0) + 1
    maintained: dict[str, int] = {}
    for rec in analysis.records.values():
        if rec.kind == "code" and rec.owner:
            maintained[rec.owner] = maintained.get(rec.owner, 0) + 1
    rows = [
        {"name": a.name, "recent": a.commits_active, "total": total.get(who, 0), "maintains": maintained.get(a.name, 0), "idle_days": max(0, int((now - a.last) // 86400))}
        for who, a in act.authors.items()
    ]
    rows.sort(key=lambda r: (-r["recent"], -r["total"], r["name"]))
    return {
        "rows": rows[:BOARD_ROWS], "people": len(rows), "commits": act.commits, "window_days": 90,
        "inactive_days": analysis.ownership.inactive_days if analysis.ownership else 180,
        "code_files": sum(1 for r in analysis.records.values() if r.kind == "code"),
        "built": time.strftime("%Y-%m-%d", time.gmtime(now)),
    }


def board_page(board: dict) -> str:
    top_recent = max([r["recent"] for r in board["rows"]] + [1])
    lines = []
    for i, r in enumerate(board["rows"], 1):
        quiet = f' <span class="quiet">quiet for {r["idle_days"]} days</span>' if r["idle_days"] > board["inactive_days"] else ""
        width = round(100 * r["recent"] / top_recent)
        lines.append(
            f'<li><span class="rank">{i}</span><span class="who">{html.escape(r["name"])}{quiet}</span>'
            f'<span class="bar" style="--w:{width}%"><i></i><b>{r["recent"]}</b></span>'
            f'<span class="num">{r["total"]:,}</span><span class="num">{r["maintains"]}</span></li>'
        )
    body = (
        '<div class="wrap blog board" id="main">\n<header class="blog-head"><span class="label">The board</span><h1>Who keeps Tessri understandable</h1>'
        f"<p>Tessri on its own history, for fun. {board['people']} {'person has' if board['people'] == 1 else 'people have'} committed to this repository, {board['commits']:,} commits in all, {board['code_files']} code files. "
        "Commits in the last 90 days first, then all time, then the code files each person maintains most, as <code>tessri scan</code> credits them: a recent commit weighs more than an old one, a year halves it, and a bot owns nothing. "
        f"Built from the checkout on {_day(board['built'])}; the names are git author names.</p></header>\n"
        '<ol class="standings"><li class="head"><span class="rank">#</span><span class="who">Who</span><span class="bar">Commits, 90 days</span><span class="num">All time</span><span class="num">Files maintained</span></li>\n'
        + "\n".join(lines)
        + "\n</ol>\n"
        f'<p class="join">Want on it? <a href="{BLOB}CONTRIBUTING.md">CONTRIBUTING.md</a> says what the code keeps and where things live; a page of the guide that reads badly is a way in, and so is a number you can show to be wrong.</p>\n</div>\n'
    )
    return head("The board · Tessri", "Tessri on its own history, for fun: who committed lately, who maintains what, who has been quiet.", 1, "board/") + "<body>\n" + skip() + top(1, "board", True) + body + foot(1, True) + SCRIPTS + "\n</body>\n</html>\n"


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
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"  # "HEAD" when detached, as on a pull request's merge ref
    merged = re.match(r"Merge pull request #(\d+)", subject)
    if merged:
        return {"sha": sha, "pr": int(merged.group(1)), "title": body[0] if body else subject, "branch": branch}
    return {"sha": sha, "pr": None, "title": subject, "branch": branch}


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
    return {"report": htmlreport.build_html(analysis, build_report(analysis)), "brief": page, "change": latest_change(), "base": base, "reach": reach(analysis.graph, found.group(1)), "board": board_content(analysis)}


def _demote(body: str) -> str:
    """Every heading one level down, so a rendered page sits under the page's own heading."""
    return re.sub(r"<(/?)h([1-5])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", body)


def _what(change: dict) -> str:
    title = html.escape(change["title"])
    if change["pr"]:
        return f'pull request <a href="{REPO}/pull/{change["pr"]}">#{change["pr"]}</a>, \u201c{title}\u201d, merged as <code>{change["sha"][:9]}</code>'
    return f'the commit \u201c{title}\u201d (<code>{change["sha"][:9]}</code>)'


def _analysed(demo: dict) -> str:
    """The sentence that says what the brief is of. A build on the default branch has the latest change there; a build
    anywhere else names its branch (or a detached checkout) and commit, so a preview never passes for the deployed site."""
    change = demo["change"]
    if change["branch"] == DEFAULT_BRANCH:
        return f"The latest change on Tessri's own <code>{DEFAULT_BRANCH}</code> is {_what(change)}"
    where = "a detached checkout" if change["branch"] == "HEAD" else f'<code>{html.escape(change["branch"])}</code>'
    return (
        f'This build analysed {where} at <code>{change["sha"][:9]}</code>, \u201c{html.escape(change["title"])}\u201d, against its parent <code>{html.escape(demo["base"])}</code>; '
        f"the deployed site builds from <code>{DEFAULT_BRANCH}</code>"
    )


def demo_page(demo: dict) -> str:
    """`demo/index.html`: the whole brief, under a heading that says what it is."""
    _, body = render_markdown(demo["brief"])
    base = html.escape(demo["base"])
    if demo["change"]["branch"] == DEFAULT_BRANCH:
        built = f'the change compared with <code>{DEFAULT_BRANCH}</code> as it was before it (<code>{base}</code>), built when the site was deployed, and every push to <code>{DEFAULT_BRANCH}</code> rebuilds it. '
    else:
        built = f"the change compared with its parent (<code>{base}</code>), built from that checkout as a preview. "
    intro = (
        '<h1 id="tessri-on-itself">Tessri on itself</h1>\n'
        f'<p>{_analysed(demo)}. Below is the page <code>tessri brief --since {base}</code> hands a person for it: {built}'
        '<a href="report.html">The HTML report of the repository</a>, with the module graph and the impact explorer, is what <code>tessri scan . --format html</code> writes, built the same way.</p>\n'
    )
    article = (
        f'<article class="prose" id="main">\n{intro}{_demote(body)}\n'
        f'<p class="source">Built from this checkout by <a href="{BLOB}tools/build_site.py">tools/build_site.py</a> with <code>--demo</code>; the <a href="../guide/brief.html">brief guide</a> explains every section, and the <a href="../guide/html-report.html">report guide</a> the explorer.</p>\n</article>'
    )
    return (
        head("Tessri on itself · demo", "The brief of the latest change on Tessri's own repository, and the HTML report of the repository, rebuilt on every push.", 1, "demo/")
        + "<body>\n"
        + skip()
        + top(1, "demo", True)
        + f'<div class="wrap demo-page">\n{article}\n</div>\n'
        + foot(1, True)
        + SCRIPTS
        + "\n</body>\n</html>\n"
    )


def search_entries(where: str, title: str, body: str) -> list[dict]:
    """What the search over the guide knows about one page: the page itself, then each of its sections, as plain
    text. `where` is the page's address under the site root."""

    def text(fragment: str) -> str:
        fragment = re.sub(r"<svg\b.*?</svg>", " ", fragment, flags=re.S)  # a drawing's labels are not the page's words
        return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()

    parts = re.split(r'(?=<h2 id=")', body)
    entries = [{"t": title, "u": where, "h": "", "b": text(parts[0])[:1500]}]
    for part in parts[1:]:
        m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', part)
        if not m:
            continue
        entries.append({"t": title, "u": f"{where}#{m.group(1)}", "h": text(m.group(2)), "b": text(part[m.end():])[:1500]})
    return entries


def not_found(demo: bool) -> str:
    """`404.html`, which GitHub Pages serves for any address the site does not have. Every link on it is pinned to
    the site's root, since the page appears at the address that was asked for."""
    return (
        head("Not found · Tessri", "There is no page at this address.", 0, "404.html", base=True)
        + "<body>\n"
        + skip()
        + top(0, None, demo)
        + '<main class="wrap notfound" id="main">\n<h1 id="not-found">No page here.</h1>\n'
        '<p>The address may be from an older version of the site, or mistyped. <a href="guide/">The guide</a> lists every page Tessri has, '
        'and <kbd>/</kbd> searches it from any page.</p>\n'
        f'<p class="actions"><a class="button cta" href="./">Home {icon("arrow-right")}</a><a class="button quiet" href="guide/">The guide</a></p>\n</main>\n'
        + foot(0, demo)
        + SCRIPTS
        + "\n</body>\n</html>\n"
    )


def sitemap(paths: list[str]) -> str:
    urls = "".join(f"<url><loc>{html.escape(SITE_URL + p, quote=True)}</loc></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


def build(out: Path, demo: bool = False) -> list[Path]:
    """Write the site into `out` and return the files written. With `demo`, the pages that run Tessri on this checkout."""
    content = demo_content() if demo else None  # before anything is written
    worked = review_example.generate()
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
    write("index.html", landing(content, worked))
    (out / "example").mkdir()
    example_html = review_example.briefhtml.render(worked, example=True)
    example_html = example_html.replace("</head>", social("A worked review · Tessri", "Two passing billing tests and an unchanged importer of a deleted file. A reproducible teaching review.", "example/") + "</head>")
    write("example/index.html", example_html)
    write("example/brief.json", json.dumps(worked, ensure_ascii=False, indent=2) + "\n")
    write("example/brief.md", review_example.brief.markdown(worked))
    if FIGURES.is_dir():  # the files Markdown viewers show; the pages themselves inline the drawings
        (out / "guide" / "figures").mkdir()
        for svg in sorted(FIGURES.glob("*.svg")):
            shutil.copyfile(svg, out / "guide" / "figures" / svg.name)
            written.append(out / "guide" / "figures" / svg.name)
    pages = guide_index()
    known = {s for s, _ in pages}
    entries: list[dict] = []
    addresses = ["", "example/"]
    for md in sorted(GUIDE.glob("*.md")):
        name = md.stem
        if name != "README" and name not in known:
            raise BuildError(f"docs/guide/{md.name} is not linked from docs/guide/README.md, so the guide index would not show it")
        title, body = render_markdown(md.read_text(encoding="utf-8"))
        if not title:
            raise BuildError(f"docs/guide/{md.name} has no level-one heading")
        where = "guide/" if name == "README" else f"guide/{name}.html"
        write(f"guide/{'index' if name == 'README' else name}.html", guide_page(name, title, body, pages, demo))
        entries.extend(search_entries(where, title, body))
        addresses.append(where)
    all_posts = posts()
    (out / "blog").mkdir()
    write("blog/index.html", blog_index(all_posts, bool(content)))
    addresses.append("blog/")
    for post in all_posts:
        write(f"blog/{post['slug']}.html", post_page(post, all_posts, bool(content)))
        entries.extend(search_entries(f"blog/{post['slug']}.html", post["title"], post["body"]))
        addresses.append(f"blog/{post['slug']}.html")
    if content:
        (out / "demo").mkdir()
        write("demo/report.html", content["report"])
        write("demo/index.html", demo_page(content))
        (out / "board").mkdir()
        write("board/index.html", board_page(content["board"]))
        addresses.extend(["demo/", "demo/report.html", "board/"])
    write("search.json", json.dumps(entries, ensure_ascii=False, separators=(",", ":")))
    write("404.html", not_found(bool(content)))
    write("sitemap.xml", sitemap(addresses))
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n")
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
