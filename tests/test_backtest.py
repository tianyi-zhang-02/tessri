"""`tools/backtest.py`: the order `triage` uses and the import graph's co-change claim, measured on a small history
with known outcomes, and the statistic behind the numbers."""

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

import backtest  # noqa: E402  (tools/ is not a package)

DAY = backtest.DAY


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = backtest.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class AucTest(unittest.TestCase):
    def test_perfect_inverse_tied_and_undefined(self):
        self.assertEqual(backtest.auc([((2,), True), ((1,), False), ((0,), False)]), 1.0)
        self.assertEqual(backtest.auc([((0,), True), ((1,), False), ((2,), False)]), 0.0)
        self.assertEqual(backtest.auc([((1,), True), ((1,), False), ((1,), False)]), 0.5)
        self.assertAlmostEqual(backtest.auc([((5,), True), ((5,), False), ((1,), False), ((9,), False)]), 0.5)  # above 1, tied with 5, below 9
        self.assertEqual(backtest.auc([((3, 1), True), ((0, 20), False), ((0, 1), False)]), 1.0)  # tuples sort in order
        self.assertIsNone(backtest.auc([((1,), True)]))
        self.assertIsNone(backtest.auc([((1,), False), ((2,), False)]))
        self.assertIsNone(backtest.auc([]))


class RowsTest(unittest.TestCase):
    def test_a_row_uses_only_what_git_knew_at_the_change(self):
        t = 1_800_000_000
        change = backtest.Change("c", t, "change", {"a.py": 7, "b.py": 1})
        touches = {"a.py": sorted([t - 90 * DAY, t - 1, t, t + 5]), "b.py": [t - 91 * DAY]}
        fixes = {"a.py": [t, t + 30 * DAY], "b.py": [t + 30 * DAY + 1]}
        rows = backtest.rows_of(change, touches, fixes, window=30, active=90)
        self.assertEqual(rows[0], backtest.Row("c", "a.py", 7, 2, 0, True))  # the window before is [t - 90 d, t): the change itself is not activity
        self.assertEqual(rows[1], backtest.Row("c", "b.py", 1, 0, 0, False))  # a fix a second after the window is not an outcome

    def test_the_months_are_the_last_complete_ones(self):
        start = 1_700_000_000
        found = [backtest.Change(f"c{i}", start + i * 10 * DAY, "x") for i in range(40)]  # 400 days, one change every ten
        chosen = backtest.select(found, months=2, window=30, active=90)
        self.assertEqual(len(chosen), 2)
        last = max(c.when for month in chosen.values() for c in month)
        self.assertLessEqual(last, found[-1].when - 30 * DAY)
        everything = backtest.select(found, months=0, window=30, active=90)
        first = min(c.when for month in everything.values() for c in month)
        self.assertGreaterEqual(first, found[0].when + 90 * DAY)
        self.assertEqual(sorted(everything)[-2:], sorted(chosen))
        with self.assertRaises(backtest.BacktestError):
            backtest.select(found, months=0, window=300, active=200)


class History(TempRepo):
    """a.py is busy (three commits in the 90 days before the change) and gets a fix ten days after it; lib/d.py gets
    the largest edit and no fix; b.py imports a. The last commit closes the outcome window. All at the top or in
    lib/, so that the pairs the change touches are one import apart (a, b) or unrelated (a and b with d)."""

    def setUp(self):
        super().setUp()
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, {"a.py": "X = 1\n", "b.py": "import a\n", "c.py": "Y = 1\n", "lib/d.py": "Z = 1\n", "lib/e.py": "W = 1\n"})
        self.commit("start", "2026-01-01T12:00:00Z")
        for day in ("2026-02-01", "2026-02-10", "2026-02-20"):
            write_tree(self.root, {"a.py": f"X = 1  # {day}\n"})
            self.commit("touch a", f"{day}T12:00:00Z")
        write_tree(self.root, {"a.py": "X = 2\n", "b.py": "import a\nprint(a.X)\n", "lib/d.py": "Z = 1\n" + "".join(f"V{i} = {i}\n" for i in range(20))})
        self.commit("change a, b and d", "2026-04-10T12:00:00Z")
        write_tree(self.root, {"a.py": "X = 3\n"})
        self.commit("fix: a", "2026-04-20T12:00:00Z")
        write_tree(self.root, {"README.md": "later\n"})
        self.commit("later", "2026-05-15T12:00:00Z")

    def commit(self, subject: str, when: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", subject, when=when)


class OrderTest(History):
    def test_the_busy_file_is_the_one_fixed_and_the_order_says_so(self):
        result = backtest.run(self.root, graph=False)
        self.assertEqual(result["rows"], {"count": 3, "changes": 1, "months": ["2026-04"], "fixed": 1})
        self.assertNotIn("cochange", result)
        by_name = {o["order"]: o for o in result["orders"]}
        triage = by_name["activity, then size (triage)"]
        self.assertEqual((triage["pooled"], triage["mean_of_months"], triage["months"]), (1.0, 1.0, {"2026-04": 1.0}))
        self.assertEqual((triage["ahead_of_size"], triage["months_compared"]), (1, 1))
        self.assertEqual(triage["within_change"], {"mean": 1.0, "changes": 1})
        self.assertEqual(by_name["size"]["pooled"], 0.5)  # d's 20 lines sort above a's 2, b's 1 below
        self.assertEqual(by_name["size"]["within_change"], {"mean": 0.5, "changes": 1})
        self.assertEqual(by_name["activity"]["pooled"], 1.0)
        self.assertEqual(by_name["fixes, then activity, then size"]["pooled"], 1.0)  # nothing was a fix before, so activity decides
        self.assertNotIn("dependents, then size", by_name)  # needs the graph
        self.assertEqual(result["history"], {"first": "2026-01-01", "last": "2026-05-15", "changes": 7})
        self.assertEqual(result["settings"]["fix_subject"], backtest.gitlog.FIX_SUBJECT.pattern)

    def test_pairs_one_import_apart_changed_together_more_than_unrelated_ones(self):
        result = backtest.run(self.root)
        month = result["cochange"]["months"]["2026-04"]
        base = subprocess.run(["git", "rev-parse", "HEAD~3"], cwd=self.root, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(month["tree"], base)  # the tree before the month's first change: the last "touch a"
        self.assertEqual((month["files"], month["changes"], month["bulk"]), (5, 1, 0))
        self.assertEqual(month["pairs"], {"one import apart": 1, "two imports apart": 0, "same directory": 3, "unrelated": 6})
        self.assertEqual(month["cochanged"], {"one import apart": 1, "two imports apart": 0, "same directory": 0, "unrelated": 2})
        pooled = {e["pairs"]: e for e in result["cochange"]["pooled"]}
        self.assertEqual((pooled["one import apart"]["rate"], pooled["one import apart"]["ratio"]), (1.0, 3.0))
        self.assertEqual(pooled["one import apart"]["ratio_range"], [3.0, 3.0])
        self.assertEqual((pooled["same directory"]["rate"], pooled["same directory"]["ratio"]), (0.0, 0.0))
        self.assertEqual((pooled["two imports apart"]["rate"], pooled["two imports apart"]["ratio"], pooled["two imports apart"]["ratio_range"]), (None, None, None))
        self.assertAlmostEqual(pooled["unrelated"]["rate"], 1 / 3)
        self.assertEqual(result["cochange"]["bulk"], backtest.BULK)
        by_name = {o["order"]: o for o in result["orders"]}
        self.assertEqual(by_name["dependents, then size"]["pooled"], 1.0)  # b imports a, nothing imports b or d
        self.assertEqual(len(by_name), len(backtest.ORDERS))

    def test_the_command_prints_text_or_json_and_says_why_it_cannot(self):
        code, out, err = run_main(str(self.root), "--no-graph")
        self.assertEqual(code, 0, err)
        self.assertIn("Tessri backtest of ", out)
        self.assertIn("Rows: 3 code files touched by 1 change in 1 month (2026-04); the outcome, a fix or revert commit touching the\nfile within 30 days, holds for 33% of them.", out)
        self.assertIn("activity, then size (triage)", out)
        self.assertIn("1 of 1", out)
        self.assertNotIn("Pairs", out)
        target = self.root / "out.json"
        code, out, err = run_main(str(self.root), "--format", "json", "--out", str(target), "--months", "1")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("backtest: graph at 2026-04 (1 of 1)", err)
        found = json.loads(target.read_text())
        self.assertEqual((found["kind"], found["rows"]["count"]), ("backtest", 3))
        self.assertEqual([e["pairs"] for e in found["cochange"]["pooled"]], list(backtest.PAIRS))
        code, out, err = run_main(str(self.root), "--window", "60")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "backtest: no change has 90 days of history before it and 60 days after it; the history spans 2026-01-01 to 2026-05-15\n")
        code, _, err = run_main(str(self.root / "nope"))
        self.assertEqual(code, 1)
        self.assertIn("not a directory", err)
        code, _, err = run_main(str(self.root), "--rev", "nothing")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("backtest: "), err)


if __name__ == "__main__":
    unittest.main()
