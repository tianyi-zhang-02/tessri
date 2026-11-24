"""`tessri why` as data: `facts` holds everything the text says, the text is rendered from it, and
`--format json` prints it with the metadata block."""

import contextlib
import io
import json
import time
import unittest

from helpers import TempRepo, git, write_tree

from tessri import config
from tessri.analyze import analyze
from tessri.cli import main
from tessri.explain import ORPHAN_ADVICE, TargetError, _definitions_text, explain, facts, render, why_json

ALICE = ("Alice", "alice@example.com")
BOB = ("Bob", "bob@example.com")
TREE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "import pkg.util\n",
    "pkg/util.py": "x = 1\n",
    "pkg/dead.py": "y = 2\n",
    "pkg/loader.py": 'NAME = "pkg.plugin"\n',  # names pkg/plugin.py in a string
    "pkg/plugin.py": "z = 3\n",
    "scripts/run.py": 'import pkg.core\nLOADER = "pkg.loader"\n',
    "tests/test_core.py": "import pkg.core\n",
    "docs/guide.md": "See pkg/core.py.\n",
    "CODEOWNERS": "pkg/ @alice\n",
    ".tessri.toml": 'entry = ["scripts/run.py"]\n',
}


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


class Repo(TempRepo):
    """Alice wrote everything 400 days ago and went quiet; Bob maintains pkg/util.py; pkg/new.py is untracked."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        write_tree(self.root, TREE)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "start", when=self.stamp(400), author=ALICE)
        write_tree(self.root, {"pkg/util.py": "x = 1\nz = 2\n"})
        git(self.root, "commit", "-qam", "fix: util", when=self.stamp(10), author=BOB)
        write_tree(self.root, {"pkg/new.py": "w = 1\n"})
        self.a = analyze(self.root, config.load(self.root), now=self.now)

    def stamp(self, days_ago: int) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))


class FactsTest(Repo):
    def test_text_is_rendered_from_facts(self):
        for path in self.a.records:
            with self.subTest(path):
                self.assertEqual(explain(self.a, path), render(facts(self.a, path)))

    def test_orphan(self):
        f = facts(self.a, "pkg/dead.py")
        self.assertEqual((f["path"], f["query"]), ("pkg/dead.py", "pkg/dead.py"))
        self.assertEqual((f["verdict"]["status"], f["verdict"]["reachability"], f["verdict"]["confidence"]), ("ORPHAN", "none", "high"))
        self.assertEqual(f["graph"]["dependents"], [])
        self.assertEqual(f["advice"], ORPHAN_ADVICE)
        text = explain(self.a, "pkg/dead.py")
        self.assertIn("status:        ORPHAN (confidence high)", text)
        self.assertTrue(text.endswith(ORPHAN_ADVICE))

    def test_reachable_file_with_history_owners_and_graph(self):
        f = facts(self.a, "pkg.core")  # resolved from a module name
        self.assertEqual(f["path"], "pkg/core.py")
        self.assertEqual(f["verdict"]["status"], "STABLE")  # 400 days old, but two files still import it
        self.assertEqual(f["advice"], None)
        self.assertEqual((f["git"]["tracked"], f["git"]["commits_year"], f["git"]["authors_year"]), (True, 0, 0))
        self.assertEqual(f["graph"]["reached_via"], ["scripts/run.py", "pkg/core.py"])
        self.assertEqual(f["graph"]["dependents"], ["scripts/run.py", "tests/test_core.py"])
        self.assertEqual(f["graph"]["doc_refs"], ["docs/guide.md"])
        self.assertEqual([d["path"] for d in f["graph"]["depends_on"]], ["pkg/__init__.py", "pkg/util.py"])
        self.assertEqual(f["graph"]["depends_on"][1]["status"], "ACTIVE")
        self.assertEqual(f["graph"]["stranded_if_removed"], ["pkg/util.py"])
        owners = f["owners"]
        self.assertEqual(owners["state"], "no-active-owner")
        self.assertEqual([(p["name"], p["share"], p["silent"]) for p in owners["people"]], [("Alice", 100, True)])
        self.assertEqual(owners["codeowners"], {"declared": ["@alice"], "match": None})
        text = explain(self.a, "pkg/core.py")
        self.assertIn("owners:        Alice 100% (silent 400d); NO ACTIVE OWNER", text)
        self.assertIn("reached via:   scripts/run.py -> pkg/core.py", text)
        self.assertIn("deleting it would also strand: pkg/util.py", text)

    def test_every_edge_says_what_evidence_it_rests_on(self):
        f = facts(self.a, "pkg/plugin.py")  # named in a string by pkg/loader.py, itself named in a string by the script
        self.assertEqual(f["graph"]["reached_via"], ["scripts/run.py", "pkg/loader.py", "pkg/plugin.py"])
        self.assertEqual(f["graph"]["kinds"], {"reached_via": ["string", "string"], "dependents": {"pkg/loader.py": "string"}, "depends_on": {}})
        text = explain(self.a, "pkg/plugin.py")
        self.assertIn("reached via:   scripts/run.py -(string)-> pkg/loader.py -(string)-> pkg/plugin.py", text)
        self.assertIn("depended on by: pkg/loader.py (string)", text)
        core = facts(self.a, "pkg/core.py")["graph"]["kinds"]
        self.assertEqual(core["reached_via"], ["import"])
        self.assertEqual(core["dependents"], {"scripts/run.py": "import", "tests/test_core.py": "import"})
        self.assertEqual(core["depends_on"], {"pkg/__init__.py": "package", "pkg/util.py": "import"})
        text = explain(self.a, "pkg/core.py")
        self.assertIn("reached via:   scripts/run.py -> pkg/core.py\n", text)  # an import statement goes unmarked
        self.assertIn("depended on by: scripts/run.py, tests/test_core.py\n", text)
        self.assertRegex(text, r"depends on:    pkg/__init__\.py \[\w+\] \(package\), pkg/util\.py \[ACTIVE\]\n")

    def test_active_owner_is_not_silent(self):
        f = facts(self.a, "pkg/util.py")
        bob = next(p for p in f["owners"]["people"] if p["name"] == "Bob")
        self.assertEqual((bob["silent"], f["owners"]["state"], f["git"]["fixes_90"]), (False, "owned", 1))
        self.assertNotIn("silent 10d", explain(self.a, "pkg/util.py"))

    def test_untracked_file(self):
        f = facts(self.a, "pkg/new.py")
        self.assertEqual((f["git"]["tracked"], f["git"]["last_commit"]), (False, None))
        self.assertIn("git:           no history for this file (new or untracked)", explain(self.a, "pkg/new.py"))

    def test_test_file(self):
        f = facts(self.a, "tests/test_core.py")
        self.assertEqual((f["file"]["test"], f["verdict"]["status"]), (True, "DORMANT"))
        self.assertIn("kind:          test file", explain(self.a, "tests/test_core.py"))

    def test_json_is_serialisable_and_carries_meta(self):
        doc = json.loads(json.dumps(why_json(self.a, "pkg/core.py")))
        self.assertEqual((doc["schema_version"], doc["kind"], doc["path"]), (1, "why", "pkg/core.py"))
        self.assertEqual(doc["meta"]["git"]["available"], True)
        for key in ("file", "verdict", "git", "owners", "graph", "advice"):
            self.assertIn(key, doc)

    def test_unknown_target(self):
        with self.assertRaises(TargetError):
            facts(self.a, "nope.py")


DEFINITIONS_TREE = {
    "pkg/__init__.py": "",
    "pkg/shapes.py": "def area(w, h):\n    return w * h\n\n\ndef perimeter(w, h):\n    return 2 * (w + h)\n\n\ndef _check(x):\n    return x\n\n\nclass Shape:\n    def draw(self):\n        return area(1, 1)\n",
    "pkg/use.py": "from pkg import shapes\n\n\ndef run():\n    return shapes.area(2, 3)\n",
    "tests/test_shapes.py": "from pkg import shapes\n\n\ndef test_area():\n    assert shapes.area(2, 3) == 6\n\n\ndef test_shape():\n    assert shapes.Shape().draw() == 1  # perimeter is only in this comment\n",
    "tests/test_use.py": "from pkg import use\n\n\ndef test_run():\n    assert use.run() == 6\n",
    "web/ops.js": "export function insert(x) { return x }\nexport function remove(x) { return x }\n",
    "web/ops.test.js": "import { insert } from './ops'\ntest('inserts', () => { expect(insert(1)).toBe(1) })\n",
    "web/broken.test.js": "import { remove } from './ops'\nconst s = `never closed\n",
    "lonely/__init__.py": "",
    "lonely/alone.py": "def solo():\n    return 1\n",
    "style.css": "body {}\n",
}


class DefinitionsTest(TempRepo):
    """`why` holds every definition of a code file against the tests that reach it: named in which, named in none,
    not searched; a test file and a file of another language say why there is nothing."""

    def setUp(self):
        super().setUp()
        write_tree(self.root, DEFINITIONS_TREE)
        self.a = analyze(self.root, config.load(self.root))

    def test_each_definition_names_the_reaching_tests_whose_code_uses_its_name(self):
        from tessri import modules

        d = facts(self.a, "pkg/shapes.py")["definitions"]
        self.assertEqual({k: v for k, v in d.items() if k != "items"}, {"available": True, "tests": 2, "unread": [], "named": 3, "unnamed": 1, "unsearched": 1})
        self.assertEqual(d["tests"], modules.impact(self.a, "pkg/shapes.py")["tests"]["files"])  # the same tests `impact` counts
        self.assertEqual(
            d["items"],
            [
                {"name": "area", "start": 1, "end": 2, "named_in": ["tests/test_shapes.py"]},
                {"name": "perimeter", "start": 5, "end": 6, "named_in": []},  # a comment is not code
                {"name": "_check", "start": 9, "end": 10, "named_in": None},  # private by convention: not searched
                {"name": "Shape", "start": 13, "end": 15, "named_in": ["tests/test_shapes.py"]},
                {"name": "Shape.draw", "start": 14, "end": 15, "named_in": ["tests/test_shapes.py"]},
            ],
        )
        self.assertIn("definitions:   5; named in a reaching test: 3; named in none: perimeter; not searched (too short, private or too common): _check", explain(self.a, "pkg/shapes.py"))

    def test_a_javascript_file_is_held_against_its_specs_and_a_spec_the_analyzer_could_not_read_reaches_nothing(self):
        d = facts(self.a, "web/ops.js")["definitions"]
        self.assertEqual((d["tests"], d["unread"]), (1, []))  # broken.test.js never closes its template: no edge from it, so it is not a reaching test
        self.assertEqual([(i["name"], i["named_in"]) for i in d["items"]], [("insert", ["web/ops.test.js"]), ("remove", [])])
        self.assertIn("definitions:   2; named in a reaching test: 1; named in none: remove", explain(self.a, "web/ops.js"))
        unread = {"available": True, "items": [{"name": "insert", "start": 1, "end": 1, "named_in": []}], "tests": 3, "unread": ["web/a.test.js", "web/b.test.js"], "named": 0, "unnamed": 1, "unsearched": 0}
        self.assertEqual(_definitions_text(unread), "1; named in a reaching test: 0; named in none: insert; 2 reaching tests could not be read: web/a.test.js, web/b.test.js")

    def test_no_reaching_test_says_so_instead_of_counting_names(self):
        d = facts(self.a, "lonely/alone.py")["definitions"]
        self.assertEqual((d["tests"], d["named"], d["unnamed"]), (0, 0, 1))
        self.assertIn("definitions:   1; no test reaches the file", explain(self.a, "lonely/alone.py"))
        self.assertNotIn("definitions:", explain(self.a, "pkg/__init__.py"))  # no definitions: no line, an empty list in the JSON
        self.assertEqual(facts(self.a, "pkg/__init__.py")["definitions"]["items"], [])

    def test_a_test_file_and_another_language_say_why_there_is_nothing(self):
        self.assertEqual(facts(self.a, "tests/test_shapes.py")["definitions"], {"available": False, "reason": "a test file: its definitions are not held against the tests"})
        self.assertNotIn("definitions:", explain(self.a, "tests/test_shapes.py"))
        self.assertEqual(facts(self.a, "style.css")["definitions"], {"available": False, "reason": "definitions are read for Python, JavaScript and TypeScript, not CSS"})
        self.assertNotIn("definitions:", explain(self.a, "style.css"))
        self.assertIn("definitions", json.loads(json.dumps(why_json(self.a, "pkg/shapes.py"))))


class WithoutGitTest(TempRepo):
    def test_no_history_means_no_git_and_no_owner_facts(self):
        write_tree(self.root, {"a.py": "import b\n", "b.py": "x = 1\n"})
        a = analyze(self.root, config.load(self.root))
        f = facts(a, "b.py")
        # Without entry points nothing is reached, so the verdict is ORPHAN; without history it has no git doubts.
        self.assertEqual((f["git"], f["owners"], f["verdict"]["status"], f["verdict"]["confidence"]), (None, None, "ORPHAN", "high"))
        text = explain(a, "b.py")
        self.assertNotIn("git:", text)
        self.assertNotIn("owners:", text)
        doc = why_json(a, "b.py")
        self.assertEqual(doc["meta"]["git"]["reason"], "not-a-repository")


class CliTest(Repo):
    def test_text_is_the_default(self):
        code, out = run_cli("why", "pkg/dead.py", "--repo", str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(out, explain(self.a, "pkg/dead.py") + "\n")

    def test_json(self):
        code, out = run_cli("why", "pkg/dead.py", "--repo", str(self.root), "--format", "json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual((doc["kind"], doc["verdict"]["status"], doc["meta"]["git"]["available"]), ("why", "ORPHAN", True))

    def test_out_file(self):
        target = self.root / "out" / "why.json"
        code, out = run_cli("why", "pkg/dead.py", "--repo", str(self.root), "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(target.read_text())["path"], "pkg/dead.py")

    def test_unknown_target_exits_2_without_output(self):
        code, out = run_cli("why", "nope.py", "--repo", str(self.root), "--format", "json")
        self.assertEqual((code, out), (2, ""))


if __name__ == "__main__":
    unittest.main()
