"""`tools/deletions.py`: every deletion in a small history, replayed through `check`, and what became of the names
it left behind."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

from helpers import TempRepo, git, write_tree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import deletions  # noqa: E402  (tools/ is not a package)


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = deletions.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class History(TempRepo):
    """lib.py is imported by core.py, run by the Makefile, named on a docs page and in the changelog. The second change
    deletes it and updates core.py; the Makefile is fixed three days later; the page never is; the changelog is a
    record, not a stale mention."""

    def setUp(self):
        super().setUp()
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, {"core.py": "import lib\n", "lib.py": "X = 1\n", "Makefile": "run:\n\tpython lib.py\n", "docs/guide.md": "Run lib.py first.\n", "CHANGELOG.md": "- added lib.py\n"})
        self.commit("start", "2026-01-01T12:00:00+0000")
        (self.root / "lib.py").unlink()
        write_tree(self.root, {"core.py": "X = 1\n"})
        self.commit("drop lib", "2026-02-01T12:00:00+0000")
        write_tree(self.root, {"Makefile": "run:\n\techo done\n"})
        self.commit("fix the Makefile", "2026-02-04T12:00:00+0000")

    def commit(self, message: str, when: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message, when=when)


class DeletionsTest(History):
    def test_every_name_left_behind_and_what_became_of_it(self):
        result = deletions.run(self.root, days=0)
        self.assertEqual((result["summary"]["changes"], result["summary"]["files_gone"], result["summary"]["left_a_name"]), (1, 1, 1))
        self.assertEqual(
            [(o["deleted"], o["referrer"], o["kind"], o["fate"], o["days"]) for o in result["outcomes"]],
            [("lib.py", "Makefile", "config", "name removed", 3), ("lib.py", "docs/guide.md", "doc", "still named", None)],
        )
        self.assertEqual(result["kinds"], {"config": {"names": 1, "resolved": 1, "within_30_days": 1, "still_named": 0}, "doc": {"names": 1, "resolved": 0, "within_30_days": 0, "still_named": 1}})
        self.assertEqual(result["changes"][0]["dangling_imports"], [])  # core.py was updated in the same change
        self.assertEqual(result["summary"]["resolved"], 1)

    def test_the_listing_and_the_json(self):
        code, out, err = run_main(str(self.root), "--days", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("1 left a name behind, 2 names in all: 1 later resolved, 1 still there", out)
        self.assertIn("lib.py  Makefile (config): name removed after 3 days", out)
        self.assertIn("lib.py  docs/guide.md (doc): still named", out)
        self.assertIn("deletions: ", err)  # progress goes to stderr
        self.assertEqual(deletions.render({**json.loads(run_main(str(self.root), "--days", "0", "--format", "json")[1]), "outcomes": [{"date": "2026-02-01", "sha": "abc", "deleted": "a.py", "moved_to": None, "referrer": "b.sh", "kind": "config", "fate": "name removed", "days": 0}]}).splitlines()[-1], "2026-02-01 abc  a.py  b.sh (config): name removed the same day")
        code, out, err = run_main(str(self.root), "--days", "0", "--format", "json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["summary"]["names"], 2)

    def test_a_history_without_a_deletion_is_an_error(self):
        code, out, err = run_main(str(self.root), "--days", "0", "--rev", "HEAD~2")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("deletions: no change deleted or moved a code file"), err)


class TokensTest(unittest.TestCase):
    def test_the_forms_a_file_is_named_in(self):
        self.assertEqual(deletions.tokens("pkg/sub/mod.py"), {"mod.py", "pkg.sub.mod", "sub.mod"})
        self.assertEqual(deletions.tokens("pkg/sub/__init__.py"), {"pkg.sub"})  # a package is named by its directory
        self.assertEqual(deletions.tokens("src/index.ts"), {"src"})
        self.assertEqual(deletions.tokens("index.ts"), set())


if __name__ == "__main__":
    unittest.main()
