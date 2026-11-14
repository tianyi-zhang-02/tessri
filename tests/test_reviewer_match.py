"""`tools/reviewer_match.py`: "who can look" against who reviewed, on a small history with known reviews, and the
pieces behind the numbers: the identity match, the metrics, the gatekeeper baseline."""

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import TempRepo, git, write_tree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import reviewer_match as rm  # noqa: E402  (tools/ is not a package)

ALICE, BOB, CARA = ("Alice Adams", "alice@example.com"), ("Bob Brown", "12345+bbrown@users.noreply.github.com"), ("Cara Cole", "cara@example.com")
IDENTITIES = {"alice": {"names": ["Alice Adams"], "emails": ["alice@example.com"]}, "bbrown": {"names": [], "emails": ["12345+bbrown@users.noreply.github.com"]}, "ccole": {"names": ["Cara Cole"], "emails": []}}


class MatchTest(unittest.TestCase):
    def test_a_git_name_finds_its_login_by_name_login_or_address(self):
        match = rm.matcher(IDENTITIES)
        self.assertEqual(match("Alice Adams"), "alice")
        self.assertEqual(match("alice"), "alice")  # the login itself, as a commit name
        self.assertEqual(match("Bob Brown"), None)  # no name on file, and the address only gives the login
        self.assertEqual(match("bbrown"), "bbrown")
        self.assertEqual(match("Cara  COLE"), "ccole")
        self.assertIsNone(match("Dan"))  # too short to match anything by accident


class MetricsTest(unittest.TestCase):
    rows = [
        {"files": 3, "actual": ["a", "b"], "requested": [], "authors": ["x"], "tessri": ["a", "c", "d"], "recent": ["c"]},
        {"files": 1, "actual": ["a"], "requested": ["a"], "authors": ["y"], "tessri": [], "recent": ["b", "a"]},
        {"files": 0, "actual": ["a"], "requested": [], "authors": ["z"], "tessri": ["a"], "recent": ["a"]},  # no code file: not judged
        {"files": 2, "actual": [], "requested": [], "authors": ["x"], "tessri": ["a"], "recent": ["a"]},  # nobody reviewed: not judged
    ]

    def test_precision_recall_hit_at_1_and_any_hit_over_the_judged_pull_requests(self):
        m = rm.metrics(self.rows, "tessri")
        self.assertEqual((m["judged"], m["offered"]), (2, 1))
        self.assertEqual((m["precision"], m["recall"], m["hit_at_1"], m["any_hit"]), (round(1 / 3, 3), 0.5, 1.0, 1.0))
        m = rm.metrics(self.rows, "recent")
        self.assertEqual((m["judged"], m["offered"]), (2, 2))
        self.assertEqual((m["precision"], m["recall"], m["hit_at_1"], m["any_hit"]), (0.25, 0.5, 0.0, 0.5))
        self.assertEqual(rm.metrics(self.rows, "tessri", "requested")["offered"], 0)
        self.assertIsNone(rm.metrics(self.rows, "tessri", "requested")["precision"])

    def test_the_gatekeepers_are_the_frequent_past_reviewers_once_there_is_a_past(self):
        rows = [{"actual": ["a"], "authors": ["q"]}] + [{"actual": ["a", "b"], "authors": ["a"]} for _ in range(12)]  # newest first
        rm.gatekeepers(rows, k=2, min_past=20)
        self.assertEqual(rows[0]["gatekeepers"], ["a", "b"])  # 24 slots before it
        self.assertEqual(rows[1]["gatekeepers"], ["b"])  # 22 slots before it; a is this pull request's author
        self.assertEqual(rows[3]["gatekeepers"], [])  # 18 slots: not enough


class Pulls(TempRepo):
    """Alice maintains a.py through 2025 and early 2026; Bob maintains b.py; Bob's "pull request" changes a.py and is
    reviewed by Alice; a later docs-only pull request by Cara is reviewed by Bob. Dates are days apart so that Alice
    is active at the merge and the year window holds her commits."""

    def setUp(self):
        super().setUp()
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, {"a.py": "X = 1\n", "b.py": "import a\n", "README.md": "hi\n"})
        self.commit("start", "2025-11-01T12:00:00Z", ALICE)
        for n, day in enumerate(("2025-12-01", "2026-01-05", "2026-02-10", "2026-03-15")):
            write_tree(self.root, {"a.py": f"X = {n + 2}\n"})
            self.commit(f"a again {n}", f"{day}T12:00:00Z", ALICE)
        write_tree(self.root, {"b.py": "import a\nY = a.X\n"})
        self.commit("b", "2026-03-20T12:00:00Z", BOB)
        write_tree(self.root, {"a.py": "X = 9\n"})
        self.commit("feat: a by bob (#1)", "2026-04-01T12:00:00Z", BOB)
        self.pr1 = self.sha("HEAD")
        write_tree(self.root, {"README.md": "docs (#2)\n"})
        self.commit("docs (#2)", "2026-04-05T12:00:00Z", CARA)
        self.pr2 = self.sha("HEAD")

    def commit(self, subject: str, when: str, who: tuple[str, str]) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", subject, when=when, author=who)

    def sha(self, rev: str) -> str:
        return subprocess.run(["git", "rev-parse", rev], cwd=self.root, capture_output=True, text=True, check=True).stdout.strip()

    def payload(self, path: str):
        """A stand-in for the GitHub API: two closed pull requests, one of them not merged, with reviews and commits."""
        if path.startswith("repos/o/r/pulls?"):
            if path.endswith("&page=1"):
                return [
                    {"number": 2, "title": "docs", "user": {"login": "ccole"}, "merged_at": "2026-04-05T13:00:00Z", "merge_commit_sha": self.pr2, "requested_reviewers": [{"login": "alice"}]},
                    {"number": 3, "title": "closed, not merged", "user": {"login": "ccole"}, "merged_at": None, "merge_commit_sha": "0" * 40, "requested_reviewers": []},
                    {"number": 1, "title": "feat: a", "user": {"login": "bbrown"}, "merged_at": "2026-04-01T13:00:00Z", "merge_commit_sha": self.pr1, "requested_reviewers": []},
                    {"number": 4, "title": "elsewhere", "user": {"login": "x"}, "merged_at": "2026-04-02T13:00:00Z", "merge_commit_sha": "1" * 40, "requested_reviewers": []},
                ]
            return []
        if path == "repos/o/r/pulls/1/reviews?per_page=100":
            return [{"user": {"login": "alice"}, "state": "APPROVED", "submitted_at": "2026-04-01T12:30:00Z"}, {"user": {"login": "bbrown"}, "state": "COMMENTED", "submitted_at": "2026-04-01T12:40:00Z"}, {"user": {"login": "svcnvidia-nemo-ci"}, "state": "COMMENTED", "submitted_at": "2026-04-01T12:41:00Z"}]
        if path == "repos/o/r/pulls/2/reviews?per_page=100":
            return [{"user": {"login": "bbrown"}, "state": "APPROVED", "submitted_at": "2026-04-05T12:30:00Z"}]
        if path == "repos/o/r/pulls/1/commits?per_page=100":
            return [{"author": {"login": "bbrown"}, "commit": {"author": {"name": BOB[0], "email": BOB[1]}}}]
        if path == "repos/o/r/pulls/2/commits?per_page=100":
            return [{"author": {"login": "ccole"}, "commit": {"author": {"name": CARA[0], "email": CARA[1]}}}]
        if path == "users/alice":
            return {"login": "alice", "name": "Alice Adams"}
        raise rm.ReviewerMatchError(f"unexpected call {path}")


class CollectTest(Pulls):
    def test_merged_pull_requests_in_the_local_history_with_reviews_and_identities(self):
        data = rm.collect("o/r", self.root, api=self.payload)
        self.assertEqual([p["number"] for p in data["pulls"]], [2, 1])  # newest merge first; #3 was not merged, #4 is not in this history
        one = data["pulls"][1]
        self.assertEqual((one["merge"], one["base"]), (self.pr1, self.sha(f"{self.pr1}^1")))
        self.assertEqual([r["login"] for r in one["reviews"]], ["alice", "bbrown", "svcnvidia-nemo-ci"])
        self.assertEqual(one["commit_authors"], [{"login": "bbrown", "name": "Bob Brown", "email": BOB[1]}])
        self.assertEqual(data["identities"]["alice"], {"names": ["Alice Adams"], "emails": []})  # from the profile: she authored nothing here
        self.assertEqual(data["identities"]["bbrown"]["emails"], [BOB[1]])
        self.assertEqual(data["pulls"][0]["requested"], ["alice"])
        with self.assertRaises(rm.ReviewerMatchError):
            rm.collect("o/r", self.root, api=lambda path: [] if "pulls?" in path else {})


class ScoreTest(Pulls):
    def test_triage_names_the_maintainer_who_reviewed_and_a_docs_change_is_not_judged(self):
        data = rm.collect("o/r", self.root, api=self.payload)
        result = rm.score(data, self.root)
        self.assertEqual(result["pulls"], dict(result["pulls"], count=2, scored=2, errors=[], reviewed=2, no_code=1, judged=1))
        one = next(r for r in result["rows"] if r["number"] == 1)
        self.assertEqual((one["files"], one["actual"], one["authors"]), (1, ["alice"], ["bbrown"]))  # the service account is not a reviewer
        self.assertEqual((one["tessri_names"], one["tessri"], one["unmatched"]), (["Alice Adams"], ["alice"], []))
        self.assertEqual((one["recent"], one["usual"], one["gatekeepers"]), (["alice"], ["alice"], []))  # too little review history for gatekeepers
        by = {m["method"]: m for m in result["methods"]}
        self.assertEqual((by["tessri"]["offered"], by["tessri"]["precision"], by["tessri"]["recall"], by["tessri"]["hit_at_1"], by["tessri"]["any_hit"]), (1, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(by["gatekeepers"]["offered"], 0)
        self.assertEqual(result["reviewers"], {"distinct": 1, "top": [{"login": "alice", "share": 1.0}], "only_top3_share": 1.0})
        self.assertEqual(result["overlap"], {"both": 1, "tessri_only": 0, "recent_only": 0, "neither": 0})
        self.assertEqual(subprocess.run(["git", "worktree", "list"], cwd=self.root, capture_output=True, text=True).stdout.count("\n"), 1)  # the scoring worktree is gone
        rendered = rm.text(result)
        self.assertIn("Tessri reviewer match on o/r (2 merged pull requests, 2026-04-01 to 2026-04-05)", rendered)
        self.assertIn("triage: active holders of the changed files", rendered)
        self.assertIn("1 of 1", rendered)

    def test_the_command_line(self):
        data = rm.collect("o/r", self.root, api=self.payload)
        pulls = self.root.parent / f"{self.root.name}-pulls.json"
        pulls.write_text(json.dumps(data))
        self.addCleanup(pulls.unlink)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rm.main(["score", str(pulls), str(self.root), "--format", "json"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["pulls"]["judged"], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rm.main(["score", str(pulls), str(self.root / "nowhere")]), 1)


if __name__ == "__main__":
    unittest.main()
