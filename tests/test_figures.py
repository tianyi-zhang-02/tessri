"""`tools/figures.py`: the drawings are one source for the landing page, the guide and the README. Each one is
well-formed as an inline fragment and as a standalone document, has a label, keeps its ids to itself, and the files
under docs/guide/figures/ are the ones the module makes."""

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import figures  # noqa: E402  (tools/ is not a package)


class FigureTest(unittest.TestCase):
    def test_every_figure_is_well_formed_inline_and_standalone(self):
        for name, fig in figures.FIGURES.items():
            with self.subTest(name=name):
                self.assertTrue(fig.label.endswith(".") and len(fig.label) > 40, fig.label)
                self.assertRegex(fig.viewbox, r"^0 0 \d+ \d+$")
                inline = figures.inline(name)
                self.assertTrue(inline.startswith('<svg viewBox="') and inline.endswith("</svg>"))
                ET.fromstring(inline.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1))
                doc = ET.fromstring(figures.standalone(name))
                self.assertEqual(doc.tag, "{http://www.w3.org/2000/svg}svg")
                self.assertEqual(doc[0].text, fig.label)  # the title a reader without the picture gets
                self.assertIn("prefers-color-scheme: dark", doc[1].text)
                self.assertNotIn("var(--", figures.standalone(name))  # the file cannot reach the site's tokens

    def test_ids_are_unique_within_a_figure_and_across_the_landing_page(self):
        seen: dict[str, str] = {}
        for name, fig in figures.FIGURES.items():
            ids = re.findall(r'\bid="([^"]+)"', fig.body)
            self.assertEqual(len(ids), len(set(ids)), name)
            for i in ids:
                self.assertNotIn(i, seen, f"{name} reuses id {i} of {seen.get(i)}")
                seen[i] = name
            for ref in re.findall(r"url\(#([^)]+)\)", fig.body):
                self.assertIn(ref, ids, f"{name} refers to #{ref}, which it does not define")

    def test_the_committed_files_are_current(self):
        self.assertEqual(figures.stale(), [], "run python3 tools/figures.py")
        self.assertEqual(sorted(p.stem for p in (ROOT / "docs" / "guide" / "figures").glob("*.svg")), sorted(figures.FIGURES))

    def test_the_command_line(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "figs"
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(figures.main(["--check", "--out", str(out)]), 1)  # nothing there yet
            self.assertIn("stale: ", err.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(figures.main(["--out", str(out)]), 0)
            self.assertEqual(figures.main(["--check", "--out", str(out)]), 0)


if __name__ == "__main__":
    unittest.main()
