"""`tessri/mentions.py`: which of the tests that reach a changed file name the definitions the change touched, as
identifiers in their code."""

import time
import unittest

from helpers import TempRepo, git, write_tree
from tessri import config, mentions, triage

ALICE = ("Alice Adams", "alice@example.com")


class SearchableTest(unittest.TestCase):
    def test_the_last_segment_is_searched_when_it_can_mean_something(self):
        self.assertEqual(mentions.searchable("Shape.area"), "area")
        self.assertEqual(mentions.searchable("module.exports.run"), "run")
        self.assertEqual(mentions.searchable("$el"), "$el")
        self.assertEqual(mentions.searchable("gross"), "gross")

    def test_short_common_and_unnameable_names_are_not(self):
        for name in ("f", "ab", "default", "Widget.constructor", "exports", "Widget.__init__", "_join", "Shape.#secret", "ref.should unwrap nested values", "nodeOps.quoted-key"):
            self.assertIsNone(mentions.searchable(name), name)


class IdentifiersTest(unittest.TestCase):
    def test_python_identifiers_come_from_code_not_strings_or_comments(self):
        found = mentions.identifiers("from core import a\n\n\ndef test_a():\n    assert a.f0() == 0  # calls gee\n    s = 'aitch'\n", "Python")
        self.assertTrue({"core", "a", "test_a", "f0"} <= found)
        self.assertFalse({"gee", "aitch", "calls"} & found)

    def test_javascript_identifiers_leave_out_strings_templates_comments_and_regexes(self):
        text = "import { insert } from './ops'\nit('walks the tree', () => { expect(insert(1)).toBe(2) /* remove */ ; const r = /walk/; `${insert} nope` })\n"
        found = mentions.identifiers(text, "TypeScript")
        self.assertTrue({"insert", "expect", "toBe"} <= found)
        self.assertFalse({"walks", "remove", "walk", "nope"} & found)

    def test_an_unreadable_text_or_an_unread_language_is_none(self):
        self.assertIsNone(mentions.identifiers("def f(:\n  '''open", "Python"))
        self.assertIsNone(mentions.identifiers("const s = `abc\n", "JavaScript"))  # an open template; an unclosed brace still tokenizes
        self.assertIsNone(mentions.identifiers("package main\nfunc main() {}\n", "Go"))
        self.assertEqual(mentions.identifiers("", "Python"), set())


class ComputeTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, {
            "tests/test_near.py": "from core import a\n\n\ndef test_f():\n    assert a.f() == 1\n    assert a.old_name is None\n",
            "tests/test_far.py": "from core import b\n\n\ndef test_g():\n    assert b.via_g() == 2  # g\n",
            "tests/broken.py": "def test_x(:\n",
            "web/a.spec.js": "import { insert } from './a'\ntest('x', () => expect(insert()).toBe(1))\n",
        })
        self.rows = [
            {"path": "core/a.py", "change": "modified", "test": False, "symbols": {"available": True, "added": ["g", "f"], "changed": ["Shape.area", "ab"], "removed": ["old_name"], "module_level": False}},
            {"path": "web/a.js", "change": "modified", "test": False, "symbols": {"available": True, "added": [], "changed": ["insert", "nodeOps.remove"], "removed": [], "module_level": False}},
            {"path": "tests/test_near.py", "change": "modified", "test": True, "symbols": {"available": True, "added": ["test_f"], "changed": [], "removed": [], "module_level": False}},
            {"path": "core/gone.py", "change": "deleted", "test": False, "symbols": {"available": True, "added": [], "changed": [], "removed": ["gone"], "module_level": False}},
            {"path": "svc/main.go", "change": "modified", "test": False, "symbols": {"available": False, "reason": "no"}},
        ]
        self.reach = {"core/a.py": {"tests/test_far.py": 2, "tests/test_near.py": 1, "tests/broken.py": 1}, "web/a.js": {"web/a.spec.js": 1}}
        self.languages = {"tests/test_near.py": "Python", "tests/test_far.py": "Python", "tests/broken.py": "Python", "web/a.spec.js": "JavaScript"}
        mentions.compute(self.root, self.rows, self.reach, self.languages)

    def test_each_searchable_name_maps_to_the_reaching_tests_that_use_it_nearest_first(self):
        s = self.rows[0]["symbols"]
        self.assertEqual(s["named_in"], {"Shape.area": [], "old_name": ["tests/test_near.py"]})  # `f`, `g` and `ab` are too short to search
        self.assertEqual(s["unsearched"], ["g", "f", "ab"])
        self.assertEqual(s["tests_unread"], ["tests/broken.py"])
        self.assertEqual(self.rows[1]["symbols"], {"available": True, "added": [], "changed": ["insert", "nodeOps.remove"], "removed": [], "module_level": False, "named_in": {"insert": ["web/a.spec.js"], "nodeOps.remove": []}, "unsearched": []})

    def test_test_rows_deleted_files_and_unread_files_are_left_alone(self):
        for row in self.rows[2:]:
            self.assertNotIn("named_in", row["symbols"], row["path"])

    def test_the_summary_counts_what_was_searched(self):
        self.assertEqual(mentions.summary(self.rows), {"touched": 7, "named": 2, "unnamed": 2, "unsearched": 3})
        self.assertIsNone(mentions.summary(self.rows[2:]))

    def test_the_sentence_and_the_open_items_say_what_was_found(self):
        self.assertEqual(
            mentions.line(self.rows),
            "By name, in the tests that reach their file: `insert` (`web/a.spec.js`) is named; `Shape.area` and `nodeOps.remove` are named in none; "
            "`old_name` (`tests/test_near.py`) was removed but is still named; `g`, `f` and `ab` were not searched, being too short, private or too common; "
            "1 reaching test file could not be read.",
        )
        self.assertIsNone(mentions.line(self.rows[2:]))
        items = mentions.open_items(self.rows)
        self.assertEqual([i["kind"] for i in items], ["definitions-unnamed", "removed-still-named"])
        self.assertEqual(items[0]["text"], "No test that reaches the file names `Shape.area` (`core/a.py`) and `nodeOps.remove` (`web/a.js`): find the test that exercises them without saying the name, or write one.")
        self.assertEqual(items[0]["files"], ["core/a.py", "web/a.js"])
        self.assertEqual(items[1]["text"], "`old_name` (`core/a.py`) was removed, but `tests/test_near.py` still names it: run or update that test.")
        self.assertEqual(items[1]["files"], ["tests/test_near.py"])

    def test_a_name_two_files_share_is_told_apart_by_its_file(self):
        rows = [
            {"path": "a.py", "change": "modified", "test": False, "symbols": {"available": True, "added": [], "changed": ["compute"], "removed": [], "module_level": False}},
            {"path": "b.py", "change": "modified", "test": False, "symbols": {"available": True, "added": [], "changed": ["compute", "render"], "removed": [], "module_level": False}},
        ]
        mentions.compute(self.root, rows, {"a.py": {"tests/test_near.py": 1}}, self.languages)
        self.assertEqual(mentions.line(rows), "By name, in the tests that reach their file: `compute` in `a.py`, `compute` in `b.py` and `render` are named in none.")
        self.assertEqual(mentions.open_items(rows)[0]["text"], "No test that reaches the file names `compute` (`a.py`), `compute` (`b.py`) and `render` (`b.py`): find the test that exercises them without saying the name, or write one.")

    def test_long_lists_are_cut_with_their_count(self):
        rows = [{"path": "m.py", "change": "modified", "test": False, "symbols": {"available": True, "added": [f"name{i}" for i in range(9)], "changed": [], "removed": [], "module_level": False}}]
        mentions.compute(self.root, rows, {}, {})
        self.assertEqual(mentions.line(rows), "By name, in the tests that reach their file: `name0`, `name1`, `name2`, `name3`, `name4`, `name5` and 3 more are named in none.")


class TriageTest(TempRepo):
    """Through `triage`: a Python change named by one reaching test and not by another, a JavaScript change named by its spec."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        files = {
            "core/__init__.py": "",
            "core/a.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
            "core/b.py": "from core import a\n\n\ndef via():\n    return a.g()\n",
            "tests/test_a.py": "from core import a\n\n\ndef test_f():\n    assert a.f() == 1\n",
            "tests/test_b.py": "from core import b\n\n\ndef test_via():\n    assert b.via() == 2\n",
            "web/ops.js": "export function insert(x) { return x }\nexport function remove(x) { return x }\n",
            "web/ops.test.js": "import { insert } from './ops'\ntest('inserts', () => { expect(insert(1)).toBe(1) })\n",
        }
        self.commit(files, 30, "feat: all")
        git(self.root, "checkout", "-q", "-b", "feature")
        files["core/a.py"] = "def f():\n    return 10\n\n\ndef g():\n    return 20\n"
        files["web/ops.js"] = "export function insert(x) { return x + 1 }\nexport function remove(x) { return x - 1 }\n"
        self.commit(files, 1, "feat: change them")

    def commit(self, files, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "-m", message, when=when, author=ALICE)

    def test_the_rows_carry_who_names_what_and_the_summary_counts_it(self):
        t = triage.compute(self.root, config.load(self.root), "main", now=self.now)
        by_path = {r["path"]: r["symbols"] for r in t["files"]}
        self.assertEqual(by_path["core/a.py"]["named_in"], {})  # `f` and `g` are one letter: not searched
        self.assertEqual(by_path["core/a.py"]["unsearched"], ["f", "g"])
        self.assertEqual(by_path["web/ops.js"]["named_in"], {"insert": ["web/ops.test.js"], "remove": []})
        self.assertEqual(t["summary"]["definitions"], {"touched": 4, "named": 1, "unnamed": 1, "unsearched": 2})
        text = triage.markdown(t)
        self.assertIn("- **1** of the 4 definitions it touched is named in a test that reaches the file", text)
        self.assertIn("By name, in the tests that reach their file: `insert` (`web/ops.test.js`) is named; `remove` is named in none; `f` and `g` were not searched, being too short, private or too common.", text)
        self.assertIn("named in a test when the identifier appears in the test's code", "\n".join(t["notes"]))


if __name__ == "__main__":
    unittest.main()
