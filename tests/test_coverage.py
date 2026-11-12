"""`tessri.coverage`: a coverage report the host wrote, read into the lines it executed and missed per file of the
repository, the lines a change added or changed, and the one held against the other."""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import TempRepo, git, write_tree
from tessri import coverage

FILES = {"pkg/__init__.py", "pkg/core.py", "pkg/util.py", "tests/test_core.py"}
CORE = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
CORE2 = "def a():\n    return 1\n\n\ndef b():\n    # changed\n    return 3\n\n\ndef c():\n    x = 1\n    return x\n"
HITS = {1: 1, 2: 1, 5: 1, 7: 1, 10: 1, 11: 0, 12: 0}  # the statements of CORE2 as one run of `tests/test_core.py` left them
EXECUTED, MISSING = {1, 2, 5, 7, 10}, {11, 12}

COBERTURA = '<?xml version="1.0" ?>\n<coverage version="7.6" line-rate="0.71">\n<sources><source>/build/src</source></sources>\n<packages><package name="pkg"><classes><class name="core.py" filename="pkg/core.py"><methods/><lines>\n' + "".join(f'<line number="{n}" hits="{h}"/>\n' for n, h in HITS.items()) + "</lines></class></classes></package></packages>\n</coverage>\n"
CLOVER = '<?xml version="1.0" encoding="UTF-8"?>\n<coverage generated="1" clover="3.2.0"><project timestamp="1" name="All files"><metrics statements="7"/>\n<file name="core.py" path="/build/src/pkg/core.py"><metrics/>\n' + "".join(f'<line num="{n}" count="{h}" type="stmt"/>\n' for n, h in HITS.items()) + "</file></project></coverage>\n"
LCOV = "TN:\nSF:/build/src/pkg/core.py\n" + "".join(f"DA:{n},{h}\n" for n, h in HITS.items()) + "LF:7\nLH:5\nend_of_record\n"
COVJSON = json.dumps({"meta": {"format": 3}, "files": {"pkg/core.py": {"executed_lines": sorted(EXECUTED), "missing_lines": sorted(MISSING), "excluded_lines": []}}, "totals": {}})


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def report(self, name, text):
        p = self.dir / name
        p.write_text(text)
        return p

    def test_cobertura_clover_lcov_and_coverage_json_read_alike(self):
        for name, text in (("coverage.xml", COBERTURA), ("clover.xml", CLOVER), ("lcov.info", LCOV), ("coverage.json", COVJSON)):
            r = coverage.read(self.report(name, text), FILES)
            self.assertEqual((r["source"], r["files"], r["unmatched"]), (str(self.dir / name), {"pkg/core.py": {"executed": EXECUTED, "missing": MISSING}}, {"files": 0, "named": []}), name)

    def test_names_are_matched_by_their_longest_suffix_and_the_rest_counted(self):
        text = "SF:C:\\build\\src\\pkg\\core.py\nDA:1,1\nDA:2,0\nend_of_record\nSF:/elsewhere/nothing.py\nDA:1,1\nend_of_record\n"
        r = coverage.read(self.report("lcov.info", text), FILES)
        self.assertEqual(r["files"], {"pkg/core.py": {"executed": {1}, "missing": {2}}})
        self.assertEqual(r["unmatched"], {"files": 1, "named": ["/elsewhere/nothing.py"]})

    def test_reports_merge_as_one_run(self):
        first = self.report("a.json", json.dumps({"files": {"pkg/core.py": {"executed_lines": [1, 2], "missing_lines": [5, 7, 10, 11, 12]}}}))
        second = self.report("b.json", json.dumps({"files": {"pkg/core.py": {"executed_lines": [5, 7, 10], "missing_lines": [1, 2, 11, 12]}, "pkg/util.py": {"executed_lines": [1], "missing_lines": []}}}))
        merged = coverage.load([first, second], FILES)
        self.assertEqual(merged["sources"], [str(first), str(second)])
        self.assertEqual(merged["files"], {"pkg/core.py": {"executed": EXECUTED, "missing": MISSING}, "pkg/util.py": {"executed": {1}, "missing": set()}})
        self.assertEqual(coverage.load(["b.json"], FILES, base=self.dir)["files"]["pkg/util.py"], {"executed": {1}, "missing": set()})  # relative under the base

    def test_what_is_not_a_report_is_refused_with_the_reason(self):
        for name, text, reason in (
            ("junit.xml", '<testsuites><testsuite name="s"/></testsuites>', "the root element is `testsuites`"),
            ("empty.xml", "<coverage/>", "no lines under `class` or `file` elements"),
            ("broken.xml", "<coverage>", "not well-formed XML"),
            ("other.json", '{"a": 1}', "JSON without `files` of `executed_lines`"),
            ("bad.json", "{bad", "not JSON"),
            ("bare.info", "TN:\nSF:pkg/core.py\nend_of_record\n", "lcov without `DA:` lines"),
            ("notes.txt", "hello\n", "neither Cobertura or Clover XML, lcov nor coverage.py's JSON"),
        ):
            with self.assertRaises(coverage.CoverageError) as caught:
                coverage.read(self.report(name, text), FILES)
            self.assertIn(reason, str(caught.exception), name)
            self.assertTrue(str(caught.exception).startswith(str(self.dir / name)), str(caught.exception))
        with self.assertRaises(coverage.CoverageError) as caught:
            coverage.read(self.dir / "missing.xml", FILES)
        self.assertIn("missing.xml", str(caught.exception))

    def test_a_hit_count_that_is_not_a_number_counts_as_none(self):
        text = '<coverage><packages><package><classes><class filename="pkg/core.py"><lines><line number="1" hits="2.0"/><line number="2" hits="?"/></lines></class></classes></package></packages></coverage>'
        self.assertEqual(coverage.read(self.report("odd.xml", text), FILES)["files"], {"pkg/core.py": {"executed": {1}, "missing": {2}}})

    def test_ranges_and_their_text(self):
        self.assertEqual(coverage.ranges([10, 9, 1, 2, 3, 7]), [[1, 3], [7, 7], [9, 10]])
        self.assertEqual(coverage.spans([[1, 3], [7, 7], [9, 10]]), "1-3, 7, 9-10")
        self.assertEqual((coverage.ranges([]), coverage.spans([])), ([], ""))

    def test_the_changed_lines_are_held_against_the_report(self):
        report = coverage.merge([coverage.read(self.report("coverage.xml", COBERTURA), FILES)])
        held = coverage.against(report, {"pkg/core.py": {6, 7, 8, 9, 10, 11, 12}, "pkg/fresh.py": {1, 2}})
        self.assertEqual(held["files"], {"pkg/core.py": {"changed": 7, "statements": 4, "ran": 2, "not_run": 2, "not_run_ranges": [[11, 12]]}})  # 6, 8 and 9 are a comment and blank lines: no statement
        self.assertEqual(held["not_measured"], {"pkg/fresh.py": 2})
        self.assertEqual({k: held[k] for k in ("sources", "measured", "changed", "statements", "ran", "not_run", "unmatched")}, {"sources": [str(self.dir / "coverage.xml")], "measured": 1, "changed": 9, "statements": 4, "ran": 2, "not_run": 2, "unmatched": {"files": 0, "named": []}})


class ChangedLinesTest(TempRepo):
    def test_the_new_side_of_every_hunk_and_whole_new_files(self):
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, {"pkg/__init__.py": "", "pkg/core.py": CORE, "pkg/old.py": "O = 1\nP = 2\nQ = 3\nR = 4\n", "pkg/util.py": "A = 1\n", 'pkg/odd"ü.py': "A = 1\nB = 2\n"})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        write_tree(self.root, {"pkg/core.py": CORE2, "pkg/fresh.py": "Y = 1\nZ = 2\n", 'pkg/odd"ü.py': "A = 1\nB = 3\n"})  # edited, untracked, and a name git quotes
        git(self.root, "mv", "pkg/old.py", "pkg/renamed.py")
        (self.root / "pkg/renamed.py").write_text("O = 1\nP = 2\nQ = 3\nR = 5\n")  # moved, one line edited on the way
        (self.root / "pkg/util.py").unlink()
        changed = coverage.changed_lines(self.root, "HEAD", ["pkg/core.py", "pkg/fresh.py", "pkg/renamed.py", "pkg/__init__.py", 'pkg/odd"ü.py'])
        self.assertEqual(changed, {"pkg/core.py": {6, 7, 8, 9, 10, 11, 12}, "pkg/fresh.py": {1, 2}, "pkg/renamed.py": {4}, "pkg/__init__.py": set(), 'pkg/odd"ü.py': {2}})
        self.assertEqual(coverage.changed_lines(self.root, "HEAD", []), {})

    def test_quoted_paths_are_read_as_git_writes_them(self):
        self.assertEqual(coverage._unquote('"pkg/odd\\"\\303\\274\\t.py"'), 'pkg/odd"ü\t.py')  # a quote, two octal bytes, a tab
        self.assertEqual(coverage._unquote('"a\\\\b"'), "a\\b")
        self.assertEqual(coverage._unquote("plain/path.py"), "plain/path.py")


if __name__ == "__main__":
    unittest.main()
