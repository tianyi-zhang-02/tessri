"""The CLI writes UTF-8 whatever the stream was opened with: a Windows pipe or file takes the legacy code page, which
cannot hold the arrows, the middle dots or a path in another script that the pages carry."""

import contextlib
import io
import unittest

from helpers import TempRepo, write_tree
from tessri.cli import main


class Utf8Test(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, {
            "app/__init__.py": "",
            "app/main.py": "from lib import \u00fcber\n\nif __name__ == '__main__':\n    \u00fcber.go()\n",
            "lib/__init__.py": "",
            "lib/\u00fcber.py": "from app import main\n\n\ndef go():\n    return main\n",
        })

    def _run(self, *argv: str) -> bytes:
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", newline="")  # what a redirected stream is on Windows
        err = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(err):
            code = main([*argv, "--repo", str(self.root)])
        stream.flush()
        self.assertEqual(code, 0, err.getvalue())
        return raw.getvalue()

    def test_the_graph_page_and_its_arrows_arrive_as_utf8(self):
        out = self._run("graph")
        self.assertIn("\u21c4".encode("utf-8"), out)  # the cycle, written as A ⇄ B
        self.assertIn("\u00fcber".encode("utf-8"), out)
        with self.assertRaises(UnicodeDecodeError):
            out.decode("ascii")
        out.decode("utf-8")  # and nothing was replaced

    def test_a_stream_that_is_utf8_already_is_left_alone(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["scan", str(self.root), "--format", "json"]), 0)
        stream.flush()
        self.assertEqual(stream.encoding, "utf-8")
        self.assertTrue(raw.getvalue().startswith(b"{"))


if __name__ == "__main__":
    unittest.main()
