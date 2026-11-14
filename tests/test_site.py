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

    def test_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_site.main(["--out", str(Path(tmp) / "out")]), 0)
            self.assertTrue((Path(tmp) / "out" / "guide" / "index.html").exists())
        self.assertRegex(out.getvalue(), r"^\d+ files written to ")


if __name__ == "__main__":
    unittest.main()
