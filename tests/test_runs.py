"""`tessri.runs`: a JUnit report the host wrote, read into the repository's test files and their outcomes, and the
candidate tests held against it."""

import tempfile
import unittest
from pathlib import Path

from tessri import runs

FILES = {"tests/test_engine.py", "tests/sub/__init__.py", "tests/sub/test_deep.py", "src/app.test.ts", "core/engine.py"}

PYTEST = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="6">
    <testcase classname="tests.test_engine" name="test_run" time="0.001"/>
    <testcase classname="tests.test_engine.EngineTest" name="test_fail"><failure message="boom">trace</failure></testcase>
    <testcase classname="tests.test_engine.EngineTest" name="test_skip"><skipped message="later"/></testcase>
    <testcase classname="tests.sub.test_deep.DeepTest" name="test_err"><error message="bad">trace</error></testcase>
    <testcase classname="tests.sub" name="test_in_the_package"/>
    <testcase classname="elsewhere.test_other" name="test_nowhere"/>
  </testsuite>
</testsuites>
"""

JEST = """<testsuites name="jest tests">
  <testsuite name="app" file="/home/ci/work/repo/src/app.test.ts" tests="2">
    <testcase classname="app renders" name="renders"/>
    <testcase classname="app renders" name="renders twice" file=".\\src\\app.test.ts"/>
  </testsuite>
  <testsuite name="lone" tests="1">
    <testcase classname="lone case" name="runs"/>
  </testsuite>
</testsuites>
"""


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def report(self, name, text):
        p = self.dir / name
        p.write_text(text)
        return p

    def test_pytest_cases_are_matched_by_classname(self):
        r = runs.read(self.report("junit.xml", PYTEST), FILES)
        self.assertEqual(r["cases"], 6)
        self.assertEqual(r["files"]["tests/test_engine.py"], {"passed": 1, "failed": 1, "skipped": 1})
        self.assertEqual(r["files"]["tests/sub/test_deep.py"], {"passed": 0, "failed": 1, "skipped": 0})  # an error is a failure
        self.assertEqual(r["files"]["tests/sub/__init__.py"], {"passed": 1, "failed": 0, "skipped": 0})  # a package name
        self.assertEqual(r["unmatched"], {"cases": 1, "named": ["elsewhere.test_other"]})

    def test_file_attributes_win_and_suffixes_and_backslashes_are_read(self):
        r = runs.read(self.report("jest.xml", JEST), FILES)
        self.assertEqual(r["files"], {"src/app.test.ts": {"passed": 2, "failed": 0, "skipped": 0}})  # the suite's absolute path, the case's relative one
        self.assertEqual(r["unmatched"], {"cases": 1, "named": ["lone case"]})

    def test_a_single_suite_root_is_a_report_too(self):
        r = runs.read(self.report("one.xml", '<testsuite name="s" file="tests/test_engine.py"><testcase name="a"/></testsuite>'), FILES)
        self.assertEqual(r["files"], {"tests/test_engine.py": {"passed": 1, "failed": 0, "skipped": 0}})

    def test_what_is_not_a_report_is_refused_with_the_reason(self):
        with self.assertRaises(runs.RunsError) as cm:
            runs.read(self.report("notes.xml", "<notes><note/></notes>"), FILES)
        self.assertIn("not a JUnit report", str(cm.exception))
        with self.assertRaises(runs.RunsError) as cm:
            runs.read(self.report("junk.xml", "not xml at all"), FILES)
        self.assertIn("not JUnit XML", str(cm.exception))
        with self.assertRaises(runs.RunsError) as cm:
            runs.read(self.dir / "missing.xml", FILES)
        self.assertIn("missing.xml", str(cm.exception))

    def test_reports_merge_and_candidates_are_held_against_them(self):
        a = runs.read(self.report("a.xml", PYTEST), FILES)
        b = runs.read(self.report("b.xml", JEST), FILES)
        merged = runs.load([self.dir / "a.xml", "b.xml"], FILES, base=self.dir)
        self.assertEqual(merged["sources"], [str(self.dir / "a.xml"), str(self.dir / "b.xml")])
        self.assertEqual(merged["cases"], a["cases"] + b["cases"])
        self.assertEqual(merged["unmatched"], {"cases": 2, "named": ["elsewhere.test_other", "lone case"]})
        held = runs.against(merged, ["tests/test_engine.py", "tests/sub/test_deep.py", "tests/test_missing.py", "src/app.test.ts"])
        self.assertEqual(held["ran"], {"tests/test_engine.py": "failed", "tests/sub/test_deep.py": "failed", "src/app.test.ts": "passed"})
        self.assertEqual((held["passed"], held["failed"], held["skipped"], held["not_run"]), (1, ["tests/test_engine.py", "tests/sub/test_deep.py"], 0, ["tests/test_missing.py"]))
        only_skipped = runs.against({"sources": [], "cases": 1, "files": {"t.py": {"passed": 0, "failed": 0, "skipped": 1}}, "unmatched": {"cases": 0, "named": []}}, ["t.py"])
        self.assertEqual((only_skipped["ran"], only_skipped["skipped"]), ({"t.py": "skipped"}, 1))


if __name__ == "__main__":
    unittest.main()
