import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from helpers import TempRepo, git, write_tree
from tessri import config, since as sincemod, sinceview
from tessri.since import CheckError
from test_modules import run_cli

ALICE = ("Alice Adams", "alice@example.com")
BOB = ("Bob Brown", "bob@example.com")
CAROL = ("Carol Chen", "carol@example.com")

BASE = {
    "app/__init__.py": "",
    "app/main.py": "from core import engine\n\nif __name__ == '__main__':\n    engine.run()\n",
    "core/__init__.py": "",
    "core/engine.py": "from util import helpers\n\n\ndef run():\n    return helpers.go()\n",
    "util/__init__.py": "",
    "util/helpers.py": "def go():\n    return 1\n",
    "tests/test_engine.py": "from core import engine\n\n\ndef test_run():\n    assert engine.run()\n",
}

# a and b depend on each other; c stands apart
CYCLIC = {
    "a/__init__.py": "",
    "a/x.py": "from b import y\n\nif __name__ == '__main__':\n    print(y)\n",
    "b/__init__.py": "",
    "b/y.py": "from a import x\n",
    "c/__init__.py": "",
    "c/z.py": "VALUE = 1\n",
}


class Branchy(TempRepo):
    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")

    def commit(self, files=None, remove=(), days_ago=0, who=ALICE, message="change"):
        write_tree(self.root, files or {})
        for rel in remove:
            (self.root / rel).unlink()
        git(self.root, "add", "-A")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "--allow-empty", "-m", message, when=stamp, author=who)

    def check(self, since="HEAD", **settings):
        cfg = config.load(self.root)
        for key, value in settings.items():
            setattr(cfg, key, value)
        return sincemod.check(self.root, cfg, since, now=self.now)

    def kinds(self, result):
        return {(f["kind"], f["severity"]) for f in result["findings"]}

    def finding(self, result, finding_id):
        return next(f for f in result["findings"] if f["id"] == finding_id)


class NothingTest(Branchy):
    def test_a_clean_tree_has_nothing_to_compare(self):
        self.commit(BASE)
        r = self.check()
        self.assertEqual((r["summary"]["files"], r["summary"]["code_files"], r["findings"]), (0, 0, []))
        self.assertEqual(r["summary"]["findings"], {"info": 0, "warn": 0, "block": 0})
        self.assertIn("No code changed", sinceview.markdown(r))

    def test_a_change_to_docs_alone_has_no_structure_to_compare(self):
        self.commit(BASE)
        write_tree(self.root, {"README.md": "# hello\n"})
        r = self.check()
        self.assertEqual((r["summary"]["files"], r["summary"]["code_files"], r["summary"]["other_files"]), (1, 0, 1))
        self.assertEqual(r["findings"], [])

    def test_a_harmless_edit_finds_nothing(self):
        self.commit(BASE)
        write_tree(self.root, {"util/helpers.py": "def go():\n    return 2\n"})
        r = self.check()
        self.assertEqual((r["summary"]["code_files"], r["summary"]["modified"]), (1, 1))
        self.assertEqual(r["findings"], [])
        self.assertIn("No structural findings", sinceview.markdown(r))


class OrphanTest(Branchy):
    def test_a_new_file_nothing_reaches(self):
        self.commit(BASE)
        write_tree(self.root, {"core/unused.py": "VALUE = 1\n"})
        r = self.check()
        self.assertEqual(r["orphans"]["new"], [{"path": "core/unused.py", "how": "added", "code": 1}])
        f = self.finding(r, "new-orphan:added")
        self.assertEqual((f["severity"], f["files"], f["needs_human"]), ("warn", ["core/unused.py"], False))

    def test_a_dirty_tree_is_reported_as_one(self):
        self.commit(BASE)
        write_tree(self.root, {"core/unused.py": "VALUE = 1\n"})
        r = self.check()
        self.assertTrue(r["change"]["uncommitted"])
        self.assertIn("to the working tree", sinceview.markdown(r))

    def test_a_new_script_nothing_imports_is_only_a_note_because_scripts_are_run_by_hand(self):
        self.commit(BASE)
        write_tree(self.root, {"scripts/tidy.py": "VALUE = 1\n"})
        f = self.finding(self.check(), "new-orphan:added")
        self.assertEqual(f["severity"], "info")
        self.assertIn("often run by hand", f["detail"])
        write_tree(self.root, {"core/unused.py": "VALUE = 1\n"})  # one that is not a script makes it a warning again
        f = self.finding(self.check(), "new-orphan:added")
        self.assertEqual(f["severity"], "warn")
        self.assertIn("1 of them are under", f["detail"])

    def test_a_new_file_that_something_imports_is_fine(self):
        self.commit(BASE)
        write_tree(self.root, {"core/extra.py": "VALUE = 1\n", "core/engine.py": "from util import helpers\nfrom core import extra\n\n\ndef run():\n    return helpers.go() + extra.VALUE\n"})
        self.assertEqual(self.check()["orphans"]["new"], [])

    def test_cutting_the_last_link_strands_a_file_that_was_fine(self):
        self.commit(BASE)
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        r = self.check()
        self.assertEqual([(o["path"], o["how"], o["was_reached_from"], o["reached_kinds"]) for o in r["orphans"]["new"]], [("util/helpers.py", "stranded", ["core/engine.py"], {"core/engine.py": "import"})])
        f = self.finding(r, "new-orphan:stranded")
        self.assertIn("`util/helpers.py` was reached from `core/engine.py`", f["detail"])

    def test_a_stranded_file_says_what_kind_of_link_was_cut(self):
        base = {
            **BASE,
            "app/main.py": "from app import loader\nfrom core import engine\n\nif __name__ == '__main__':\n    engine.run()\n",
            "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n",
            "core/engine.py": "def run():\n    return 1\n",
        }
        self.commit(base)
        write_tree(self.root, {"app/loader.py": "def load():\n    return None\n"})  # the string was the last link to util/helpers.py
        r = self.check()
        rows = [(o["path"], o["how"], o["was_reached_from"], o["reached_kinds"]) for o in r["orphans"]["new"]]
        self.assertEqual(rows, [("util/helpers.py", "stranded", ["app/loader.py"], {"app/loader.py": "string"})])
        self.assertIn("`util/helpers.py` was reached from `app/loader.py` (string)", self.finding(r, "new-orphan:stranded")["detail"])

    def test_an_orphan_that_was_already_there_is_not_new(self):
        self.commit({**BASE, "core/old.py": "VALUE = 1\n"})
        write_tree(self.root, {"core/old.py": "VALUE = 2\n"})
        self.assertEqual(self.check()["orphans"], {"new": [], "resolved": []})

    def test_deleting_or_wiring_up_an_orphan_resolves_it(self):
        self.commit({**BASE, "core/old.py": "VALUE = 1\n", "core/odd.py": "VALUE = 2\n"})
        (self.root / "core/old.py").unlink()
        write_tree(self.root, {"core/engine.py": "from util import helpers\nfrom core import odd\n\n\ndef run():\n    return helpers.go() + odd.VALUE\n"})
        r = self.check()
        self.assertEqual(r["orphans"]["resolved"], [{"path": "core/odd.py", "how": "wired"}, {"path": "core/old.py", "how": "removed"}])
        f = self.finding(r, "orphan-resolved:all")
        self.assertEqual((f["severity"], f["detail"]), ("info", "1 deleted, 1 now reached."))


class DanglingTest(Branchy):
    def test_deleting_a_file_an_untouched_file_still_imports(self):
        self.commit(BASE)
        (self.root / "util/helpers.py").unlink()
        r = self.check()
        self.assertEqual(r["dangling_imports"], [{"deleted": "util/helpers.py", "importers": ["core/engine.py"]}])
        f = self.finding(r, "dangling-import:util/helpers.py")
        self.assertEqual((f["severity"], f["files"]), ("block", ["core/engine.py"]))
        self.assertEqual(r["summary"]["findings"]["block"], 1)

    def test_updating_the_importer_in_the_same_change_is_fine(self):
        self.commit(BASE)
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        self.assertEqual(self.check()["dangling_imports"], [])

    def test_a_moved_file_leaves_its_importers_dangling(self):
        self.commit(BASE)
        (self.root / "util/helpers.py").rename(self.root / "util/aid.py")
        r = self.check()
        self.assertEqual([d["deleted"] for d in r["dangling_imports"]], ["util/helpers.py"])

    def test_a_package_init_that_only_ran_on_the_way_is_not_an_import(self):
        base = {**BASE, "core/__init__.py": "VALUE = 1\n"}
        self.commit(base)
        (self.root / "core/__init__.py").unlink()  # app imports core.engine, which only runs core/__init__ as a side effect
        self.assertEqual(self.check()["dangling_imports"], [])

    def test_a_deleted_file_still_named_in_a_string_is_a_warning_for_a_person(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n"})
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})  # the importer is updated in the same change; the loader is not
        r = self.check()
        self.assertEqual(r["dangling_imports"], [])
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "app/loader.py", "kind": "string"}]}])
        f = self.finding(r, "dangling-reference:util/helpers.py")
        self.assertEqual((f["severity"], f["needs_human"], f["files"]), ("warn", True, ["app/loader.py"]))
        self.assertEqual(f["title"], "`util/helpers.py` was deleted but is still named in code")
        self.assertIn("`app/loader.py` (string)", f["detail"])
        self.assertIn("A person has to decide this.", sinceview.markdown(r))

    def test_a_moved_file_still_named_by_its_old_name(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n"})
        git(self.root, "mv", "util/helpers.py", "util/aid.py")
        write_tree(self.root, {"core/engine.py": "from util import aid\n\n\ndef run():\n    return aid.go()\n"})
        r = self.check()
        self.assertEqual(r["dangling_imports"], [])
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "app/loader.py", "kind": "string"}], "moved_to": "util/aid.py"}])
        self.assertEqual(self.finding(r, "dangling-reference:util/helpers.py")["title"], "`util/helpers.py` was moved to `util/aid.py` but is still named by its old name")

    def test_a_name_that_still_fits_the_moved_file_is_not_dangling(self):
        self.commit({**BASE, "app/loader.py": "PATH = 'helpers.py'\n"})
        (self.root / "lib").mkdir()
        git(self.root, "mv", "util/helpers.py", "lib/helpers.py")
        write_tree(self.root, {"lib/__init__.py": "", "core/engine.py": "from lib import helpers\n\n\ndef run():\n    return helpers.go()\n"})
        r = self.check()
        self.assertEqual((r["dangling_imports"], r["dangling_references"]), ([], []))

    def test_a_deleted_file_still_named_in_a_config_is_a_warning_with_no_decision_in_it(self):
        self.commit({**BASE, ".github/workflows/ci.yml": "jobs:\n  warm:\n    steps:\n      - run: python util/helpers.py\n"})
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        r = self.check()
        self.assertEqual(r["dangling_imports"], [])
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": ".github/workflows/ci.yml", "kind": "config"}]}])
        f = self.finding(r, "dangling-reference:util/helpers.py")
        self.assertEqual((f["severity"], f["needs_human"], f["files"]), ("warn", False, [".github/workflows/ci.yml"]))
        self.assertEqual(f["title"], "`util/helpers.py` was deleted but is still named in a config")
        self.assertIn("`.github/workflows/ci.yml` (config)", f["detail"])
        self.assertIn("wiring", f["detail"])
        self.assertEqual(f["action"], "Update the name in the same change, or restore the file.")

    def test_a_deleted_file_named_only_in_documentation_is_a_note_and_a_changelog_is_left_alone(self):
        self.commit({**BASE, "README.md": "Run `python util/helpers.py` first.\n", "CHANGELOG.md": "## 0.1\n\n- added util/helpers.py\n"})
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        r = self.check()
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "README.md", "kind": "doc"}]}])
        f = self.finding(r, "dangling-reference:util/helpers.py")
        self.assertEqual((f["severity"], f["needs_human"], f["files"]), ("info", False, ["README.md"]))
        self.assertEqual(f["title"], "`util/helpers.py` was deleted but is still named in documentation")
        self.assertEqual(f["action"], "Update the documentation in the same change.")
        self.assertNotIn("A person has to decide this.", sinceview.markdown(r))

    def test_a_file_named_in_a_config_and_in_code_lists_the_config_first(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n", "Makefile": "warm:\n\tpython util/helpers.py\n"})
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        r = self.check()
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "Makefile", "kind": "config"}, {"path": "app/loader.py", "kind": "string"}]}])
        f = self.finding(r, "dangling-reference:util/helpers.py")
        self.assertEqual((f["severity"], f["needs_human"], f["files"]), ("warn", True, ["Makefile", "app/loader.py"]))
        self.assertEqual(f["title"], "`util/helpers.py` was deleted but is still named in a config and in code")
        self.assertIn("so check it first", f["action"])

    def test_a_moved_file_whose_old_path_a_config_still_names(self):
        self.commit({**BASE, "Makefile": "warm:\n\tpython util/helpers.py\n"})
        git(self.root, "mv", "util/helpers.py", "util/aid.py")
        write_tree(self.root, {"core/engine.py": "from util import aid\n\n\ndef run():\n    return aid.go()\n"})
        r = self.check()
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "Makefile", "kind": "config"}], "moved_to": "util/aid.py"}])
        self.assertEqual(self.finding(r, "dangling-reference:util/helpers.py")["severity"], "warn")

    def test_a_module_turned_into_a_package_keeps_its_name(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n", "Makefile": "warm:\n\tpython util/helpers.py\n"})
        (self.root / "util/helpers").mkdir()
        git(self.root, "mv", "util/helpers.py", "util/helpers/impl.py")
        write_tree(self.root, {"util/helpers/__init__.py": "from .impl import go\n"})
        r = self.check()
        self.assertEqual(r["dangling_imports"], [])  # `from util import helpers` in core/engine.py now reaches the package
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "Makefile", "kind": "config"}], "moved_to": "util/helpers/impl.py"}])  # the script path is gone; the dotted name is not

    def test_a_package_initializer_run_on_the_way_to_a_module_that_stays_is_not_dangling(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n", "pyproject.toml": "[project]\nname = 'demo'\n\n[project.scripts]\ngo = 'util.helpers:go'\n"})
        (self.root / "util/__init__.py").unlink()  # util/ is a namespace package now; util.helpers still resolves
        r = self.check()
        self.assertEqual((r["dangling_imports"], r["dangling_references"]), ([], []))

    def test_a_deleted_package_is_reported_through_its_module_not_its_initializer(self):
        self.commit({**BASE, "app/loader.py": "import importlib\n\n\ndef load():\n    return importlib.import_module('util.helpers')\n", "pyproject.toml": "[project]\nname = 'demo'\n\n[project.scripts]\ngo = 'util.helpers:go'\n"})
        (self.root / "util/__init__.py").unlink()
        (self.root / "util/helpers.py").unlink()
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        r = self.check()
        self.assertEqual(r["dangling_references"], [{"deleted": "util/helpers.py", "referrers": [{"path": "pyproject.toml", "kind": "config"}, {"path": "app/loader.py", "kind": "string"}]}])  # one row, for the module the name names


class CycleTest(Branchy):
    def test_a_dependency_that_closes_a_loop(self):
        self.commit(BASE)
        write_tree(self.root, {"util/helpers.py": "from core import engine\n\n\ndef go():\n    return engine\n"})
        r = self.check()
        self.assertEqual([c["modules"] for c in r["cycles"]["new"]], [["core", "util"]])
        self.assertEqual([(e["from"], e["to"]) for e in r["cycles"]["new"][0]["closing"]], [("util", "core")])
        self.assertEqual([(e["from"], e["to"], e["against_flow"]) for e in r["dependencies"]["new"]], [("util", "core", True)])
        f = self.finding(r, "new-cycle:core+util")
        self.assertEqual(f["severity"], "warn")
        self.assertIn("`util` → `core`", f["detail"])

    def test_a_cycle_that_was_already_there_is_not_new(self):
        self.commit({**BASE, "util/helpers.py": "from core import engine\n\n\ndef go():\n    return engine\n"})
        write_tree(self.root, {"util/helpers.py": "from core import engine\n\n\ndef go():\n    return engine.run\n"})
        r = self.check()
        self.assertEqual((r["cycles"], r["dependencies"]["new"]), ({"new": [], "grown": [], "resolved": []}, []))

    def test_a_third_module_drawn_into_a_cycle(self):
        self.commit(CYCLIC)
        write_tree(self.root, {"b/y.py": "from a import x\nfrom c import z\n", "c/z.py": "from a import x\n\nVALUE = 1\n"})
        r = self.check()
        self.assertEqual(r["cycles"]["new"], [])
        grown = r["cycles"]["grown"]
        self.assertEqual([(g["modules"], g["added_modules"]) for g in grown], [(["a", "b", "c"], ["c"])])
        self.assertTrue(any(f["kind"] == "cycle-grew" for f in r["findings"]))

    def test_removing_the_back_edge_resolves_a_cycle(self):
        self.commit(CYCLIC)
        write_tree(self.root, {"b/y.py": "VALUE = 1\n"})
        r = self.check()
        self.assertEqual(r["cycles"]["resolved"], [{"modules": ["a", "b"]}])
        self.assertEqual([f["kind"] for f in r["findings"]], ["cycle-resolved"])

    def test_new_dependencies_that_close_no_loop_are_listed_but_calm(self):
        self.commit({**BASE, "extra/__init__.py": "", "extra/e.py": "VALUE = 1\n"})
        write_tree(self.root, {"core/engine.py": "from util import helpers\nfrom extra import e\n\n\ndef run():\n    return helpers.go() + e.VALUE\n"})
        r = self.check()
        self.assertEqual([(e["from"], e["to"], e["against_flow"]) for e in r["dependencies"]["new"]], [("core", "extra", False)])
        self.assertIn(("new-dependency", "info"), self.kinds(r))
        self.assertEqual({sev for _, sev in self.kinds(r)}, {"info"})  # nothing that needs attention

    def test_removed_dependencies_are_listed(self):
        self.commit(BASE)
        write_tree(self.root, {"core/engine.py": "def run():\n    return 1\n"})
        self.assertEqual(self.check()["dependencies"]["removed"], [{"from": "core", "to": "util"}])


class OwnerTest(Branchy):
    def history(self):
        self.commit({"legacy/__init__.py": "", "legacy/old.py": "def old():\n    return 1\n"}, days_ago=400, who=BOB)
        self.commit(BASE, days_ago=5, who=ALICE)

    def test_changed_code_nobody_active_maintains(self):
        self.history()
        write_tree(self.root, {"legacy/old.py": "def old():\n    return 2\n"})
        r = self.check()
        self.assertEqual([(u["path"], u["last_owner"]) for u in r["unowned"]], [("legacy/old.py", "Bob Brown")])
        self.assertIn(r["unowned"][0]["owner_idle_days"], (399, 400))
        f = self.finding(r, "no-active-owner:changed")
        self.assertEqual((f["severity"], f["needs_human"], f["files"]), ("warn", True, ["legacy/old.py"]))
        self.assertIn("A person has to decide this.", sinceview.markdown(r))

    def test_the_authors_own_commits_do_not_make_them_the_owner(self):
        self.history()
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"legacy/old.py": "def old():\n    return 2\n"}, days_ago=0, who=CAROL, message="touch the old code")
        r = self.check("main")
        self.assertFalse(r["change"]["uncommitted"])
        self.assertEqual([u["path"] for u in r["unowned"]], ["legacy/old.py"])

    def test_code_somebody_active_maintains_is_not_flagged(self):
        self.history()
        write_tree(self.root, {"util/helpers.py": "def go():\n    return 2\n"})
        self.assertEqual(self.check()["unowned"], [])

    def test_deleting_unowned_code_is_not_a_finding(self):
        self.history()
        (self.root / "legacy/old.py").unlink()
        self.assertEqual(self.check()["unowned"], [])

    def test_a_new_file_has_no_history_to_be_unowned_in(self):
        self.history()
        write_tree(self.root, {"legacy/new.py": "VALUE = 1\n"})
        self.assertEqual(self.check()["unowned"], [])


class SplitTest(Branchy):
    def test_both_sides_are_cut_into_modules_the_same_way(self):
        """20 files stay one module; a 21st makes the split by size kick in. Compared with each side's own split,
        the dependency between the two halves would look new."""
        files = {f"pkg/one/f{i}.py": f"from pkg.two import g{i}\n" for i in range(10)} | {f"pkg/two/g{i}.py": "VALUE = 1\n" for i in range(10)}
        files["main.py"] = "from pkg.one import f0\n\nif __name__ == '__main__':\n    print(f0)\n"
        files = {k: v for k, v in files.items() if k != "main.py"}  # exactly 20 files
        self.commit(files)
        write_tree(self.root, {"pkg/one/extra.py": "VALUE = 2\n"})
        r = self.check()
        self.assertEqual(r["dependencies"]["new"], [])
        self.assertEqual(r["cycles"], {"new": [], "grown": [], "resolved": []})


    def test_a_file_that_disappears_does_not_move_the_split_under_the_comparison(self):
        files = {f"pkg/one/f{i}.py": f"from pkg.two import g{i}\n" for i in range(11)} | {f"pkg/two/g{i}.py": "VALUE = 1\n" for i in range(11)}
        files = {k: v for k, v in files.items() if k != "pkg/one/f10.py" and k != "pkg/two/g10.py"} | {"pkg/two/g10.py": "VALUE = 1\n"}  # 21 files
        self.commit(files)
        (self.root / "pkg/two/g10.py").unlink()  # 20 files: on its own the head would no longer be split
        r = self.check()
        self.assertEqual((r["dependencies"]["new"], r["dependencies"]["removed"]), ([], []))


class BaseTest(Branchy):
    def test_the_base_is_where_the_branch_left_main(self):
        self.commit(BASE)
        fork = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout.strip()
        git(self.root, "checkout", "-q", "-b", "feature")
        git(self.root, "checkout", "-q", "main")
        self.commit({"main_only.py": "VALUE = 1\n"}, message="main moves on")
        git(self.root, "checkout", "-q", "feature")
        self.commit({"core/unused.py": "VALUE = 1\n"}, message="the feature")
        r = self.check("main")
        self.assertEqual(r["change"]["base"], fork[:9])
        self.assertEqual([f["path"] for f in r["changed_files"]], ["core/unused.py"])  # not main_only.py, which is not part of this branch

    def test_a_committed_branch_with_a_clean_tree(self):
        self.commit(BASE)
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"core/unused.py": "VALUE = 1\n"})
        r = self.check("main")
        self.assertEqual((r["change"]["uncommitted"], r["summary"]["added"]), (False, 1))
        self.assertEqual(r["orphans"]["new"][0]["path"], "core/unused.py")
        self.assertIn("to " + r["change"]["head"], sinceview.markdown(r))

    def test_staged_and_untracked_files_are_both_part_of_the_change(self):
        self.commit(BASE)
        write_tree(self.root, {"core/staged.py": "A = 1\n", "core/loose.py": "B = 2\n"})
        git(self.root, "add", "core/staged.py")
        r = self.check()
        self.assertEqual({(f["path"], f["change"]) for f in r["changed_files"]}, {("core/staged.py", "added"), ("core/loose.py", "added")})

    def test_files_matching_exclude_are_ignored(self):
        self.commit(BASE)
        write_tree(self.root, {"vendor/lib.py": "VALUE = 1\n", "core/unused.py": "VALUE = 2\n"})
        r = self.check(exclude=["vendor/*"])
        self.assertEqual([f["path"] for f in r["changed_files"]], ["core/unused.py"])

    def test_the_project_may_live_in_a_subdirectory(self):
        self.commit({f"proj/{k}": v for k, v in BASE.items()} | {"elsewhere/x.py": "VALUE = 1\n"})
        write_tree(self.root, {"proj/core/unused.py": "VALUE = 1\n", "elsewhere/x.py": "VALUE = 2\n"})
        cfg = config.load(self.root / "proj")
        r = sincemod.check(self.root / "proj", cfg, "HEAD", now=self.now)
        self.assertEqual([f["path"] for f in r["changed_files"]], ["core/unused.py"])
        self.assertEqual([o["path"] for o in r["orphans"]["new"]], ["core/unused.py"])

    def test_the_base_may_not_have_had_the_project_yet(self):
        self.commit({"README.md": "# x\n"})
        write_tree(self.root, {"proj/core/lib.py": "VALUE = 1\n"})
        r = sincemod.check(self.root / "proj", config.load(self.root), "HEAD", now=self.now) if (self.root / "proj").is_dir() else None
        self.assertEqual([o["path"] for o in r["orphans"]["new"]], ["core/lib.py"])


class ExtractTest(Branchy):
    def test_export_ignore_does_not_hide_files_from_the_base(self):
        self.commit({**BASE, ".gitattributes": "core/hidden.py export-ignore\n", "core/hidden.py": "VALUE = 1\n"})
        dest = self.root.parent / (self.root.name + "-base")
        dest.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(dest, ignore_errors=True))
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout.strip()
        sincemod.extract_tree(self.root, base, "", dest, [])
        self.assertTrue((dest / "core/hidden.py").is_file())
        self.assertEqual((dest / "util/helpers.py").read_text(), BASE["util/helpers.py"])

    def test_large_files_links_and_skipped_paths_are_not_written(self):
        big = "x = 1\n" * 400_000  # over the size the analysis reads
        self.commit({**BASE, "big.py": big, "vendor/lib.py": "VALUE = 1\n"})
        (self.root / "link.py").symlink_to("core/engine.py")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "link")
        dest = self.root.parent / (self.root.name + "-base2")
        dest.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(dest, ignore_errors=True))
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout.strip()
        sincemod.extract_tree(self.root, base, "", dest, ["vendor/*"])
        written = {str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()}
        self.assertNotIn("big.py", written)
        self.assertNotIn("link.py", written)
        self.assertNotIn("vendor/lib.py", written)
        self.assertIn("core/engine.py", written)


class ErrorTest(TempRepo):
    def run_check(self, root, since="HEAD"):
        return sincemod.check(root, config.load(root), since)

    def test_a_directory_without_git(self):
        write_tree(self.root, BASE)
        with self.assertRaisesRegex(CheckError, "needs a git repository"):
            self.run_check(self.root)

    def test_an_unknown_ref(self):
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, BASE)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        with self.assertRaisesRegex(CheckError, "`nope` is not a commit, branch or tag"):
            self.run_check(self.root, "nope")

    def test_a_repository_without_commits(self):
        git(self.root, "init", "-q", "-b", "main")
        with self.assertRaises(CheckError):
            self.run_check(self.root)


class GateTest(unittest.TestCase):
    def result(self, *severities):
        return {"findings": [{"severity": s} for s in severities]}

    def test_fail_on_picks_the_severity_that_stops_the_merge(self):
        for severities, fail_on, expected in (
            ((), "warn", False),
            (("info",), "warn", False),
            (("warn",), "warn", True),
            (("warn",), "block", False),
            (("info", "block"), "block", True),
            (("block",), "never", False),
            (("block", "warn"), "warn", True),
        ):
            self.assertEqual(sincemod.failing(self.result(*severities), fail_on), expected, (severities, fail_on))


class OutputTest(Branchy):
    def test_the_result_is_plain_json_and_never_carries_an_address(self):
        self.commit(BASE, who=ALICE)
        write_tree(self.root, {"util/helpers.py": "from core import engine\n\n\ndef go():\n    return engine\n", "core/unused.py": "V = 1\n"})
        r = self.check()
        text = json.dumps(r)
        self.assertNotIn("@example.com", text)
        self.assertEqual(r["kind"], "change-check")
        self.assertEqual(r["summary"]["findings"], {"info": 1, "warn": 2, "block": 0})
        severities = [f["severity"] for f in r["findings"]]
        self.assertEqual(severities, sorted(severities, key=lambda s: ("block", "warn", "info").index(s)))  # the serious ones first

    def test_serious_findings_come_before_calm_ones_whatever_order_they_were_found_in(self):
        BaseTestHistory = OwnerTest.history
        BaseTestHistory(self)
        write_tree(self.root, {"core/engine.py": "from util import helpers\nfrom legacy import old\n\n\ndef run():\n    return helpers.go() + old.old()\n", "legacy/old.py": "def old():\n    return 2\n"})
        r = self.check()
        self.assertEqual([f["severity"] for f in r["findings"]], ["warn", "info", "info"])
        self.assertEqual(r["findings"][0]["kind"], "no-active-owner")

    def test_markdown_names_the_findings_and_what_to_do(self):
        self.commit(BASE)
        (self.root / "util/helpers.py").unlink()
        text = sinceview.markdown(self.check())
        for want in ("# Change check:", "**1 block", "`util/helpers.py` was deleted but is still imported", "Files: `core/engine.py`", "Do: Restore the file", "## Read this with care"):
            self.assertIn(want, text)


class CliTest(Branchy):
    def test_markdown_by_default_and_json_on_request(self):
        self.commit(BASE)
        write_tree(self.root, {"core/unused.py": "VALUE = 1\n"})
        code, out, _ = run_cli("check", "--repo", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("# Change check:", out)
        code, out, _ = run_cli("check", "--repo", str(self.root), "--format", "json")
        self.assertEqual((code, json.loads(out)["kind"]), (0, "change-check"))

    def test_fail_on_turns_findings_into_an_exit_code(self):
        self.commit(BASE)
        write_tree(self.root, {"core/unused.py": "VALUE = 1\n"})  # a warning
        args = ("check", "--repo", str(self.root))
        self.assertEqual(run_cli(*args)[0], 0)
        self.assertEqual(run_cli(*args, "--fail-on", "never")[0], 0)
        self.assertEqual(run_cli(*args, "--fail-on", "block")[0], 0)
        self.assertEqual(run_cli(*args, "--fail-on", "warn")[0], 1)
        out = run_cli(*args, "--fail-on", "warn")[1]
        self.assertIn("**warn**", out)  # the report is still printed

    def test_a_deleted_file_still_imported_fails_even_on_block(self):
        self.commit(BASE)
        (self.root / "util/helpers.py").unlink()
        self.assertEqual(run_cli("check", "--repo", str(self.root), "--fail-on", "block")[0], 1)

    def test_since_names_the_base(self):
        self.commit(BASE)
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"core/unused.py": "VALUE = 1\n"})
        code, out, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "json", "--fail-on", "warn")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["change"]["since"], "main")
        code, out, _ = run_cli("check", "--repo", str(self.root), "--format", "json", "--fail-on", "warn")  # without --since: the same, main being the default branch
        self.assertEqual((code, json.loads(out)["change"]["since"]), (1, "main"))
        self.assertEqual(run_cli("check", "--repo", str(self.root), "--since", "HEAD", "--fail-on", "warn")[0], 0)  # nothing uncommitted

    def test_the_result_can_be_written_to_a_file(self):
        self.commit(BASE)
        target = self.root / "out" / "check.json"
        code, out, err = run_cli("check", "--repo", str(self.root), "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("wrote", err)
        self.assertEqual(json.loads(target.read_text())["summary"]["files"], 0)

    def test_errors_are_reported_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as plain:
            code, out, err = run_cli("check", "--repo", plain)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("needs a git repository", err)
        code, _, err = run_cli("check", "--repo", str(self.root))  # a repository that has no commits yet
        self.assertEqual(code, 2)
        self.assertIn("no commits yet", err)
        self.commit(BASE)
        code, _, err = run_cli("check", "--repo", str(self.root), "--since", "nope")
        self.assertEqual(code, 2)
        self.assertIn("`nope` is not a commit", err)
        self.assertEqual(run_cli("check", "--repo", str(self.root), "--fail-on", "sometimes")[0], 2)

    def test_the_exclude_flag_applies(self):
        self.commit(BASE)
        write_tree(self.root, {"vendor/lib.py": "VALUE = 1\n"})
        out = run_cli("check", "--repo", str(self.root), "--format", "json", "--exclude", "vendor/*")[1]
        self.assertEqual(json.loads(out)["summary"]["files"], 0)


class DefaultSinceTest(TempRepo):
    """Without `--since`, the change is judged against the default branch: the one the remote declares, else the
    usual names with the remote-tracking branch first, else HEAD."""

    def test_the_remote_declares_it_else_the_usual_names_else_head(self):
        upstream = self.root / "upstream"
        upstream.mkdir()
        git(upstream, "init", "-q", "-b", "trunk")
        write_tree(upstream, {"a.py": "x = 1\n"})
        git(upstream, "add", ".")
        git(upstream, "commit", "-qm", "base")
        clone = self.root / "clone"
        git(self.root, "clone", "-q", str(upstream), str(clone))
        self.assertEqual(sincemod.default_since(clone), "origin/trunk")  # what the clone's origin/HEAD points at
        git(clone, "remote", "set-head", "origin", "-d")
        self.assertEqual(sincemod.default_since(clone), "HEAD")  # trunk is not a usual name, so only uncommitted work
        git(clone, "branch", "main")
        self.assertEqual(sincemod.default_since(clone), "main")
        git(clone, "update-ref", "refs/remotes/origin/master", "HEAD")
        self.assertEqual(sincemod.default_since(clone), "origin/master")  # a remote-tracking branch before a local one
        self.assertEqual(sincemod.default_since(upstream), "HEAD")
        self.assertEqual(sincemod.default_since(self.root), "HEAD")  # not a repository: resolving the base says so
        with self.assertRaises(CheckError):
            sincemod.check(self.root, config.load(self.root))

    def test_the_commands_use_it(self):
        upstream = self.root / "upstream"
        upstream.mkdir()
        git(upstream, "init", "-q", "-b", "main")
        write_tree(upstream, {"a.py": "x = 1\n"})
        git(upstream, "add", ".")
        git(upstream, "commit", "-qm", "base")
        clone = self.root / "clone"
        git(self.root, "clone", "-q", str(upstream), str(clone))
        git(clone, "checkout", "-qb", "feature")
        write_tree(clone, {"b.py": "import a\n"})
        git(clone, "add", ".")
        git(clone, "commit", "-qm", "feat: b")
        r = sincemod.check(clone, config.load(clone))
        self.assertEqual((r["change"]["since"], r["change"]["uncommitted"], r["summary"]["added"]), ("origin/main", False, 1))
        self.assertIn("`origin/main` (", sinceview.markdown(r))
        code, out, _ = run_cli("brief", "--repo", str(clone), "--format", "json")
        self.assertEqual((code, json.loads(out)["change"]["since"]), (0, "origin/main"))
        code, out, _ = run_cli("check", "--repo", str(clone), "--since", "HEAD", "--format", "json")
        self.assertEqual((code, json.loads(out)["summary"]["files"]), (0, 0))  # HEAD still means the uncommitted work alone


if __name__ == "__main__":
    unittest.main()
