import contextlib
import dataclasses
import io
import json
import os
import re
import time
import unittest

from helpers import TempRepo, git, write_tree
from tessri import config, gitlog, triage
from tessri.analyze import analyze
from tessri.cli import main
from tessri.report import build_report

ALICE = ("Alice Adams", "alice@example.com")
BOB = ("Bob Brown", "bob@example.com")
CAROL = ("Carol Chen", "carol@example.com")
A0 = "".join(f"def f{i}():\n    return {i}\n" for i in range(5))  # 10 lines


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class Repo(TempRepo):
    """main: Alice owns core/ and fixes core/a.py twice lately; Bob wrote util/ and is long gone.
    A branch `feature` then carries Carol's change. Commit dates are days before `self.now`."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Dana Doe")
        git(self.root, "config", "user.email", "dana@example.com")
        self.commit({"core/__init__.py": "", "core/a.py": A0, "core/b.py": "from core import a\n\n\ndef b():\n    return a.f0()\n", "tests/test_a.py": "from core import a\n\n\ndef test_a():\n    assert a.f0() == 0\n"}, ALICE, 300, "feat: add core")
        self.commit({"util/__init__.py": "", "util/c.py": "def c():\n    return 1\n"}, BOB, 300, "feat: add util")
        self.commit({"core/b.py": "from core import a\n\n\ndef b():\n    return a.f0() + 1\n"}, ALICE, 200, "fix: old trouble in b")
        self.commit({"core/a.py": A0 + "def g():\n    return 'handle empty'\n"}, ALICE, 60, "fix: handle empty input")
        self.commit({"core/a.py": A0 + "def g():\n    return 'handle empty'\n\n\ndef h():\n    return 1\n"}, ALICE, 40, "Fix off by one")
        self.commit({"core/a.py": A0 + "def g():\n    return 'handle empty'\n\n\ndef h():\n    return 1\n\n\ndef k():\n    return 2\n"}, ALICE, 20, "feat: more")

    def commit(self, files, who, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "-m", message, when=when, author=who)

    def feature(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        a = (self.root / "core/a.py").read_text()
        self.commit({"core/a.py": a + "\n\ndef carol():\n    return 3\n", "core/b.py": "from core import a\n\n\ndef b():\n    return a.f0() + 2\n    # carol\n", "util/c.py": "def c():\n    return 1\n\n\ndef c2():\n    return 2\n\n\ndef c3():\n    return 3\n"}, CAROL, 1, "fix: carol touches things")
        (self.root / "logo.png").write_bytes(b"\x89PNG\r\n\x00\x00binary")
        self.commit({"core/d.py": "def d():\n    return 4\n" * 3, "docs/notes.md": "one\ntwo\n", "package-lock.json": "{}\n" * 50}, CAROL, 0.5, "feat: carol adds d")

    def triage(self, since="main", **settings):
        cfg = config.load(self.root)
        for key, value in settings.items():
            setattr(cfg, key, value)
        return triage.compute(self.root, cfg, since, now=self.now)


class FixSubjectTest(unittest.TestCase):
    def test_what_counts_as_a_repair(self):
        for subject in ("fix: x", "fix(core): y", "fix!: z", "Fix typo in README", "Fixes #12", "fixed the build", "bugfix: z", "bug-fix", "hotfix", "Hotfix v2", 'Revert "feat: x"', "revert: x"):
            self.assertTrue(gitlog.FIX_SUBJECT.match(subject), subject)
        for subject in ("fixture: add data", "prefix: x", "feat: fix typo", "refactor: fixes naming", "Add a fixes list", "fixing flaky tests", "feat(fix): x", "debug: x"):
            self.assertFalse(gitlog.FIX_SUBJECT.match(subject), subject)


class IgnoredAuthorsTest(unittest.TestCase):
    def test_automation_never_owns_code(self):
        for name, email in (("dependabot[bot]", "x@users.noreply.github.com"), ("svcnvidia-nemo-ci", "svc@example.com"), ("pre-commit-ci", "x@x"), ("Release Bot", "release_bot@example.com"), ("nemo-ci", "x@x"), ("x", "deploy-bot@users.noreply.github.com")):
            self.assertTrue(gitlog.is_ignored(name, email, ()), name)
        for name, email in (("Luci", "luci@example.com"), ("Abbot", "abbot@example.com"), ("Alice Adams", "alice@ci.example.com"), ("Ci Wang", "ci@example.com")):
            self.assertFalse(gitlog.is_ignored(name, email, ()), name)
        self.assertTrue(gitlog.is_ignored("Alice Adams", "alice@ci.example.com", ("*@ci.example.com",)))


class HistoryTest(Repo):
    def test_fix_counts_per_file(self):
        act = gitlog.load(self.root, self.now, 90)
        self.assertEqual((act.files["core/a.py"].fixes_90, act.files["core/a.py"].fixes_year), (2, 2))
        self.assertEqual((act.files["core/b.py"].fixes_90, act.files["core/b.py"].fixes_year), (0, 1))
        self.assertEqual((act.files["util/c.py"].fixes_90, act.files["util/c.py"].fixes_year), (0, 0))

    def test_recent_commits_are_kept_per_file_and_per_person(self):
        act = gitlog.load(self.root, self.now, 90)
        self.assertEqual({who: len(whens) for who, whens in act.recent["core/a.py"].items()}, {"alice adams": 4})  # 300, 60, 40 and 20 days ago
        self.assertEqual({who: len(whens) for who, whens in act.recent["core/b.py"].items()}, {"alice adams": 2})
        self.assertEqual(len(act.recent["core/a.py"]["alice adams"] | act.recent["core/b.py"]["alice adams"]), 5)  # the first commit touched both
        self.assertEqual({who: len(whens) for who, whens in act.recent["util/c.py"].items()}, {"bob brown": 1})  # 300 days old: inside the year
        self.assertEqual((act.authors["alice adams"].commits_active, act.authors["bob brown"].commits_active), (3, 0))

    def test_a_merge_counts_for_the_person_but_touches_no_file(self):
        git(self.root, "checkout", "-q", "-b", "side")
        self.commit({"util/c.py": "def c():\n    return 2\n"}, ("Erin Ebert", "erin@example.com"), 10, "fix: c")
        git(self.root, "checkout", "-q", "main")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - 9 * 86400))
        git(self.root, "merge", "-q", "--no-ff", "-m", "Merge side", "side", when=when, author=ALICE)
        act = gitlog.load(self.root, self.now, 90)
        self.assertEqual((act.authors["alice adams"].commits_active, act.authors["erin ebert"].commits_active), (4, 1))  # the merge is hers
        self.assertEqual(act.files["util/c.py"].commits_active, 1)  # Erin's commit; the merge lists no file
        self.assertEqual(set(act.recent["util/c.py"]), {"bob brown", "erin ebert"})

    def test_history_can_be_read_up_to_a_base_commit(self):
        base = git_out(self.root, "rev-parse", "main")
        self.feature()
        later = gitlog.load(self.root, self.now, 90)
        before = gitlog.load(self.root, self.now, 90, (), base)
        self.assertEqual(later.commits, before.commits + 2)
        self.assertEqual(before.files["core/a.py"].fixes_90, 2)
        self.assertEqual(later.files["core/a.py"].fixes_90, 3)  # Carol's "fix:" counts once her commits are included
        self.assertNotIn("carol chen", before.authors)
        self.assertIn("carol chen", later.authors)

    def test_the_report_carries_fix_counts(self):
        a = analyze(self.root, config.load(self.root), now=self.now)
        report = build_report(a, full=True)
        row = next(r for r in report["files"] if r["path"] == "core/a.py")
        self.assertEqual((row["fixes_90"], row["fixes_year"]), (2, 2))
        self.assertTrue(all("fixes_year" in h for h in report["hotspots"]))


def git_out(root, *args):
    import subprocess

    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class TriageTest(Repo):
    def setUp(self):
        super().setUp()
        self.feature()
        self.t = self.triage()
        self.by = {r["path"]: r for r in self.t["files"]}

    def test_files_are_ordered_by_history_of_trouble_then_activity_then_size(self):
        self.assertEqual([r["path"] for r in self.t["files"]], ["core/a.py", "util/c.py", "core/d.py", "core/b.py"])  # three commits; then by lines: 8, 6, 2
        self.assertEqual([r["rank"] for r in self.t["files"]], [1, 2, 3, 4])
        self.assertEqual([r["tier"] for r in self.t["files"]], ["busy", "quiet", "new", "quiet"])

    def test_the_change_does_not_count_as_its_own_trouble(self):
        a = self.by["core/a.py"]
        self.assertEqual((a["fixes_90"], a["fixes_year"], a["commits_active"]), (2, 2, 3))  # Carol's "fix:" commit is not in the history yet
        self.assertEqual(self.by["core/b.py"]["fixes_90"], 0)

    def test_the_author_of_the_change_is_not_an_owner_of_what_they_changed(self):
        self.assertEqual(self.t["change"]["authors"], ["Carol Chen"])
        self.assertIn("author is not among the owners", self.by["core/a.py"]["flags"])
        self.assertEqual([o["name"] for o in self.by["core/a.py"]["owners"]], ["Alice Adams"])

    def test_code_nobody_active_maintains_is_flagged(self):
        c = self.by["util/c.py"]
        self.assertIn("no active owner", c["flags"])
        self.assertEqual(c["ownership"], "no-active-owner")
        self.assertEqual(self.t["nobody_else_can_look"], ["util/c.py"])
        self.assertEqual(self.t["summary"]["no_active_owner"], 1)

    def test_new_files_have_no_history(self):
        d = self.by["core/d.py"]
        self.assertEqual((d["change"], d["fixes_90"], d["commits_active"], d["owners"], d["last_commit"]), ("added", 0, 0, [], None))
        self.assertIn("new file", d["flags"])

    def test_lines_come_from_the_diff_with_the_base(self):
        a = self.by["core/a.py"]
        self.assertEqual((a["added"], a["deleted"], a["lines"]), (4, 0, 4))
        self.assertEqual(self.by["core/d.py"]["added"], 6)
        self.assertEqual(self.t["summary"]["lines"], sum(r["lines"] for r in self.t["files"]))

    def test_other_files_are_counted_apart_and_excluded_ones_are_ignored(self):
        s = self.t["summary"]
        self.assertEqual((s["files"], s["other_files"], s["other_lines"]), (4, 2, 2))  # notes.md and the binary logo; package-lock.json is excluded
        self.assertNotIn("package-lock.json", json.dumps(self.t))

    def test_what_imports_the_change_is_context(self):
        a = self.by["core/a.py"]
        self.assertEqual(a["dependents"], {"direct": 1, "within_2": 1})  # core/b.py, which is itself in the change
        self.assertEqual(self.t["summary"]["ripple"], {"direct": 0, "second": 0})  # nothing outside the change imports it
        self.assertEqual(self.t["tests"], {"count": 1, "nearest": ["tests/test_a.py"], "paths": ["tests/test_a.py"]})

    def test_who_can_look_excludes_the_author_and_the_gone(self):
        self.assertEqual([r["name"] for r in self.t["reviewers"]], ["Alice Adams"])
        self.assertEqual((self.t["reviewers"][0]["files"], self.t["reviewers"][0]["commits"]), (2, 5))  # a.py and b.py; five distinct commits in the year
        self.assertNotIn("Bob Brown", json.dumps(self.t["reviewers"]))

    def test_the_regulars_are_the_busiest_committers_of_the_window_other_than_the_authors(self):
        self.assertEqual(self.t["regulars"], {"window_days": 90, "commits": 3, "committers": 1, "people": [{"name": "Alice Adams", "commits": 3, "share": 1.0}]})
        self.assertIsNone(triage.regulars_line(self.t))  # she is already offered

    def test_a_deleted_file_is_listed_with_its_history(self):
        git(self.root, "rm", "-q", "core/b.py")
        t = self.triage()
        row = next(r for r in t["files"] if r["path"] == "core/b.py")
        self.assertEqual((row["change"], row["fixes_year"]), ("deleted", 1))
        self.assertIn("deleted", row["flags"])

    def test_nothing_in_the_output_is_an_address(self):
        text = json.dumps(self.t) + triage.markdown(self.t)
        self.assertNotRegex(text, r"[\w.]+@[\w.]+\.\w+")

    def test_output_is_deterministic(self):
        self.assertEqual(json.dumps(self.t), json.dumps(self.triage()))

    def test_markdown_tells_a_reader_what_to_do(self):
        text = triage.markdown(self.t)
        for want in ("# Change triage", "Look at these first", "`core/a.py`", "3 commits in 90 days, 2 of them fixes or reverts", "no active owner", "Who can look, other than the authors: Alice Adams", "Read this with care"):
            self.assertIn(want, text)
        self.assertLess(text.index("`core/a.py`"), text.index("`core/d.py`"))


class RecencyTest(TempRepo):
    """old.py: Alice wrote it long ago and Erin touched it once this year; hot.py: Alice committed to it twelve times this
    year and Frank once, so Frank's share is under a tenth. Carol's branch then changes both."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Dana Doe")
        git(self.root, "config", "user.email", "dana@example.com")
        for i, days in enumerate(range(450, 390, -10)):
            self.commit({"old.py": f"OLD = {i}\n", "hot.py": "HOT = 0\n"}, ALICE, days, f"feat: old {i}")
        for i, days in enumerate(range(150, 90, -5)):
            self.commit({"hot.py": f"HOT = {i + 1}\n"}, ALICE, days, f"feat: hot {i + 1}")
        self.commit({"old.py": "OLD = 6\nERIN = 1\n"}, ("Erin Ebert", "erin@example.com"), 20, "fix: old")
        self.commit({"hot.py": "HOT = 11\nFRANK = 1\n"}, ("Frank Fox", "frank@example.com"), 15, "fix: hot")

    def commit(self, files, who, days_ago, message):
        write_tree(self.root, files)
        git(self.root, "add", "-A")
        when = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))
        git(self.root, "commit", "-q", "-m", message, when=when, author=who)

    def triage(self):
        return triage.compute(self.root, config.load(self.root), "main", now=self.now)

    def test_recent_commits_rank_before_share_and_a_small_share_with_a_commit_is_offered(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"old.py": "OLD = 6\nERIN = 1\nCAROL = 1\n", "hot.py": "HOT = 11\nFRANK = 1\nCAROL = 1\n"}, CAROL, 1, "feat: carol")
        t = self.triage()
        rows = [(r["name"], r["files"], r["commits"]) for r in t["reviewers"]]
        self.assertEqual(rows, [("Alice Adams", 2, 12), ("Erin Ebert", 1, 1), ("Frank Fox", 1, 1)])  # Alice's twelve are this year's; her six to old.py are not
        self.assertLess(next(o["share"] for o in next(r for r in t["files"] if r["path"] == "hot.py")["owners"] if o["name"] == "Alice Adams"), 100)
        self.assertNotIn("Frank Fox", json.dumps(next(r for r in t["files"] if r["path"] == "hot.py")["owners"]))  # under a tenth, so not an owner, yet offered
        self.assertEqual(t["nobody_else_can_look"], [])
        self.assertEqual(t["regulars"], {"window_days": 90, "commits": 2, "committers": 2, "people": [{"name": "Erin Ebert", "commits": 1, "share": 0.5}, {"name": "Frank Fox", "commits": 1, "share": 0.5}]})
        self.assertIn("Who can look, other than the authors: Alice Adams (2 files, 12 commits in the last year), Erin Ebert (1 file, 1 commit in the last year), Frank Fox (1 file, 1 commit in the last year).", triage.markdown(t))

    def test_a_holder_without_a_commit_this_year_is_offered_last_and_says_so(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"old.py": "OLD = 6\nERIN = 1\nFRANK = 1\n"}, ("Frank Fox", "frank@example.com"), 1, "feat: frank")
        t = self.triage()
        self.assertEqual([(r["name"], r["files"], r["commits"]) for r in t["reviewers"]], [("Erin Ebert", 1, 1), ("Alice Adams", 1, 0)])
        text = triage.markdown(t)
        self.assertIn("Who can look, other than the authors: Erin Ebert (1 file, 1 commit in the last year), Alice Adams (1 file, no commits in the last year).", text)
        self.assertNotIn("regulars", text)  # Erin is named, Frank is the author

    def test_the_regulars_not_already_named_get_their_own_line(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        self.commit({"old.py": "OLD = 6\nERIN = 1\nALICE = 1\n"}, ALICE, 1, "feat: alice again")
        t = self.triage()
        self.assertEqual([r["name"] for r in t["reviewers"]], ["Erin Ebert"])
        self.assertEqual(t["regulars"]["people"], [{"name": "Erin Ebert", "commits": 1, "share": 0.5}, {"name": "Frank Fox", "commits": 1, "share": 0.5}])
        self.assertEqual(
            triage.regulars_line(t),
            "The repository's regulars in the last 90 days, apart from the authors and the people above: Frank Fox (1 commit, 50%), of 2 commits by 2 people. "
            "Where a few people review everything they are the reviewers whatever the files; where review is spread, the people behind the files are the better offer.",
        )
        self.assertIn(triage.regulars_line(t), triage.markdown(t))


class RippleTest(Repo):
    def test_files_outside_the_change_that_import_it_are_listed_by_distance(self):
        self.commit({"app/__init__.py": "", "app/main.py": "from core import a\n\n\ndef main():\n    return a.f0()\n", "app/run.py": "from app import main\n\nif __name__ == '__main__':\n    main.main()\n"}, ALICE, 30, "feat: app")
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"core/a.py": (self.root / "core/a.py").read_text() + "\n\ndef z():\n    return 0\n"}, CAROL, 0.3, "feat: z")
        t = self.triage("main")
        self.assertEqual(t["summary"]["ripple"], {"direct": 2, "second": 1})  # core/b.py and app/main.py; app/run.py one step further
        self.assertEqual(t["ripple"], [{"module": "app", "direct": 1, "second": 1}, {"module": "core", "direct": 1, "second": 0}])
        self.assertEqual(t["files"][0]["dependents"], {"direct": 2, "within_2": 3})
        self.assertEqual(t["tests"]["nearest"], ["tests/test_a.py"])

    def test_files_in_the_change_are_not_counted_as_outside_it(self):
        git(self.root, "checkout", "-q", "-b", "topic")
        a = (self.root / "core/a.py").read_text()
        self.commit({"core/a.py": a + "\n\ndef z():\n    return 0\n", "core/b.py": "from core import a\n\n\ndef b():\n    return a.f0() + 5\n"}, CAROL, 0.3, "feat: both")
        t = self.triage("main")
        self.assertEqual(t["summary"]["ripple"], {"direct": 0, "second": 0})
        self.assertEqual(next(r for r in t["files"] if r["path"] == "core/a.py")["dependents"]["direct"], 1)


class BranchSemanticsTest(Repo):
    def test_changes_made_on_the_other_side_do_not_count(self):
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"core/a.py": (self.root / "core/a.py").read_text() + "\n\ndef t():\n    return 1\n"}, CAROL, 0.5, "feat: topic")
        git(self.root, "checkout", "-q", "main")
        self.commit({"util/only_on_main.py": "x = 1\n"}, ALICE, 0.2, "feat: main moves on")
        git(self.root, "checkout", "-q", "topic")
        t = self.triage("main")
        self.assertEqual([r["path"] for r in t["files"]], ["core/a.py"])  # judged from where topic parted from main, as a pull request is

    def test_the_author_is_not_offered_as_their_own_reviewer(self):
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"core/a.py": (self.root / "core/a.py").read_text() + "\n\ndef t():\n    return 1\n"}, ALICE, 0.5, "feat: alice again")
        t = self.triage("main")
        self.assertEqual(t["change"]["authors"], ["Alice Adams"])
        self.assertEqual(t["reviewers"], [])
        self.assertEqual(t["nobody_else_can_look"], ["core/a.py"])
        self.assertNotIn("author is not among the owners", t["files"][0]["flags"])


class OrderTest(Repo):
    def test_recent_activity_outranks_size_when_nothing_was_fixed(self):
        git(self.root, "checkout", "-q", "main")
        self.commit({"util/e.py": "e = 1\n"}, ALICE, 10, "feat: e")
        self.commit({"util/e.py": "e = 1\ne2 = 2\n"}, ALICE, 5, "feat: e again")
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"util/e.py": "e = 1\ne2 = 2\ne3 = 3\n", "util/c.py": (self.root / "util/c.py").read_text() + "".join(f"c{i} = {i}\n" for i in range(8))}, CAROL, 0.5, "feat: both")
        t = self.triage("main")
        by = {r["path"]: r for r in t["files"]}
        self.assertEqual((by["util/e.py"]["lines"], by["util/c.py"]["lines"]), (1, 8))
        self.assertEqual((by["util/e.py"]["commits_active"], by["util/c.py"]["commits_active"]), (2, 0))
        self.assertEqual([r["path"] for r in t["files"]], ["util/e.py", "util/c.py"])
        self.assertEqual([r["tier"] for r in t["files"]], ["busy", "quiet"])

    def test_fix_history_is_shown_but_does_not_reorder(self):
        git(self.root, "checkout", "-q", "main")
        for days, message in ((30, "feat: x1"), (20, "feat: x2"), (10, "feat: x3")):
            self.commit({"util/x.py": f"x = {days}\n"}, ALICE, days, message)
        for days, message in ((25, "fix: y1"), (15, "fix: y2")):
            self.commit({"util/y.py": f"y = {days}\n"}, ALICE, days, message)
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"util/x.py": "x = 0\n", "util/y.py": "y = 0\n"}, CAROL, 0.5, "feat: both")
        t = self.triage("main")
        by = {r["path"]: r for r in t["files"]}
        self.assertEqual((by["util/x.py"]["commits_active"], by["util/x.py"]["fixes_90"]), (3, 0))
        self.assertEqual((by["util/y.py"]["commits_active"], by["util/y.py"]["fixes_90"]), (2, 2))
        self.assertEqual([r["path"] for r in t["files"]], ["util/x.py", "util/y.py"])  # more activity first, however many of them were fixes
        self.assertEqual(t["summary"]["recently_fixed"], 1)

    def test_a_package_init_running_on_the_way_is_not_a_dependent(self):
        git(self.root, "checkout", "-q", "-b", "topic")
        self.commit({"core/__init__.py": "VERSION = 1\n"}, CAROL, 0.5, "feat: version")
        t = self.triage("main")
        self.assertEqual(t["files"][0]["dependents"], {"direct": 0, "within_2": 0})  # `from core import a` names a.py, not core/__init__.py
        self.assertEqual(t["summary"]["ripple"], {"direct": 0, "second": 0})


class UncommittedTest(Repo):
    def test_uncommitted_work_is_triaged_against_head(self):
        (self.root / "core/a.py").write_text((self.root / "core/a.py").read_text() + "\n\ndef extra():\n    return 9\n")
        (self.root / "core/new.py").write_text("x = 1\ny = 2\n")
        t = triage.compute(self.root, config.load(self.root), "HEAD", now=self.now)
        by = {r["path"]: r for r in t["files"]}
        self.assertTrue(t["change"]["uncommitted"])
        self.assertEqual(t["change"]["authors"], ["Dana Doe"])  # whoever is configured here wrote it
        self.assertEqual((by["core/a.py"]["added"], by["core/a.py"]["fixes_90"]), (4, 2))
        self.assertEqual((by["core/new.py"]["added"], by["core/new.py"]["change"]), (2, "added"))

    def test_without_since_the_change_is_judged_against_the_default_branch(self):
        (self.root / "core/a.py").write_text((self.root / "core/a.py").read_text() + "\n\ndef extra():\n    return 9\n")
        code, out, _ = run_cli("triage", "--repo", str(self.root), "--format", "json")
        data = json.loads(out)  # on main itself, that is the uncommitted work
        self.assertEqual((code, data["change"]["since"], data["change"]["uncommitted"], [r["path"] for r in data["files"]]), (0, "main", True, ["core/a.py"]))
        git(self.root, "checkout", "-q", "--", "core/a.py")
        self.feature()
        code, out, _ = run_cli("triage", "--repo", str(self.root), "--format", "json")
        data = json.loads(out)  # on a branch, the branch against main
        self.assertEqual((code, data["change"]["since"], data["change"]["authors"]), (0, "main", ["Carol Chen"]))
        self.assertEqual(sorted(r["path"] for r in data["files"]), ["core/a.py", "core/b.py", "core/d.py", "util/c.py"])

    def test_a_clean_tree_has_nothing_to_triage(self):
        t = triage.compute(self.root, config.load(self.root), "HEAD", now=self.now)
        self.assertEqual((t["files"], t["summary"]["files"]), ([], 0))
        self.assertIn("No code changed", triage.markdown(t))

    def test_unknown_refs_and_non_repositories_are_refused(self):
        with self.assertRaises(triage.TriageError) as ctx:
            triage.compute(self.root, config.load(self.root), "nowhere", now=self.now)
        self.assertIn("nowhere", str(ctx.exception))

    def test_triage_needs_git(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(triage.TriageError) as ctx:
                triage.compute(Path(d), config.load(Path(d)), "HEAD")
        self.assertIn("git", str(ctx.exception))


class CliTest(Repo):
    def setUp(self):
        super().setUp()
        self.feature()

    def test_markdown_and_json(self):
        code, out, _ = run_cli("triage", "--repo", str(self.root), "--since", "main")
        self.assertEqual(code, 0)
        self.assertIn("# Change triage", out)
        code, out, _ = run_cli("triage", "--repo", str(self.root), "--since", "main", "--format", "json")
        data = json.loads(out)
        self.assertEqual((data["kind"], data["files"][0]["path"], data["schema_version"]), ("triage", "core/a.py", 1))

    def test_limit_caps_the_table_not_the_json(self):
        _, out, _ = run_cli("triage", "--repo", str(self.root), "--since", "main", "--limit", "1")
        self.assertIn("3 more files in the JSON output", out)
        self.assertIn("`core/a.py`", out)
        self.assertNotIn("`core/b.py`", out)  # ranked last

    def test_a_bad_ref_is_an_error_not_a_traceback(self):
        code, out, err = run_cli("triage", "--repo", str(self.root), "--since", "nowhere")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("nowhere", err)

    def test_it_can_be_written_to_a_file(self):
        target = self.root / "out" / "triage.json"
        code, out, err = run_cli("triage", "--repo", str(self.root), "--since", "main", "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(target.read_text())["kind"], "triage")


if __name__ == "__main__":
    unittest.main()
