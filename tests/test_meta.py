"""The `meta` block and the reasons behind a missing history: every JSON output names the same HEAD, the revision
history was read up to and the base of a change, with full object ids, and a result that read nothing says so."""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempRepo, git, write_tree

from tessri import config, gitlog, meta, templates
from tessri.analyze import analyze
from tessri.cli import main

FULL_ID = re.compile(r"^[0-9a-f]{40}$")
TREE = {
    "pkg/__init__.py": "",
    "pkg/a.py": "import pkg.b\n",
    "pkg/b.py": "x = 1\n",
    "main.py": "import pkg.a\n",
    "README.md": "# demo\n",
}


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue()


class GitScenario(TempRepo):
    """A repository plus a way to put a `git` on PATH that fails one subcommand and hands the rest to the real one."""

    def make_repo(self):
        write_tree(self.root, TREE)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")
        git(self.root, "branch", "-M", "main")

    def state(self) -> dict:
        a = analyze(self.root, config.load(self.root))
        return meta.of(a)["git"]

    @contextlib.contextmanager
    def fake_git(self, failing: str, code: int = 128, message: str = "fatal: boom"):
        if sys.platform == "win32":
            self.skipTest("the stand-in git is a shell script")
        real = shutil.which("git")
        with tempfile.TemporaryDirectory() as shim:
            script = Path(shim) / "git"
            script.write_text(f'#!/bin/sh\nfor a in "$@"; do case "$a" in {failing}) echo "{message}" >&2; exit {code};; esac; done\nexec "{real}" "$@"\n')
            script.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": shim + os.pathsep + os.environ["PATH"]}):
                yield


class ReasonTest(GitScenario):
    def test_plain_directory(self):
        write_tree(self.root, {"a.py": "x = 1\n"})
        self.assertEqual(self.state(), {"available": False, "reason": "not-a-repository", "head": None, "history_rev": None, "shallow": None, "commits": None})

    def test_repository_without_commits(self):
        write_tree(self.root, {"a.py": "x = 1\n"})
        git(self.root, "init", "-q")
        g = self.state()
        self.assertEqual((g["available"], g["reason"], g["head"], g["history_rev"]), (False, "no-commits", None, None))

    def test_commits_without_files_are_history(self):
        """`git commit --allow-empty` in a fresh repository: git supplies no file list, but the history is there."""
        git(self.root, "init", "-q")
        git(self.root, "commit", "-q", "--allow-empty", "-m", "init")
        g = self.state()
        self.assertEqual((g["available"], g["reason"], g["commits"]), (True, None, 1))
        self.assertRegex(g["head"], FULL_ID)
        self.assertEqual(g["head"], g["history_rev"])

    def test_valid_repository(self):
        self.make_repo()
        g = self.state()
        self.assertEqual((g["available"], g["reason"], g["shallow"], g["commits"]), (True, None, False, 1))
        self.assertEqual(g["head"], g["history_rev"])
        self.assertRegex(g["head"], FULL_ID)

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as git")
    def test_history_read_failing_in_a_valid_repository(self):
        self.make_repo()
        with self.fake_git("log"):
            g = self.state()
        self.assertEqual((g["available"], g["reason"], g["history_rev"]), (False, "git-error", None))
        self.assertRegex(g["head"], FULL_ID)  # HEAD still resolves: only the read failed

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as git")
    def test_rev_parse_failure_is_an_error_not_a_missing_repository(self):
        self.make_repo()
        with self.fake_git("rev-parse"):
            self.assertEqual(gitlog.unavailable_reason(self.root), "git-error")

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as git")
    def test_broken_git_binary_is_an_error(self):
        self.make_repo()
        with self.fake_git("--version", code=3, message=""):
            self.assertEqual(gitlog.unavailable_reason(self.root), "git-error")

    def test_no_git_on_path(self):
        self.make_repo()
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"PATH": empty}):
            g = self.state()
        self.assertEqual((g["available"], g["reason"], g["head"]), (False, "git-not-found", None))

    def test_describe_not_requested(self):
        self.make_repo()
        state = gitlog.describe(self.root, "HEAD", None, requested=False)
        self.assertEqual((state.available, state.reason, state.history_rev), (False, "not-requested", None))
        self.assertRegex(state.head, FULL_ID)


class MetaTest(GitScenario):
    """Path queries name HEAD; change queries name HEAD, the base, and the base again as the history revision."""

    def setUp(self):
        super().setUp()
        self.make_repo()
        git(self.root, "checkout", "-qb", "feature")
        write_tree(self.root, {"pkg/b.py": "x = 2\ny = 3\n"})
        git(self.root, "commit", "-qam", "change")
        with open(self.root / "README.md", "a", encoding="utf-8") as fh:
            fh.write("more\n")
        self.head = self.rev("HEAD")
        self.base = self.rev("main")

    def rev(self, name):
        import subprocess

        return subprocess.run(["git", "-C", str(self.root), "rev-parse", name], capture_output=True, text=True, check=True).stdout.strip()

    def load(self, *argv):
        code, out = run_cli(*argv)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def test_scan_keeps_legacy_git_and_adds_meta(self):
        rep = self.load("scan", str(self.root), "--format", "json")
        m = rep["meta"]
        self.assertEqual(m["schema_version"], rep["schema_version"])
        self.assertEqual(m["repo"], {"name": self.root.name, "root": str(self.root)})
        self.assertEqual((m["git"]["head"], m["git"]["history_rev"], m["git"]["available"], m["git"]["reason"]), (self.head, self.head, True, None))
        self.assertNotIn("change", m)
        self.assertEqual(rep["git"], {"available": True, "head": self.head[:7], "shallow": False, "commits": 2})

    def test_graph_impact_and_why_carry_meta(self):
        for argv in (("graph", str(self.root), "--format", "json"), ("impact", "pkg/b.py", "--repo", str(self.root), "--format", "json"), ("why", "pkg/b.py", "--repo", str(self.root), "--format", "json")):
            with self.subTest(argv[0]):
                m = self.load(*argv)["meta"]
                self.assertEqual((m["git"]["head"], m["git"]["history_rev"]), (self.head, self.head))
                self.assertNotIn("change", m)

    def test_triage_separates_head_base_and_history(self):
        t = self.load("triage", "--repo", str(self.root), "--since", "main", "--format", "json")
        self.assertNotEqual(self.head, self.base)
        self.assertEqual(t["meta"]["git"]["head"], self.head)
        self.assertEqual(t["meta"]["git"]["history_rev"], self.base)
        self.assertEqual(t["meta"]["change"], {"since": "main", "base": self.base, "head": self.head, "uncommitted": True})
        self.assertEqual((t["change"]["base"], t["change"]["head"], t["change"]["uncommitted"]), (self.base[:9], self.head[:9], True))

    def test_check_separates_head_base_and_history(self):
        c = self.load("check", "--repo", str(self.root), "--since", "main", "--format", "json")
        self.assertEqual((c["meta"]["git"]["head"], c["meta"]["git"]["history_rev"], c["meta"]["git"]["available"]), (self.head, self.base, True))
        self.assertEqual(c["meta"]["change"], {"since": "main", "base": self.base, "head": self.head, "uncommitted": True})
        self.assertEqual(c["meta"]["analysis"], {"structure": "complete", "reason": None})
        self.assertEqual((c["change"]["base"], c["change"]["head"]), (self.base[:9], self.head[:9]))

    def test_check_without_code_changes_does_not_claim_an_analysis(self):
        git(self.root, "checkout", "-q", "--", "README.md")
        git(self.root, "checkout", "-q", "main")
        with open(self.root / "README.md", "a", encoding="utf-8") as fh:
            fh.write("docs only\n")
        c = self.load("check", "--repo", str(self.root), "--format", "json")
        self.assertEqual(c["findings"], [])
        self.assertEqual(c["summary"]["code_files"], 0)
        self.assertEqual(c["meta"]["analysis"], {"structure": "skipped", "reason": "no-code-changes"})
        self.assertEqual((c["meta"]["git"]["available"], c["meta"]["git"]["reason"], c["meta"]["git"]["history_rev"]), (False, "not-requested", None))
        self.assertEqual(c["meta"]["git"]["head"], self.base)
        self.assertEqual(c["meta"]["change"]["uncommitted"], True)


class SkillWordingTest(unittest.TestCase):
    def test_no_active_owner_is_a_signal_not_a_stop(self):
        for phrase in ("ask a human", "ask a person", "before changing it"):
            self.assertNotIn(phrase, templates.SKILL)
        self.assertIn("do not pick a reviewer from", templates.SKILL)
        self.assertIn("team's policy", templates.SKILL)
