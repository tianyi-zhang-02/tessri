"""The cache: the store itself, and a warm run giving the same analysis as a cold one."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempRepo, git, write_tree

from tessri import cache, cli, config, since
from tessri.analyze import analyze
from tessri.cache import KEEP_DAYS, REFRESH_DAYS, Store

DAY = 86400.0


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "repo.json"

    def test_round_trip(self):
        store = Store(self.path, now=1_000 * DAY)
        self.assertIsNone(store.get("python/1", "abc"))
        self.assertEqual((store.hits, store.misses), (0, 1))
        store.put("python/1", "abc", {"x": [1, 2]})
        self.assertTrue(store.save())
        again = Store(self.path, now=1_000 * DAY)
        self.assertEqual(again.get("python/1", "abc"), {"x": [1, 2]})
        self.assertEqual((again.hits, again.misses), (1, 0))
        self.assertFalse(again.save())  # nothing new and nothing stale: the file is left alone

    def test_prunes_what_no_run_used_and_keeps_what_one_did(self):
        store = Store(self.path, now=1_000 * DAY)
        store.put("n", "a", 1)
        store.put("n", "b", 2)
        store.save()
        later = Store(self.path, now=(1_000 + KEEP_DAYS + 1) * DAY)
        self.assertEqual(later.get("n", "a"), 1)  # used today, so it stays
        later.put("n", "c", 3)
        self.assertTrue(later.save())
        final = Store(self.path, now=(1_000 + KEEP_DAYS + 1) * DAY)
        self.assertEqual(final.get("n", "a"), 1)
        self.assertIsNone(final.get("n", "b"))
        self.assertEqual(final.get("n", "c"), 3)

    def test_a_run_that_only_read_still_refreshes_old_marks(self):
        store = Store(self.path, now=1_000 * DAY)
        store.put("n", "a", 1)
        store.save()
        soon = Store(self.path, now=(1_000 + REFRESH_DAYS - 1) * DAY)
        soon.get("n", "a")
        self.assertFalse(soon.save())
        later = Store(self.path, now=(1_000 + REFRESH_DAYS + 1) * DAY)
        later.get("n", "a")
        self.assertTrue(later.save())
        self.assertEqual(json.loads(self.path.read_text())["entries"]["n:a"]["t"], 1_000 + REFRESH_DAYS + 1)

    def test_a_file_that_is_not_ours_is_started_over(self):
        self.path.write_text("not json at all")
        store = Store(self.path)
        self.assertIsNone(store.get("n", "a"))
        store.put("n", "a", 1)
        self.assertTrue(store.save())
        self.assertEqual(Store(self.path).get("n", "a"), 1)
        other = {"format": cache.FORMAT, "version": "0.0.0", "entries": {"n:a": {"t": Store(None).day, "v": 1}}}
        self.path.write_text(json.dumps(other))
        self.assertIsNone(Store(self.path).get("n", "a"))  # another version of the package wrote it

    def test_in_memory_without_a_path(self):
        store = Store(None)
        store.put("n", "a", 1)
        self.assertEqual(store.get("n", "a"), 1)
        self.assertFalse(store.save())

    def test_a_save_that_fails_costs_nothing(self):
        store = Store(self.path / "not-a-directory" / "x.json")
        store.put("n", "a", 1)
        self.path.write_text("")  # the parent is now a file, so the directory cannot be made
        self.assertFalse(store.save())
        self.assertEqual(store.get("n", "a"), 1)

    def test_the_directory_follows_the_environment(self):
        with mock.patch.dict(os.environ, {"TESSRI_CACHE_DIR": "/given/here"}):
            self.assertEqual(cache.directory(), Path("/given/here"))
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg"}, clear=False):
            os.environ.pop("TESSRI_CACHE_DIR", None)
            self.assertEqual(cache.directory(), Path("/xdg/tessri"))

    def test_digest(self):
        self.assertNotEqual(cache.digest("a"), cache.digest("b"))
        self.assertEqual(len(cache.digest("")), 40)
        self.assertEqual(cache.digest("x"), cache.digest("x"))


class RepositoryKeyTest(TempRepo):
    def test_worktrees_share_a_key_and_strangers_do_not(self):
        write_tree(self.root, {"a.py": "x = 1\n"})
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "one")
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        wt = Path(other.name) / "wt"
        git(self.root, "worktree", "add", "-q", "--detach", str(wt))
        self.addCleanup(lambda: git(self.root, "worktree", "remove", "--force", str(wt)))
        self.assertEqual(cache.repository_key(self.root), cache.repository_key(wt))
        self.assertNotEqual(cache.repository_key(self.root), cache.repository_key(Path(other.name)))


FILES = {
    "pkg/__init__.py": '"""The package."""\n',
    "pkg/core.py": 'import os\nfrom pkg import util\n\n\ndef run():\n    """Run it."""\n    return util.helper("pkg.ext.a")\n',
    "pkg/util.py": "def helper(name):\n    return name\n",
    "pkg/plugins.py": 'from importlib import import_module\n\nfor name in ["a"]:\n    import_module(f"pkg.ext.{name}")\n',
    "pkg/ext/__init__.py": "",
    "pkg/ext/a.py": "VALUE = 1\n",
    "pkg/broken.py": "def (:\n",
    "app.js": "import { lib } from './lib.js';\nconsole.log(lib);\n",
    "lib.js": "export const lib = 1;\n",
    "index.html": '<html><script src="./app.js"></script><p>see pkg/util.py</p></html>\n',
    "config.yaml": "target: pkg.core.run\n",
    "pyproject.toml": '[project]\nname = "demo"\nversion = "0"\n[project.scripts]\ndemo = "pkg.plugins:main"\n',
    "docs/readme.md": "The core is pkg/core.py.\n",
}


class WarmRunTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, FILES)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "one")
        self.now = time.time() + 60
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "store.json"

    def analysis(self, store: Store | None):
        cfg = config.Config()
        cfg.store = store
        return analyze(self.root, cfg, now=self.now)

    @staticmethod
    def shape(a) -> dict:
        g = a.graph
        return {
            "records": {p: dataclasses.asdict(r) for p, r in a.records.items()},
            "edges": g.edges, "indirect": g.indirect, "roots": g.roots, "tests": g.tests, "provenance": g.provenance,
            "config_refs": dict(g.config_refs), "doc_refs": dict(g.doc_refs), "unparsed": a.unparsed, "analyzers": a.analyzers,
        }

    def test_a_warm_run_gives_the_cold_run_back(self):
        cold = Store(self.path, now=self.now)
        first = self.analysis(cold)
        self.assertEqual(cold.hits, 0)
        self.assertGreater(cold.misses, 0)
        self.assertTrue(self.path.is_file())  # `analyze` saved it
        warm = Store(self.path, now=self.now)
        second = self.analysis(warm)
        self.assertEqual(warm.misses, 0)
        self.assertEqual(warm.hits, cold.misses)
        self.assertEqual(self.shape(second), self.shape(first))
        self.assertEqual(self.shape(self.analysis(None)), self.shape(first))  # and the same as no cache at all
        self.assertIn("pkg/broken.py", first.unparsed)  # an unparsed file is remembered as one
        self.assertEqual(first.graph.provenance["pkg/plugins.py"]["pkg/ext/a.py"], "dynamic")

    def test_a_changed_file_is_read_again_and_only_it(self):
        self.analysis(Store(self.path, now=self.now))
        (self.root / "pkg" / "util.py").write_text("def helper(name):\n    return name.upper()\n", encoding="utf-8")
        again = Store(self.path, now=self.now)
        found = self.analysis(again)
        self.assertEqual(again.misses, 1)
        self.assertEqual(found.records["pkg/util.py"].code, 2)

    def test_check_shares_the_store_with_the_base(self):
        (self.root / "pkg" / "util.py").write_text("def helper(name):\n    return name.upper()\n", encoding="utf-8")
        git(self.root, "commit", "-q", "-am", "two")
        cfg = config.Config()
        cfg.store = Store(self.path, now=self.now)
        first = since.check(self.root, cfg, "HEAD~1", now=self.now)
        cfg.store = Store(self.path, now=self.now)
        second = since.check(self.root, cfg, "HEAD~1", now=self.now)
        self.assertEqual(cfg.store.misses, 0)  # the base's files, read from git into a scratch directory, were in it too
        self.assertGreater(cfg.store.hits, 0)
        for result in (first, second):
            result["meta"].pop("generated", None)
        self.assertEqual(second, first)


class CommandLineTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, FILES)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "one")
        self.file = cache.directory() / f"{cache.repository_key(self.root)}.json"
        self.assertTrue(str(cache.directory()).startswith(tempfile.gettempdir()) or "TESSRI_CACHE_DIR" in os.environ)
        if self.file.exists():
            self.file.unlink()

    def scan(self, *flags: str) -> int:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(["scan", str(self.root), "--format", "json", *flags])

    def test_the_store_is_written_unless_told_not_to(self):
        self.assertEqual(self.scan("--no-cache"), 0)
        self.assertFalse(self.file.exists())
        self.assertEqual(self.scan(), 0)
        self.assertTrue(self.file.exists())
        self.file.unlink()
        (self.root / ".tessri.toml").write_text("cache = false\n", encoding="utf-8")
        self.assertEqual(self.scan(), 0)
        self.assertFalse(self.file.exists())

    def test_the_option_is_a_boolean(self):
        (self.root / ".tessri.toml").write_text("cache = 1\n", encoding="utf-8")
        with self.assertRaises(config.ConfigError) as caught:
            config.load(self.root)
        self.assertIn("`cache` must be true or false", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
