"""A name found in a string or a config names a file only when it names exactly one: a bare `utils.py` in a repository
with several says nothing about any of them, and the bare `__init__.py` or `__main__.py` never names a file. An
`entry` the user wrote is taken to mean every file it fits."""

import unittest

from helpers import TempRepo, write_tree

from tessri import config
from tessri.analyze import analyze
from tessri.report import build_report
from tessri.textrefs import PathIndex

FILES = ["pkg/utils.py", "pkg/sub/utils.py", "pkg/__init__.py", "pkg/sub/__init__.py", "pkg/__main__.py", "scripts/run.py", "setup.py", "tools/setup.py"]


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.index = PathIndex(FILES)

    def test_a_unique_suffix_names_the_file(self):
        self.assertEqual(self.index.resolve("run.py"), {"scripts/run.py"})
        self.assertEqual(self.index.resolve("./scripts/run.py"), {"scripts/run.py"})
        self.assertEqual(self.index.resolve("sub/utils.py"), {"pkg/sub/utils.py"})
        self.assertEqual(self.index.ambiguous, {})

    def test_a_shared_suffix_names_nothing_and_is_recorded(self):
        self.assertEqual(self.index.resolve("utils.py"), set())
        self.assertEqual(self.index.ambiguous, {"utils.py": 2})

    def test_an_exact_path_wins_over_namesakes(self):
        self.assertEqual(self.index.resolve("setup.py"), {"setup.py"})  # the root file, not tools/setup.py as well
        self.assertEqual(self.index.resolve("tools/setup.py"), {"tools/setup.py"})

    def test_bare_package_names_never_name_a_file(self):
        self.assertEqual(self.index.resolve("__main__.py"), set())  # unique in FILES, still not a reference
        self.assertEqual(self.index.resolve("__init__.py"), set())
        self.assertEqual(self.index.resolve("pkg/__main__.py"), {"pkg/__main__.py"})  # with a directory it is a path
        self.assertEqual(self.index.ambiguous, {})

    def test_a_caller_may_ask_for_every_match(self):
        self.assertEqual(self.index.resolve("utils.py", allow_many=True), {"pkg/utils.py", "pkg/sub/utils.py"})
        self.assertEqual(self.index.ambiguous, {})


class ReachabilityTest(TempRepo):
    """Two files called `utils.py`, a CI file that names `utils.py`, and nothing else reaching either."""

    def setUp(self):
        super().setUp()
        write_tree(
            self.root,
            {
                "pkg/__init__.py": "",
                "pkg/utils.py": "def a():\n    return 1\n",
                "pkg/sub/__init__.py": "",
                "pkg/sub/utils.py": "def b():\n    return 2\n",
                "pkg/main.py": "print('__main__.py')\n",
                ".github/workflows/ci.yml": "run: python utils.py\n",
                "main.py": "import pkg.main\n\nif __name__ == '__main__':\n    pkg.main\n",
            },
        )

    def scan(self, **settings):
        cfg = config.load(self.root)
        for key, value in settings.items():
            setattr(cfg, key, value)
        return analyze(self.root, cfg)

    def test_a_shared_name_in_a_config_reaches_nothing(self):
        a = self.scan()
        self.assertEqual({p for p in a.records if a.records[p].status == "ORPHAN"}, {"pkg/utils.py", "pkg/sub/utils.py"})
        self.assertNotIn("pkg/utils.py", a.graph.config_refs)

    def test_an_entry_the_user_wrote_means_every_match(self):
        a = self.scan(entry=["utils.py"])
        self.assertEqual({p for p in a.records if a.records[p].status == "ORPHAN"}, set())
        self.assertEqual(a.graph.roots["pkg/sub/utils.py"], ["entry: utils.py"])

    def test_the_report_says_which_names_were_not_resolved(self):
        a = self.scan()
        self.assertEqual(a.graph.ambiguous, {"utils.py": 2})
        caveat = [c for c in build_report(a)["caveats"] if "several files" in c]
        self.assertEqual(len(caveat), 1)
        self.assertIn("`utils.py` (2)", caveat[0])
        self.assertIn("`entry`", caveat[0])
        self.assertEqual(self.scan(entry=["utils.py"]).graph.ambiguous, {"utils.py": 2})  # the config reference is still ambiguous; the entry is not

    def test_a_shared_name_in_code_is_listed_with_the_config_ones(self):
        (self.root / ".github/workflows/ci.yml").unlink()
        write_tree(self.root, {"pkg/loader.py": "FILES = ['utils.py', 'sub/utils.py']\n"})
        a = self.scan()
        self.assertEqual(a.graph.ambiguous, {"utils.py": 2})  # recorded by the Python analyzer; no config names it now
        self.assertEqual(a.graph.edges.get("pkg/loader.py", set()), {"pkg/sub/utils.py"})  # the suffix that fits one file names it; the shared one names none
        self.assertIn("in configs, scripts or code", [c for c in build_report(a)["caveats"] if "several files" in c][0])

    def test_a_bare_package_file_name_in_code_makes_no_edge(self):
        a = self.scan()
        self.assertNotIn("pkg/__main__.py", a.graph.edges.get("pkg/main.py", set()))
        self.assertEqual(a.graph.kind("pkg/main.py", "pkg/__main__.py"), "unknown")  # no edge, so no kind


if __name__ == "__main__":
    unittest.main()
