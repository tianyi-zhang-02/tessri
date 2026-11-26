"""`tessri/companions.py`: the files that usually change with the changed files and are not in this change, read from
the commits of the last year up to the base, in `triage` and in the brief."""

import time
import unittest

from helpers import TempRepo, git, write_tree
from tessri import brief, companions, config, gitlog, triage

ALICE = ("Alice Adams", "alice@example.com")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


class History(TempRepo):
    """core/a.py changed six times in the year (one a bulk commit): with tests/test_a.py four times, docs/CHANGELOG.md
    every time, core/z.py and core/gone.py three times, core/k.py twice; gone.py was then deleted. A commit older than
    the window and a bot's commit touch the same files. The change edits core/a.py and core/z.py and adds core/new.py."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Dana Doe")
        git(self.root, "config", "user.email", "dana@example.com")
        a = lambda n: f"def f():\n    return {n}\n"  # noqa: E731
        self.commit({"core/__init__.py": "", "core/a.py": a(0), "core/z.py": "z = 0\n", "core/k.py": "k = 0\n", "tests/test_a.py": "from core import a\n", "docs/CHANGELOG.md": "- 0\n"}, ALICE, 400, "init")
        self.commit({"core/a.py": a(1), "core/z.py": "z = 1\n", "core/gone.py": "g = 1\n", "tests/test_a.py": "from core import a  # 1\n", "docs/CHANGELOG.md": "- 1\n"}, ALICE, 200, "one")
        self.commit({"core/a.py": a(2), "core/z.py": "z = 2\n", "core/gone.py": "g = 2\n", "core/k.py": "k = 2\n", "tests/test_a.py": "from core import a  # 2\n", "docs/CHANGELOG.md": "- 2\n"}, ALICE, 150, "two")
        self.commit({"core/a.py": a(3), "core/z.py": "z = 3\n", "core/gone.py": "g = 3\n", "core/k.py": "k = 3\n", "docs/CHANGELOG.md": "- 3\n"}, ALICE, 100, "three")
        self.commit({"core/a.py": a(4), "tests/test_a.py": "from core import a  # 4\n", "docs/CHANGELOG.md": "- 4\n"}, ALICE, 50, "four")
        self.commit({"core/a.py": a(5), "tests/test_a.py": "from core import a  # 5\n", "docs/CHANGELOG.md": "- 5\n"}, ALICE, 30, "five")
        self.commit({"core/a.py": a(6), **{f"bulk/f{i}.py": f"x = {i}\n" for i in range(gitlog.BULK_FILES)}}, ALICE, 20, "bulk: a mass import")
        self.commit({"core/a.py": a(7), "core/k.py": "k = 7\n", "docs/CHANGELOG.md": "- 7\n"}, BOT, 15, "chore: bump")
        (self.root / "core/gone.py").unlink()
        self.commit({}, ALICE, 10, "drop gone")
        write_tree(self.root, {"core/a.py": a(8), "core/z.py": "z = 8\n", "core/new.py": "n = 1\n"})
        self.cfg = config.Config()

    def commit(self, files, who, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "--allow-empty", "-m", message, when=when, author=who)


class CoChangeTest(History):
    def test_the_commits_of_the_window_and_what_they_touched_with_the_file(self):
        found = gitlog.co_changes(self.root, "HEAD", ["core/a.py", "core/z.py", "core/new.py"], self.now)
        a = found["core/a.py"]
        self.assertEqual(a.commits, 5)  # one, two, three, four, five: the first commit is out of the window, the bulk commit and the bot's do not count
        self.assertEqual(a.together, {"tests/test_a.py": 4, "docs/CHANGELOG.md": 5, "core/z.py": 3, "core/gone.py": 3, "core/k.py": 2})
        self.assertEqual((found["core/z.py"].commits, found["core/z.py"].together["core/a.py"]), (3, 3))
        self.assertEqual((found["core/new.py"].commits, found["core/new.py"].together), (0, {}))

    def test_the_latest_commits_count_and_a_bot_can_be_let_in(self):
        found = gitlog.co_changes(self.root, "HEAD", ["core/a.py"], self.now, limit=2)
        self.assertEqual((found["core/a.py"].commits, found["core/a.py"].together), (2, {"tests/test_a.py": 2, "docs/CHANGELOG.md": 2}))  # five and four
        found = gitlog.co_changes(self.root, "HEAD", ["core/a.py"], self.now, days=25)
        self.assertEqual(found["core/a.py"].commits, 0)  # the bulk commit is inside the window but does not count
        self.assertEqual(gitlog.co_changes(self.root, "HEAD", [], self.now), {})
        self.assertIsNone(gitlog.co_changes(self.root, "nowhere", ["core/a.py"], self.now))


class TriageTest(History):
    def test_companions_are_the_files_in_half_the_commits_that_still_exist_and_are_not_in_the_change(self):
        t = triage.compute(self.root, self.cfg, "HEAD", now=self.now)
        rows = {r["path"]: r for r in t["files"]}
        self.assertEqual(rows["core/a.py"]["companions"], {
            "available": True, "commits": 5, "window_days": 365,
            "usually_with": [{"path": "docs/CHANGELOG.md", "together": 5}, {"path": "tests/test_a.py", "together": 4}],
        })  # z.py is in the change, gone.py is gone, k.py was there twice
        self.assertEqual(rows["core/z.py"]["companions"]["usually_with"], [{"path": "docs/CHANGELOG.md", "together": 3}])
        self.assertEqual(rows["core/new.py"]["companions"], {"available": True, "commits": 0, "window_days": 365, "usually_with": []})
        self.assertEqual(t["companions"], [
            {"path": "docs/CHANGELOG.md", "with": [{"path": "core/a.py", "together": 5, "of": 5}, {"path": "core/z.py", "together": 3, "of": 3}]},
            {"path": "tests/test_a.py", "with": [{"path": "core/a.py", "together": 4, "of": 5}]},
        ])
        self.assertEqual(t["summary"]["companions"], 2)
        self.assertTrue(any("companion" in n for n in t["notes"]))

    def test_the_page_names_them_surest_first_and_says_what_a_companion_is(self):
        t = triage.compute(self.root, self.cfg, "HEAD", now=self.now)
        page = triage.markdown(t)
        self.assertIn("Usually changed together, not in this change: `docs/CHANGELOG.md` (with `core/a.py` 5 of 5; `core/z.py` 3 of 3 commits), `tests/test_a.py` (with `core/a.py` 4 of 5 commits). Half or more of a changed file's commits in the last 365 days, up to the base; a prompt to check, not a rule.", page)
        self.assertNotIn("@", page)

    def test_a_change_that_brings_its_companions_has_none_to_name(self):
        write_tree(self.root, {"tests/test_a.py": "from core import a  # 8\n", "docs/CHANGELOG.md": "- 8\n"})
        t = triage.compute(self.root, self.cfg, "HEAD", now=self.now)
        self.assertEqual(t["companions"], [])
        self.assertEqual({r["path"]: r["companions"]["usually_with"] for r in t["files"]}, {"core/a.py": [], "core/z.py": [], "core/new.py": [], "tests/test_a.py": []})
        self.assertIsNone(companions.line([]))
        self.assertNotIn("Usually changed together", triage.markdown(t))


class BriefTest(History):
    def test_the_brief_asks_the_person_whether_the_companions_should_be_in(self):
        b = brief.compute(self.root, self.cfg, "HEAD", now=self.now)
        self.assertEqual(b["attention"]["companions"], b["triage"]["companions"])
        (item,) = [i for i in b["open"] if i["kind"] == "companions-untouched"]
        self.assertEqual(item, {
            "kind": "companions-untouched",
            "text": "`docs/CHANGELOG.md`, `tests/test_a.py` usually change with the changed files (`docs/CHANGELOG.md` changed with `core/a.py` in 5 of its last 5 commits) but are not in this change: check whether they should be.",
            "files": ["docs/CHANGELOG.md", "tests/test_a.py"],
        })
        page = brief.markdown(b)
        self.assertIn("Usually changed together, not in this change: `docs/CHANGELOG.md`", page)
        self.assertIn("- `docs/CHANGELOG.md`, `tests/test_a.py` usually change with the changed files", page)


class WordsTest(unittest.TestCase):
    def test_one_companion_and_many_read_right_and_long_lists_are_cut(self):
        one = [{"path": "tests/test_a.py", "with": [{"path": "core/a.py", "together": 4, "of": 5}]}]
        (item,) = companions.open_items(one)
        self.assertEqual(item["text"], "`tests/test_a.py` usually changes with the changed files (`tests/test_a.py` changed with `core/a.py` in 4 of its last 5 commits) but is not in this change: check whether it should be.")
        many = [{"path": f"f{i}.py", "with": [{"path": "core/a.py", "together": 3, "of": 4}, {"path": "core/b.py", "together": 3, "of": 3}, {"path": "core/c.py", "together": 3, "of": 3}]} for i in range(8)]
        self.assertTrue(companions.line(many).startswith("Usually changed together, not in this change: `f0.py` (with `core/a.py` 3 of 4; `core/b.py` 3 of 3; and 1 more commits), "))
        self.assertIn("`f5.py` (with `core/a.py` 3 of 4; `core/b.py` 3 of 3; and 1 more commits) and 2 more under `companions`.", companions.line(many))
        self.assertEqual(companions.open_items(many)[0]["text"].split(" usually")[0], "`f0.py`, `f1.py`, `f2.py`, `f3.py`, `f4.py`, `f5.py` and 2 more")
        self.assertEqual(companions.open_items([]), [])


if __name__ == "__main__":
    unittest.main()
