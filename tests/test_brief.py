"""`tessri brief`: triage and check from one pair of analyses, composed into one page for the person a change is
handed to, with the state the evidence describes, what the host ran kept apart from candidate tests, and what the
analysis could not see said rather than left out."""

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempRepo, git, write_tree
from tessri import brief, config, since, triage
from tessri.cli import main

ALICE = ("Alice Adams", "alice@example.com")
BOB = ("Bob Brown", "bob@example.com")
CAROL = ("Carol Chen", "carol@example.com")

ENGINE = "from util import helpers\n\n\ndef run():\n    return helpers.go()\n"
BASE = {
    "app/__init__.py": "",
    "app/main.py": "from core import engine\n\nif __name__ == '__main__':\n    engine.run()\n",
    "core/__init__.py": "",
    "core/engine.py": ENGINE,
    "util/__init__.py": "",
    "util/helpers.py": "def go():\n    return 1\n",
    "tests/test_engine.py": "from core import engine\n\n\ndef test_run():\n    assert engine.run()\n",
    "svc/main.go": "package main\n\nfunc main() {}\n",
    "README.md": "# demo\n",
}


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class Repo(TempRepo):
    """main: Bob wrote util/ 300 days ago and has been silent since; Alice wrote the rest and fixed the engine 40 days
    ago. `feature()` adds Carol's branch (the engine extended, a new core/extra.py nothing reaches, the Go file and the
    README edited, then the helpers fixed) and one uncommitted edit of app/main.py by Dana, the git user."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Dana Doe")
        git(self.root, "config", "user.email", "dana@example.com")
        self.commit({k: v for k, v in BASE.items() if not k.startswith("util/")}, ALICE, 320, "feat: the app")
        self.commit({"util/__init__.py": "", "util/helpers.py": BASE["util/helpers.py"]}, BOB, 300, "feat: util")
        self.commit({"core/engine.py": ENGINE + "\n\ndef again():\n    return run()\n"}, ALICE, 40, "fix: engine again")

    def commit(self, files, who, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "-m", message, when=when, author=who)

    def feature(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        engine = (self.root / "core/engine.py").read_text()
        self.commit(
            {"core/engine.py": engine + "\n\ndef carol():\n    return 3\n", "core/extra.py": "X = 1\n", "svc/main.go": "package main\n\nfunc main() { println(1) }\n", "README.md": "# demo\n\nmore\n"},
            CAROL, 1, "feat: carol extends the engine",
        )
        self.commit({"util/helpers.py": "def go():\n    return 3\n"}, CAROL, 0.5, "fix: helpers")
        write_tree(self.root, {"app/main.py": "from core import engine\n\nif __name__ == '__main__':\n    print(engine.run())\n"})

    def brief(self, since="main", **kw):
        return brief.compute(self.root, config.load(self.root), since, now=self.now, **kw)


class CompositionTest(Repo):
    def setUp(self):
        super().setUp()
        self.feature()

    def test_it_is_triage_and_check_from_one_pair_of_analyses(self):
        cfg = config.load(self.root)
        calls = []
        real = brief.analyze

        def counting(*args, **kwargs):
            calls.append(kwargs.get("rev"))
            return real(*args, **kwargs)

        with mock.patch.object(brief, "analyze", counting), mock.patch.object(since, "analyze", counting), mock.patch.object(triage, "analyze", counting):
            b = self.brief()
        self.assertEqual(len(calls), 2, calls)  # the working tree with history up to the base, and the base itself
        self.assertEqual(b["triage"], triage.compute(self.root, cfg, "main", now=self.now))
        self.assertEqual(b["check"], since.check(self.root, cfg, "main", now=self.now))
        self.assertEqual((b["kind"], b["schema_version"]), ("brief", 1))
        self.assertEqual(b["meta"]["analysis"], {"structure": "complete", "reason": None})
        self.assertEqual(b["meta"]["change"], {"since": "main", "base": b["change"]["base"], "head": b["change"]["head"], "uncommitted": True})
        self.assertRegex(b["change"]["base"], r"^[0-9a-f]{40}$")
        self.assertEqual(b["meta"]["git"]["history_rev"], b["change"]["base"])

    def test_the_scope_names_the_commits_and_the_uncommitted_work(self):
        b = self.brief()
        c = b["change"]
        self.assertEqual([k["subject"] for k in c["commits"]], ["fix: helpers", "feat: carol extends the engine"])
        self.assertEqual({k["author"] for k in c["commits"]}, {"Carol Chen"})
        self.assertEqual((c["uncommitted"], c["uncommitted_files"]), (True, ["app/main.py"]))
        self.assertEqual((c["code_files"], c["added"], c["modified"], c["deleted"], c["other_files"]), (5, 1, 4, 0, 1))
        self.assertEqual(c["authors"], ["Carol Chen", "Dana Doe"])  # the commits' authors, and the git user for the uncommitted work
        text = brief.markdown(b)
        self.assertIn(f"`main` (base {c['base'][:9]}) to the working tree: HEAD {c['head'][:9]} plus 1 uncommitted file (`app/main.py`). 5 code files changed (1 added, 4 modified, 0 deleted), **", text)
        self.assertIn("2 commits on the way, by Carol Chen, Dana Doe, in their words:", text)
        self.assertIn(f"- `{c['commits'][0]['id'][:9]}` fix: helpers (Carol Chen)", text)

    def test_what_was_not_analysed_is_said_not_left_out(self):
        b = self.brief()
        self.assertEqual(b["consequences"]["not_analysed"], [{"language": "Go", "files": ["svc/main.go"]}])
        self.assertIn("Not analysed: `svc/main.go` (Go, no analyzer), so dependents, candidate tests and structure are unknown for it.", brief.markdown(b))
        self.assertIn("not-analysed", [item["kind"] for item in b["open"]])

    def test_what_the_host_ran_is_recorded_verbatim_or_said_to_be_missing(self):
        b = self.brief()
        self.assertEqual(b["validation"], {"candidates": {"count": 1, "nearest": ["tests/test_engine.py"]}, "ran": [], "report": None})
        text = brief.markdown(b)
        self.assertIn("Candidate tests, nearest first: `tests/test_engine.py`. They reach the changed files; they are paths, not results.", text)
        self.assertIn('Checks the host ran: none recorded. Record each with `--ran "<command>: <result, exit code>"`, or hand over a test report with `--report`.', text)
        self.assertIn("no-checks-recorded", [item["kind"] for item in b["open"]])
        b = self.brief(ran=["python -m unittest tests/test_engine.py: 1 test OK (exit 0)", "mypy: not run"])
        text = brief.markdown(b)
        self.assertEqual(b["validation"]["ran"], ["python -m unittest tests/test_engine.py: 1 test OK (exit 0)", "mypy: not run"])
        self.assertIn("Checks the host ran, as recorded:\n\n- python -m unittest tests/test_engine.py: 1 test OK (exit 0)\n- mypy: not run\n", text)
        self.assertNotIn("none recorded", text)
        self.assertNotIn("no-checks-recorded", [item["kind"] for item in b["open"]])

    def test_a_test_report_the_host_wrote_is_held_against_the_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:  # outside the repository, where a report would be uncommitted work
            passing, other, failing = Path(tmp, "passing.xml"), Path(tmp, "other.xml"), Path(tmp, "failing.xml")
            passing.write_text('<testsuites><testsuite name="s"><testcase classname="tests.test_engine" name="test_run"/><testcase classname="tests.test_engine" name="test_again"/></testsuite></testsuites>')
            other.write_text('<testsuites><testsuite name="s"><testcase classname="tests.test_other" name="test_x"/></testsuite></testsuites>')
            failing.write_text('<testsuites><testsuite name="s"><testcase classname="tests.test_engine" name="test_run"><failure message="no"/></testcase></testsuite></testsuites>')
            b = self.brief(reports=[passing])
            self.assertEqual(b["validation"]["report"], {"sources": [str(passing)], "cases": 2, "ran": {"tests/test_engine.py": "passed"}, "passed": 1, "failed": [], "skipped": 0, "not_run": [], "unmatched": {"cases": 0, "named": []}})
            self.assertNotIn("no-checks-recorded", [item["kind"] for item in b["open"]])
            text = brief.markdown(b)
            self.assertIn("Candidate tests, nearest first: `tests/test_engine.py` (passed). They reach the changed files; they are paths, not results.", text)
            self.assertIn("Against the report: 1 of the 1 ran, 1 passed, 0 failed; 0 did not run.", text)
            self.assertIn(f"Checks the host ran, as recorded:\n\n- test report `{passing}`: 2 cases\n", text)
            self.assertIn("or a test report the host wrote and `--report` reads, was run", text)
            b = self.brief(reports=[other, failing])  # two reports as one: the candidate failed in one and is in neither as a pass
            held = b["validation"]["report"]
            self.assertEqual((held["sources"], held["cases"], held["ran"], held["failed"], held["unmatched"]), ([str(other), str(failing)], 2, {"tests/test_engine.py": "failed"}, ["tests/test_engine.py"], {"cases": 1, "named": ["tests.test_other"]}))
            self.assertEqual([item["kind"] for item in b["open"] if item["kind"].startswith("candidate")], ["candidate-failed"])
            self.assertIn("`tests/test_engine.py` failed in the report: the tests that reach the change do not pass.", brief.markdown(b))
            b = self.brief(reports=[other])
            self.assertEqual((b["validation"]["report"]["ran"], b["validation"]["report"]["not_run"]), ({}, ["tests/test_engine.py"]))
            self.assertEqual([item["kind"] for item in b["open"] if item["kind"].startswith("candidate")], ["candidates-not-run"])
            self.assertIn("Against the report: 0 of the 1 ran, 0 passed, 0 failed; 1 did not run (`tests/test_engine.py`).", brief.markdown(b))
            code, out, err = run_cli("brief", "--since", "main", "--repo", str(self.root), "--report", str(passing), "--format", "json")
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(out)["validation"]["report"]["ran"], {"tests/test_engine.py": "passed"})
            code, out, err = run_cli("brief", "--since", "main", "--repo", str(self.root), "--report", str(Path(tmp, "missing.xml")))
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("tessri: ") and "missing.xml" in err, err)

    def test_findings_and_people_flow_into_what_needs_a_person(self):
        b = self.brief()
        self.assertEqual([item["kind"] for item in b["open"]], ["no-active-owner", "only-the-author", "not-analysed", "no-checks-recorded"])
        self.assertEqual(b["open"][0]["files"], ["util/helpers.py"])
        self.assertEqual(b["people"], {"reviewers": b["triage"]["reviewers"], "nobody_else_can_look": ["util/helpers.py"], "no_active_owner": ["util/helpers.py"]})
        self.assertEqual([r["name"] for r in b["people"]["reviewers"]], ["Alice Adams"])
        text = brief.markdown(b)
        self.assertIn("Who can look, other than the authors: Alice Adams (3 files).", text)
        self.assertIn("- 1 changed file nobody active maintains: Have a human who knows the code look before merging", text)
        self.assertIn("- Only the author maintains `util/helpers.py`: a second reader has to come from outside the file's history.", text)
        self.assertIn("**2 warn.**", text)
        self.assertIn("- **warn**: 1 new file that nothing reaches (`core/extra.py`).", text)
        self.assertEqual(b["consequences"]["ripple"], {"direct": 0, "second": 0})  # app/main.py imports the engine, but it is in the change itself
        self.assertIn("Nothing outside the change imports it, as far as static imports show.", text)

    def test_lists_are_shortened_with_their_counts(self):
        b = self.brief(limit=1)
        self.assertEqual((b["attention"]["shown"], b["attention"]["total"], len(b["triage"]["files"])), (1, 5, 5))
        self.assertEqual(b["attention"]["files"], b["triage"]["files"][:1])
        text = brief.markdown(b)
        self.assertIn("4 more files, in order, under `triage.files`.", text)
        self.assertEqual(text.count("| 1 | `"), 1)

    def test_the_page_stays_within_its_reading_budget(self):
        text = brief.markdown(self.brief(ran=["unittest: 1 test OK (exit 0)"]))
        self.assertLess(len(text.split()), brief.BUDGET)
        for heading in ("# Review brief: ", "## Look first", "## What it did to the structure", "## Validation", "## Open for a person", "## Read this with care"):
            self.assertIn(heading, text)


class ScopeTest(Repo):
    def test_a_change_without_code_compares_nothing_and_says_so(self):
        git(self.root, "checkout", "-q", "-b", "docs")
        self.commit({"README.md": "# demo\n\nmore\n"}, CAROL, 1, "docs: more")
        calls = []
        real = brief.analyze
        with mock.patch.object(brief, "analyze", lambda *a, **k: calls.append(k.get("rev")) or real(*a, **k)), mock.patch.object(since, "analyze", lambda *a, **k: calls.append("base")):
            b = self.brief()
        self.assertEqual(len(calls), 1)  # the working tree, for the people; no base to compare with
        self.assertEqual(b["meta"]["analysis"], {"structure": "skipped", "reason": "no-code-changes"})
        self.assertEqual((b["change"]["code_files"], b["change"]["other_files"], b["attention"]["total"]), (0, 1, 0))
        text = brief.markdown(b)
        self.assertIn("No code changed; 1 other file (2 lines of config, docs and the like).", text)
        self.assertIn("No code changed, so there is nothing to rank; the other files are under `check.changed_files`.", text)
        self.assertIn("Nothing was compared: no code changed.", text)
        self.assertNotIn("Candidate tests, nearest first", text)

    def test_uncommitted_work_alone_has_no_commits_on_the_way(self):
        write_tree(self.root, {"core/engine.py": ENGINE + "\n\ndef dana():\n    return 4\n"})
        b = self.brief("HEAD")
        self.assertEqual((b["change"]["commits"], b["change"]["uncommitted_files"], b["change"]["authors"]), ([], ["core/engine.py"], ["Dana Doe"]))
        self.assertIn("No commits on the way: the change is uncommitted work by Dana Doe.", brief.markdown(b))

    def test_a_clean_head_is_said_to_be_head(self):
        self.feature()
        git(self.root, "checkout", "-q", "--", "app/main.py")
        b = self.brief()
        self.assertEqual((b["change"]["uncommitted"], b["change"]["uncommitted_files"]), (False, []))
        text = brief.markdown(b)
        self.assertIn(f"`main` (base {b['change']['base'][:9]}) to HEAD {b['change']['head'][:9]}. 4 code files changed", text)
        self.assertEqual(b["consequences"]["ripple"], {"direct": 1, "second": 0})  # app/main.py, untouched now, imports the engine
        self.assertIn("Code outside the change that imports it: **1 file** directly, 0 files through one more step (by area: `", text)

    def test_mistakes_are_the_commands_sentences(self):
        with self.assertRaises(brief.BriefError) as caught:
            self.brief("nope")
        self.assertEqual(str(caught.exception), "`nope` is not a commit, branch or tag in this repository")
        with tempfile.TemporaryDirectory() as tmp:  # its own directory: inside the fixture it would be part of that repository
            plain = Path(tmp).resolve()
            write_tree(plain, {"a.py": "x = 1\n"})
            with self.assertRaises(brief.BriefError) as caught:
                brief.compute(plain, config.load(plain), "HEAD")
        self.assertEqual(str(caught.exception), "brief needs a git repository")


class CliTest(Repo):
    def setUp(self):
        super().setUp()
        self.feature()

    def test_the_page_and_the_json(self):
        code, out, err = run_cli("brief", "--since", "main", "--repo", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, brief.markdown(self.brief()))
        code, out, err = run_cli("brief", "--since", "main", "--repo", str(self.root), "--format", "json", "--ran", "unittest: OK", "--ran", "lint: skipped", "--limit", "2")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual((doc["kind"], doc["validation"]["ran"], doc["attention"]["shown"]), ("brief", ["unittest: OK", "lint: skipped"], 2))
        self.assertEqual(doc["triage"]["kind"], "triage")
        self.assertEqual(doc["check"]["kind"], "change-check")

    def test_a_bad_base_exits_2_with_nothing_on_stdout(self):
        code, out, err = run_cli("brief", "--since", "nope", "--repo", str(self.root))
        self.assertEqual((code, out, err), (2, "", "tessri: `nope` is not a commit, branch or tag in this repository\n"))

    def test_out_writes_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:  # outside the repository, where the written file would be uncommitted work
            target = Path(tmp) / "out" / "brief.md"
            code, out, err = run_cli("brief", "--since", "main", "--repo", str(self.root), "--out", str(target))
            self.assertEqual((code, out), (0, ""))
            self.assertEqual(target.read_text(), brief.markdown(self.brief()))


if __name__ == "__main__":
    unittest.main()
