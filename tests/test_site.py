"""The site builds from the README and the guide with nothing installed: every guide page is rendered and in the
navigation, no link inside the site points at a Markdown file or a missing page, the landing page's example is the
README's, and the small Markdown converter handles what the guide writes."""

import contextlib
import html
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_site  # noqa: E402  (tools/ is not a package)

SAMPLE = """# A page *title*

One sentence with `code <b>`, a [link](other.md#part) and **bold** and *italic* words, and 1 < 2.

## Heading two

```text
# not a heading
| not | a table |
```

- first item with `x`
  wrapped onto a second line
- second [item](../workflow-recipes.md)

1. one
2. two

| Name | Count | Note |
|---|---:|---|
| `a.py` | 1 | *uses* it |
"""


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.title, self.body = build_site.render_markdown(SAMPLE)

    def test_the_title_is_the_first_heading_without_markup(self):
        self.assertEqual(self.title, "A page title")
        self.assertIn('<h1 id="a-page-title">A page <em>title</em></h1>', self.body)
        self.assertIn('<h2 id="heading-two">Heading two</h2>', self.body)

    def test_inline_markup(self):
        self.assertIn("<code>code &lt;b&gt;</code>", self.body)
        self.assertIn('<a href="other.html#part">link</a>', self.body)
        self.assertIn("<strong>bold</strong> and <em>italic</em> words, and 1 &lt; 2.", self.body)

    def test_a_fenced_block_is_verbatim(self):
        self.assertIn('<pre><code class="language-text"># not a heading\n| not | a table |</code></pre>', self.body)
        self.assertNotIn("<h1 id=\"not-a-heading\">", self.body)

    def test_lists_and_wrapped_items(self):
        self.assertIn("<ul><li>first item with <code>x</code> wrapped onto a second line</li><li>second <a href=\"https://github.com/tianyi-zhang-02/tessri/blob/main/docs/workflow-recipes.md\">item</a></li></ul>", self.body)
        self.assertIn("<ol><li>one</li><li>two</li></ol>", self.body)

    def test_tables_with_alignment(self):
        self.assertIn('<th>Name</th><th class="num">Count</th><th>Note</th>', self.body)
        self.assertIn('<td><code>a.py</code></td><td class="num">1</td><td><em>uses</em> it</td>', self.body)

    def test_a_shell_block_is_highlighted_and_every_block_gets_a_copy_button(self):
        _, body = build_site.render_markdown("```bash\n$ tessri scan . --format json  # the report\n```\n")
        self.assertIn('<span class="tk-p">$ </span><span class="tk-k">tessri</span> scan . <span class="tk-f">--format</span> json  <span class="tk-c"># the report</span>', body)
        self.assertIn('<button class="copy mini" type="button" data-copy="$ tessri scan . --format json  # the report" aria-label="Copy">', body)
        self.assertEqual(self.body.count("<pre>"), self.body.count('class="copy mini"'))

    def test_links_are_rewritten_for_the_site(self):
        cases = {
            "scan.md": "scan.html",
            "README.md": "index.html",
            "check.md#findings": "check.html#findings",
            "#part": "#part",
            "https://example.org/x.md": "https://example.org/x.md",
            "../workflow-recipes.md": "https://github.com/tianyi-zhang-02/tessri/blob/main/docs/workflow-recipes.md",
            "../../CHANGELOG.md": "https://github.com/tianyi-zhang-02/tessri/blob/main/CHANGELOG.md",
            "../design/": "https://github.com/tianyi-zhang-02/tessri/tree/main/docs/design",
        }
        for given, want in cases.items():
            self.assertEqual(build_site.rewrite_link(given), want, given)
        with self.assertRaises(build_site.BuildError):
            build_site.rewrite_link("../../../outside.md")


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "site"
        cls.written = build_site.build(cls.out, demo=True)
        cls.pages = {p: p.read_text(encoding="utf-8") for p in cls.out.rglob("*.html")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_guide_page_is_rendered_and_in_the_navigation(self):
        sources = sorted(p.stem for p in (ROOT / "docs" / "guide").glob("*.md") if p.stem != "README")
        rendered = sorted(p.stem for p in (self.out / "guide").glob("*.html") if p.stem != "index")
        self.assertEqual(rendered, sources)
        nav = self.pages[self.out / "guide" / "index.html"]
        for name in sources:
            self.assertIn(f'href="{name}.html"', nav, name)
        self.assertIn('<a href="./" aria-current="page">Overview</a>', nav)
        self.assertIn('<a href="impact.html" aria-current="page">', self.pages[self.out / "guide" / "impact.html"])

    def test_no_link_inside_the_site_is_broken_and_none_points_at_markdown(self):
        for page, text in self.pages.items():
            for href in re.findall(r'href="([^"]+)"', text):
                if re.match(r"[a-z][a-z0-9+.-]*:", href) or href.startswith("#"):
                    continue  # a page elsewhere, or a place on this one
                self.assertFalse(href.split("#")[0].endswith(".md"), (page.name, href))
                target = (page.parent / href.split("#")[0].rstrip("/")) if href.rstrip("/") else page.parent
                if target.is_dir():
                    target = target / "index.html"
                self.assertTrue(target.exists(), (page.name, href))

    def test_the_landing_page_carries_the_readme_example(self):
        index = self.pages[self.out / "index.html"]
        example = build_site.readme_example()
        self.assertTrue(example.startswith("$ tessri "))
        self.assertIn(f"$ <b>{html.escape(example.splitlines()[0][2:])}</b>", index)
        for line in example.splitlines():
            if line.startswith("People who maintain") or line.startswith("Static analysis"):
                self.assertIn(html.escape(line), index, line)
        self.assertIn("Keep code understandable.", index)
        self.assertIn('href="guide/getting-started.html"', index)

    def test_the_pages_are_self_contained(self):
        for page, text in self.pages.items():
            self.assertNotRegex(text, r"[\w.+-]+@[\w-]+\.[\w.]+", page.name)
            self.assertEqual(re.findall(r'<(?:link|script|img|iframe)\b[^>]*\s(?:href|src)="(https?://[^"]+)"', text), [], page.name)  # nothing loaded from elsewhere: no fonts, scripts, images, trackers
            if page.name != "report.html":  # the HTML report is its own document, with its style inside
                self.assertIn('<link rel="stylesheet" href="', text)
        self.assertIn("favicon.svg", {p.name for p in self.written})
        self.assertIn(".nojekyll", {p.name for p in self.written})

    def test_a_directory_this_script_did_not_build_is_refused_and_its_own_is_reused(self):
        with tempfile.TemporaryDirectory() as plain:
            (Path(plain) / "keep.txt").write_text("mine\n", encoding="utf-8")
            with self.assertRaises(build_site.BuildError):
                build_site.build(Path(plain))
            self.assertTrue((Path(plain) / "keep.txt").exists())
        with tempfile.TemporaryDirectory() as own:
            first = build_site.build(Path(own) / "site")
            again = build_site.build(Path(own) / "site")  # the marker is there, so the directory is rebuilt
            self.assertEqual(len(again), len(first))

    def test_the_demo_runs_tessri_on_this_checkout(self):
        index = self.pages[self.out / "index.html"]
        demo = self.pages[self.out / "demo" / "index.html"]
        report = self.pages[self.out / "demo" / "report.html"]
        self.assertIn('<section class="wrap hero grid with-handoff">', index)
        self.assertIn('<div class="handoff">', index)
        self.assertIn('<a href="demo/">Demo</a>', index)
        self.assertIn("$ <b>tessri brief --since ", index)
        self.assertIn('<p class="scope">', index)
        self.assertIn('<div class="steps-bar" role="tablist" aria-label="The brief, step by step">', index)
        self.assertEqual(index.count('role="tab" type="button"'), 3)
        self.assertEqual(index.count('role="tabpanel"'), 3)
        self.assertIn('id="tab-look-first" aria-controls="step-look-first" aria-selected="true"><span class="n">1</span>Look first</button>', index)
        self.assertIn('id="tab-validation" aria-controls="step-validation" aria-selected="false" tabindex="-1"><span class="n">3</span>Validation</button>', index)
        self.assertIn('<section class="step-panel" role="tabpanel" id="step-what-changed" aria-labelledby="tab-what-changed">\n<h3 class="step-name">What it did to the structure</h3>', index)
        self.assertIn('<span class="tag guess">Candidates</span>', index)
        self.assertIn('<span class="tag fact">Ran</span>Checks the host ran', index)
        self.assertIn('<a class="button quiet" href="demo/">Open the full demo ', index)
        self.assertNotIn('id="demo"', index)
        self.assertIn('<div class="example grid with-drawing">', index)
        self.assertIn('<figure class="drawing">', index)
        self.assertIn('<p class="key"><span class="k-import">', index)
        self.assertIn('>graph.py</text>', index)
        self.assertLess(index.index('<div class="handoff">'), index.index('id="questions"'))  # the handoff is the first thing after the pitch
        self.assertIn('<h1 id="tessri-on-itself">Tessri on itself</h1>', demo)
        self.assertIn('<h2 id="review-brief-', demo)
        self.assertIn('<h3 id="read-this-with-care">Read this with care</h3>', demo)
        self.assertIn('<a href="report.html">', demo)
        self.assertIn('<a href="../demo/" aria-current="page">Demo</a>', demo)
        self.assertIn("<title>Tessri: ", report)
        self.assertIn('<a href="../demo/">Demo</a>', self.pages[self.out / "guide" / "brief.html"])
        change = build_site.latest_change()
        self.assertEqual(set(change), {"sha", "pr", "title"})
        self.assertIn(html.escape(change["title"]), demo)

    def test_the_type_the_icons_and_their_notices_ship_with_the_pages(self):
        names = {p.relative_to(self.out.resolve()).as_posix() for p in self.written}
        for name in ("fonts/inter-latin-wght.woff2", "fonts/commit-mono-latin-400.woff2", "fonts/LICENSE-inter.txt", "fonts/LICENSE-commit-mono.txt", "icons/LICENSE", "liquid.js"):
            self.assertIn(name, names)
        css = (self.out / "tessri.css").read_text(encoding="utf-8")
        self.assertIn('url("fonts/inter-latin-wght.woff2")', css)
        index = self.pages[self.out / "index.html"]
        self.assertIn('<svg class="icon icon-network" aria-hidden="true"', index)
        self.assertIn('<canvas class="liquid"></canvas>', index)
        self.assertIn('<script src="liquid.js" defer></script>', index)
        self.assertNotIn("{{", index)
        for page, text in self.pages.items():
            if page.name != "report.html":
                self.assertIn("<!-- Type: Inter and Commit Mono", text, page.name)

    def test_a_guide_page_with_sections_gets_the_rail(self):
        hooks = self.pages[self.out / "guide" / "hooks.html"]
        self.assertIn('<nav class="toc" aria-label="On this page">', hooks)
        ids = re.findall(r'<h2 id="([^"]+)">', hooks)
        self.assertGreaterEqual(len(ids), 2)
        for i in ids:
            self.assertIn(f'<a href="#{i}">', hooks)
        self.assertNotIn('class="toc"', self.pages[self.out / "guide" / "getting-started.html"])

    def test_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_site.main(["--out", str(Path(tmp) / "out")]), 0)
            self.assertTrue((Path(tmp) / "out" / "guide" / "index.html").exists())
        self.assertRegex(out.getvalue(), r"^\d+ files written to ")


class DrawingTest(unittest.TestCase):
    def graph(self):
        from tessri import graph as g

        made = g.Graph()
        made.inbound = {"pkg/core.py": {"pkg/app.py", "tools/run.py"}, "pkg/app.py": {"pkg/cli.py", "tests/test_app.py"}, "tools/run.py": {"tests/test_run.py"}, "pkg/cli.py": {"tests/test_cli.py"}}
        made.tests = {"tests/test_app.py", "tests/test_run.py", "tests/test_cli.py"}
        made.provenance = {"pkg/app.py": {"pkg/core.py": "import"}, "tools/run.py": {"pkg/core.py": "string"}, "pkg/cli.py": {"pkg/app.py": "import"}}
        return made

    def test_the_reach_by_distance_with_the_kind_of_each_edge(self):
        r = build_site.reach(self.graph(), "pkg/core.py")
        self.assertEqual(r["direct"], ["pkg/app.py", "tools/run.py"])
        self.assertEqual(r["second"], ["pkg/cli.py"])
        self.assertEqual(r["tests"], ["tests/test_app.py", "tests/test_run.py", "tests/test_cli.py"])  # nearest first
        self.assertEqual(r["kinds"], {"pkg/app.py>pkg/core.py": "import", "tools/run.py>pkg/core.py": "string", "pkg/cli.py>pkg/app.py": "import"})

    def test_the_drawing_draws_every_file_and_edge_and_names_the_tests(self):
        svg = build_site.drawing(build_site.reach(self.graph(), "pkg/core.py"))
        self.assertIn('<figure class="drawing">', svg)
        self.assertIn('<g class="bp-file bp-target"><rect class="bp-node"', svg)
        for label in ("core.py", "app.py", "run.py", "cli.py"):
            self.assertIn(f'">{label}</text>', svg)
        self.assertEqual(svg.count('class="bp-edge kind-import"'), 2)
        self.assertEqual(svg.count('class="bp-edge kind-string"'), 1)
        self.assertIn('<span class="tag guess">Candidates</span><b>3 test files reach it</b>, paths to run, not runs: <code>test_app.py</code>, <code>test_run.py</code>, <code>test_cli.py</code>.', svg)
        self.assertIn('<p class="key"><span class="k-import">an import statement</span><span class="k-guess">', svg)
        many = build_site.reach(self.graph(), "pkg/core.py")
        many["second"] = [f"pkg/m{i}.py" for i in range(12)]
        self.assertIn(">+3 more</text>", build_site.drawing(many))


BRIEF = """# Review brief: demo

`main` (base 6081a02cb) to the working tree: HEAD 9ef0fcdb0. 2 code files changed (0 added, 2 modified, 0 deleted), **21** lines.

1 commit on the way, by Carol Chen, in their words:

- `9ef0fcdb0` feat: gross (Carol Chen)

## Look first

| # | File | Why | This change | Owners | Flags |
|---:|---|---|---|---|---|
| 1 | `billing/tax.py` | 2 commits in 90 days | +4 -0 | Alice Adams 100% | - |

## What it did to the structure

**1 warn.**

## Validation

Candidate tests, nearest first: `tests/test_tax.py`. They reach the changed files; they are paths, not results.

Checks the host ran, as recorded:

- python -m pytest tests/test_tax.py: 2 passed (exit 0)

## Open for a person

- Nothing this analysis can name.
"""


class HandoffTest(unittest.TestCase):
    def test_the_brief_splits_into_its_sections(self):
        parts = build_site.sections(BRIEF)
        self.assertEqual(list(parts), ["", "Look first", "What it did to the structure", "Validation", "Open for a person"])
        self.assertTrue(parts[""].startswith("# Review brief: demo\n\n`main` (base 6081a02cb)"))
        self.assertEqual(parts["What it did to the structure"], "**1 warn.**")

    def test_the_candidates_and_the_recorded_runs_get_their_labels(self):
        _, body = build_site.render_markdown(build_site.sections(BRIEF)["Validation"])
        tagged = build_site._tag_validation(body)
        self.assertIn('<p class="val guess"><span class="tag guess">Candidates</span>Candidate tests, nearest first:', tagged)
        self.assertIn('<p class="val fact"><span class="tag fact">Ran</span>Checks the host ran, as recorded:</p>', tagged)
        none = build_site._tag_validation("<p>No test file reaches the changed code, as far as static imports show.</p>\n<p>Checks the host ran: none recorded.</p>")
        self.assertIn('<span class="tag guess">Candidates</span>No test file reaches', none)
        self.assertIn('<span class="tag fact">Ran</span>Checks the host ran: none recorded.', none)

    def test_the_handoff_is_three_steps_under_the_command_with_the_way_to_the_whole_page(self):
        demo = {"brief": BRIEF, "base": "6081a02cb", "change": {"sha": "9ef0fcdb0abc", "pr": 7, "title": "feat: gross"}}
        out = build_site.handoff(demo)
        self.assertIn("$ <b>tessri brief --since 6081a02cb</b>", out)
        self.assertIn('<p class="scope"><code>main</code> (base 6081a02cb) to the working tree: HEAD 9ef0fcdb0. 2 code files changed (0 added, 2 modified, 0 deleted), <strong>21</strong> lines.</p>', out)
        self.assertNotIn("Review brief: demo", out)
        self.assertNotIn("1 commit on the way", out)  # the scope only; the commits are on the whole page
        self.assertEqual(re.findall(r'role="tab" type="button" id="([^"]+)"', out), ["tab-look-first", "tab-what-changed", "tab-validation"])
        self.assertEqual(out.count('aria-selected="true"'), 1)
        self.assertEqual(out.count('tabindex="-1"'), 2)
        self.assertIn('<section class="step-panel" role="tabpanel" id="step-look-first" aria-labelledby="tab-look-first">\n<h3 class="step-name">Look first</h3>\n<p class="caption">Ranked by history:', out)
        self.assertIn('<td><code>billing/tax.py</code></td>', out)
        self.assertIn('<span class="tag fact">Ran</span>', out)
        self.assertIn('pull request <a href="https://github.com/tianyi-zhang-02/tessri/pull/7">#7</a>', out)
        self.assertIn('<a href="demo/">the whole page</a>', out)
        self.assertIn('<a class="button quiet" href="demo/">Open the full demo <svg class="icon icon-arrow-right"', out)
        with self.assertRaises(build_site.BuildError):
            build_site.handoff({"brief": "# x\n\n## Look first\n\nnothing\n", "base": "a", "change": demo["change"]})


class AssetsTest(unittest.TestCase):
    def test_an_icon_is_inlined_without_its_size_and_hidden_from_readers(self):
        svg = build_site.icon("copy")
        self.assertTrue(svg.startswith('<svg class="icon icon-copy" aria-hidden="true" viewBox="0 0 24 24"'), svg[:90])
        for gone in (' width="', ' height="', ' xmlns="'):
            self.assertNotIn(gone, svg.split(">", 1)[0])  # the icon's own size is dropped; the page sizes it
        for gone in ("<!--", "\n"):
            self.assertNotIn(gone, svg)
        self.assertIn('class="icon sun icon-sun"', build_site.theme_button())
        with self.assertRaises(build_site.BuildError):
            build_site.icon("no-such-icon")

    def test_python_and_data_blocks_are_highlighted_and_text_is_not(self):
        py = build_site.highlight('from x import y  # why\nname = "a < b"\nn = 42\n@dec\ndef f(): pass', "python")
        self.assertIn('<span class="tk-k">from</span> x <span class="tk-k">import</span> y  <span class="tk-c"># why</span>', py)
        self.assertIn('name = <span class="tk-s">"a &lt; b"</span>', py)
        self.assertIn('n = <span class="tk-n">42</span>\n<span class="tk-f">@dec</span>\n<span class="tk-k">def</span> f(): <span class="tk-k">pass</span>', py)
        toml = build_site.highlight('[tool]\nname = "x"  # c\ncount = 3\n{"key": true}', "toml")
        self.assertEqual(toml, '[tool]\n<span class="tk-k">name</span> = <span class="tk-s">"x"</span>  <span class="tk-c"># c</span>\n<span class="tk-k">count</span> = <span class="tk-n">3</span>\n{<span class="tk-k">"key"</span>: <span class="tk-n">true</span>}')
        self.assertEqual(build_site.highlight("x < 1  # kept as it is", "text"), "x &lt; 1  # kept as it is")
        self.assertEqual(build_site.highlight("echo a#b | grep b", "bash"), '<span class="tk-k">echo</span> a#b | <span class="tk-k">grep</span> b')


if __name__ == "__main__":
    unittest.main()
