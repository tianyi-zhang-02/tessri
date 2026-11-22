"""The offline brief preserves the JSON's evidence and treats repository text as untrusted."""
import copy
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from tessri import briefhtml
from tessri.cli import main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import review_example


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.ids = set()
        self.full = False
        self.in_pre = False
        self.payload = ""
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "details" and attrs.get("id") == "evidence":
            self.full = True
        if tag == "pre" and self.full:
            self.in_pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False
        if tag == "details" and self.full:
            self.full = False

    def handle_data(self, data):
        if self.in_pre:
            self.payload += data


class BriefHtmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = review_example.generate()

    def test_full_evidence_round_trips_and_has_no_executable_or_remote_content(self):
        b = copy.deepcopy(self.result)
        attack = '</pre><script>alert("repo")</script><img src="https://invalid.test/">'
        b["repo"]["name"] = attack
        b["change"]["commits"][0]["subject"] = attack
        b["consequences"]["findings"][0]["title"] = attack
        b["validation"]["ran"] = [attack]
        b["people"]["reviewers"][0]["name"] = attack
        text = briefhtml.render(b)
        doc = Document(text)
        self.assertEqual(json.loads(doc.payload), b)
        self.assertFalse(any(t in ("script", "img", "iframe", "link") for t, a in doc.tags))
        self.assertIn(html.escape(attack, quote=True), text)
        for tag, attrs in doc.tags:
            self.assertFalse(any(k.startswith("on") for k in attrs))
            if "href" in attrs:
                self.assertTrue(attrs["href"].startswith("#"), attrs)
                self.assertIn(attrs["href"][1:], doc.ids)

    def test_limited_attention_can_be_expanded_without_losing_files(self):
        b = copy.deepcopy(self.result)
        b["attention"].update(files=b["attention"]["files"][:1], shown=1)
        text = briefhtml.render(b)
        self.assertIn("Showing 1 of 8 files", text)
        self.assertIn("7 more changed files, in order (8 total)", text)
        for row in b["triage"]["files"]:
            self.assertIn(html.escape(row["path"]), text)
        self.assertIn("Alice Adams 100%", text)
        self.assertNotIn("10000%", text)
        self.assertIn("Added definitions: <code>gross</code>", text)
        self.assertIn("Code snapshot association: unknown", text)

    def test_long_candidate_lists_are_counted_and_expandable(self):
        b = copy.deepcopy(self.result)
        paths = [f"tests/test_{i}.py" for i in range(11)]
        b["triage"]["tests"].update(paths=paths, count=len(paths))
        b["validation"]["candidates"]["count"] = len(paths)
        text = briefhtml.render(b)
        self.assertIn("3 more candidate test files (11 total)", text)
        for path in paths:
            self.assertIn(f"<code>{path}</code>", text)

    def test_reports_keep_failures_unmatched_cases_and_coverage_unknowns(self):
        b = copy.deepcopy(self.result)
        b["validation"]["report"] = {
            "passed": 0, "failed": ["tests/test_invoices.py"], "skipped": 0, "not_run": ["tests/other.py"],
            "ran": {"tests/test_invoices.py": "failed"}, "sources": ["junit.xml"], "cases": 3,
            "unmatched": {"cases": 2, "named": ["missing.Test"]},
        }
        b["validation"]["coverage"] = {
            "changed": 4, "statements": 3, "ran": 2, "not_run": 1,
            "files": {"billing/invoices.py": {"changed": 4, "statements": 3, "ran": 2, "not_run": 1, "not_run_ranges": [[5, 5]]}},
            "not_measured": {"billing/tax.py": 4}, "sources": ["coverage.xml"], "measured": 1,
            "unmatched": {"files": 1, "named": ["outside.py"]},
        }
        text = briefhtml.render(b)
        self.assertIn("1 failed", text)
        self.assertIn("tests/other.py", text)
        self.assertIn("missing.Test", text)
        self.assertIn("outside.py", text)
        self.assertIn("Not in the report", text)
        self.assertIn("current code", text)
        self.assertEqual(json.loads(Document(text).payload), b)

    def test_no_checks_and_skipped_analysis_do_not_become_passing_results(self):
        b = copy.deepcopy(self.result)
        b["validation"].update(ran=[], report=None, coverage=None)
        b["change"]["code_files"] = 0
        b["consequences"]["findings"] = []
        b["meta"]["analysis"]["structure"] = "skipped"
        text = briefhtml.render(b)
        self.assertIn("No check was recorded as run", text)
        self.assertIn("Nothing was compared: no code changed", text)
        self.assertIn("Not analysed: Go", text)
        self.assertIn("structure are unknown", text)
        self.assertNotIn("Code snapshot association", text)

    def test_the_example_really_has_the_documented_gap_without_private_machine_details(self):
        b = self.result
        self.assertEqual(b["change"]["code_files"], 8)
        self.assertEqual(b["change"]["lines"], 22)
        self.assertEqual(b["change"]["authors"], ["Carol Chen", "Dana Doe"])
        self.assertEqual(b["consequences"]["counts"], {"block": 1, "warn": 2, "info": 1})
        self.assertIn("2 passed (exit 0)", b["validation"]["ran"][0])
        self.assertEqual(b["change"]["uncommitted_files"], ["tests/test_invoices.py"])
        raw = json.dumps(b)
        self.assertNotIn(str(Path.home()), raw)
        dangling = next(f for f in b["consequences"]["findings"] if f["kind"] == "dangling-import")
        self.assertEqual(dangling["files"], ["reports/summary.py"])

    def test_cli_writes_the_offline_page_instead_of_markdown(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch("tessri.cli.brief.compute", return_value=self.result):
            target = Path(temp) / "brief.html"
            self.assertEqual(main(["brief", "--format", "html", "--repo", temp, "--out", str(target)]), 0)
            text = target.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!doctype html>"))
            self.assertEqual(json.loads(Document(text).payload), self.result)
