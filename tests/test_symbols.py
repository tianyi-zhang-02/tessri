"""`tessri/symbols.py`: which functions and classes a change touched, from the diff's hunks and the parser, and how
`triage` and the brief carry them."""

import time
import unittest

from helpers import TempRepo, git, write_tree
from tessri import brief, config, symbols, triage

ALICE = ("Alice Adams", "alice@example.com")
CAROL = ("Carol Chen", "carol@example.com")
MODULE = '''"""A module."""

LIMIT = 3


def helper(x):
    return x + 1


class Shape:
    sides = 0

    def area(self):
        return 0

    @property
    def name(self):
        return "shape"


def old_way():
    return helper(0)


def outer():
    def inner():
        return 1
    return inner()
'''


class DefinitionsTest(unittest.TestCase):
    def test_every_def_and_class_with_its_span_and_dotted_name(self):
        defs = symbols.definitions(MODULE)
        self.assertEqual([d[0] for d in defs], ["helper", "Shape", "Shape.area", "Shape.name", "old_way", "outer", "outer.inner"])
        self.assertEqual(defs[0][1:], (6, 7))
        self.assertEqual(defs[3][1:], (16, 18))  # the decorator line counts as the definition's start
        self.assertEqual(defs[5][1:], (25, 28))
        self.assertEqual(defs[6][1:], (26, 27))

    def test_a_line_maps_to_the_innermost_definition_and_outside_is_module_level(self):
        defs = symbols.definitions(MODULE)
        self.assertEqual(symbols._holders([16, 7, 26, 3], defs), (["helper", "Shape.name", "outer.inner"], True))
        self.assertEqual(symbols._holders([11], defs), (["Shape"], False))  # a class-level statement
        self.assertEqual(symbols._holders([], defs), ([], False))

    def test_a_guarded_definition_keeps_its_name_and_a_broken_source_is_none(self):
        self.assertEqual([d[0] for d in symbols.definitions("if True:\n    def f():\n        pass\ntry:\n    class C:\n        pass\nexcept Exception:\n    pass\n")], ["f", "C"])
        self.assertIsNone(symbols.definitions("def broken(:\n    pass\n"))


def core(s):
    """A row's `symbols` without what `mentions` adds to it, which has tests of its own."""
    return {k: v for k, v in s.items() if k not in ("named_in", "unsearched", "tests_unread")}


class ChangeTest(TempRepo):
    """main holds the module, a JavaScript file, a Go file and a module to delete; Carol's branch edits a method, adds
    a function, removes one, touches module level, adds a file, deletes a file, moves a file with an edit, breaks a
    Python file and a JavaScript file, and edits the Go file."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Dana Doe")
        git(self.root, "config", "user.email", "dana@example.com")
        self.commit({"pkg/__init__.py": "", "pkg/shapes.py": MODULE, "pkg/gone.py": "def bye():\n    return 0\n", "pkg/moved.py": "def still():\n    return 1\n", "pkg/broken.py": "def fine():\n    return 1\n", "web/app.js": "export function a() { return 1 }\n", "web/broken.js": "function f() {\n  return 1\n}\n", "svc/main.go": "package main\n\nfunc main() {}\n", "app.py": "from pkg import shapes, gone, moved, broken\n\nif __name__ == '__main__':\n    shapes.helper(1)\n"}, ALICE, 30, "feat: shapes")
        git(self.root, "checkout", "-q", "-b", "feature")
        edited = MODULE.replace("        return 0\n", "        return self.sides * 2\n").replace("def old_way():\n    return helper(0)\n", "def new_way():\n    return helper(1)\n").replace("LIMIT = 3", "LIMIT = 4")
        git(self.root, "mv", "pkg/moved.py", "pkg/elsewhere.py")
        self.commit({"pkg/shapes.py": edited, "pkg/fresh.py": "class Fresh:\n    def go(self):\n        return 1\n", "pkg/elsewhere.py": "def still():\n    return 2\n", "pkg/broken.py": "def fine(:\n    return 1\n", "web/app.js": "export function a() { return 2 }\n", "web/broken.js": "function f() {\n  return 2\n", "svc/main.go": "package main\n\nfunc main() { run() }\n"}, CAROL, 1, "feat: carol")
        git(self.root, "rm", "-q", "pkg/gone.py")
        self.commit({}, CAROL, 0.5, "chore: drop gone")
        write_tree(self.root, {"pkg/untracked.py": "def brand_new():\n    return 1\n"})
        self.t = triage.compute(self.root, config.load(self.root), "main", now=self.now)
        self.by = {r["path"]: r["symbols"] for r in self.t["files"]}

    def commit(self, files, who, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "--allow-empty", "-m", message, when=when, author=who)

    def test_edited_added_removed_and_module_level(self):
        self.assertEqual(core(self.by["pkg/shapes.py"]), {"available": True, "changed": ["Shape.area"], "added": ["new_way"], "removed": ["old_way"], "module_level": True})

    def test_a_new_file_an_untracked_file_a_deleted_file_and_a_moved_file(self):
        self.assertEqual(core(self.by["pkg/fresh.py"]), {"available": True, "changed": [], "added": ["Fresh", "Fresh.go"], "removed": [], "module_level": False})
        self.assertEqual(core(self.by["pkg/untracked.py"]), {"available": True, "changed": [], "added": ["brand_new"], "removed": [], "module_level": False})
        self.assertEqual(core(self.by["pkg/gone.py"]), {"available": True, "changed": [], "added": [], "removed": ["bye"], "module_level": False})
        self.assertEqual(core(self.by["pkg/elsewhere.py"]), {"available": True, "changed": ["still"], "added": [], "removed": [], "module_level": False})

    def test_a_javascript_file_is_read_too(self):
        self.assertEqual(core(self.by["web/app.js"]), {"available": True, "changed": ["a"], "added": [], "removed": [], "module_level": False})

    def test_what_cannot_be_read_says_so(self):
        self.assertEqual(self.by["svc/main.go"], {"available": False, "reason": "definitions are read for Python, JavaScript and TypeScript, not Go"})
        self.assertEqual(self.by["pkg/broken.py"], {"available": False, "reason": "the file does not parse as Python"})
        self.assertEqual(self.by["web/broken.js"], {"available": False, "reason": "the file could not be read as JavaScript: a brace, string, template or comment never closes"})

    def test_the_pages_name_the_definitions_under_the_table(self):
        text = triage.markdown(self.t)
        self.assertIn("What changed in them, by definition:", text)
        self.assertIn("- `pkg/shapes.py`: added `new_way`; changed `Shape.area`; removed `old_way`; module-level code", text)
        self.assertIn("- `pkg/fresh.py`: added `Fresh`, `Fresh.go`", text)
        self.assertIn("- `web/app.js`: changed `a`", text)
        self.assertIn("Not named for 3 files: definitions are read for Python, JavaScript and TypeScript, not Go; the file could not be read as JavaScript: a brace, string, template or comment never closes; the file does not parse as Python.", text)
        self.assertLess(text.index("Look at these first:"), text.index("What changed in them"))
        self.assertLess(text.index("What changed in them"), text.index("Who can look"))
        b = brief.compute(self.root, config.load(self.root), "main", now=self.now)
        page = brief.markdown(b)
        self.assertIn("- `pkg/shapes.py`: added `new_way`; changed `Shape.area`; removed `old_way`; module-level code", page)
        self.assertIn("symbols", b["attention"]["files"][0])

    def test_many_names_are_cut_with_a_count(self):
        s = {"available": True, "changed": [f"f{i}" for i in range(9)], "added": [], "removed": [], "module_level": False}
        self.assertEqual(symbols.line("a.py", s), "`a.py`: changed `f0`, `f1`, `f2`, `f3`, `f4`, `f5` and 3 more")
        self.assertIsNone(symbols.line("a.py", {"available": True, "changed": [], "added": [], "removed": [], "module_level": False}))
        self.assertEqual(symbols.line("a.py", {"available": True, "changed": [], "added": [], "removed": [], "module_level": True}), "`a.py`: module-level code only")
        self.assertEqual(symbols.lines([{"path": "a.py"}]), [])  # no symbols at all: nothing said


if __name__ == "__main__":
    unittest.main()
