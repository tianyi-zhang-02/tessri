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
        self.assertIn('<section class="band" id="demo">', index)
        self.assertIn('<a href="demo/">Demo</a>', index)
        self.assertIn("$ <b>tessri brief --since ", index)
        self.assertIn('<h3 id="look-first">Look first</h3>', index)  # the brief's first sections, one heading level down
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
