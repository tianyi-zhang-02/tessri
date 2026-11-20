"""`tessri check --format sarif`: one finding, one result, in order; file-level locations or none; nothing invented."""

import contextlib
import io
import json
import time
import sys
import unittest
from pathlib import Path

from helpers import TempRepo, git, write_tree

from tessri import __version__, sarifview
from tessri.cli import main
from tessri.sarifview import INFORMATIONAL, ROOT_ID, RULES, sarif

FINDINGS = [
    {"id": "dangling-import:pkg/gone.py", "kind": "dangling-import", "severity": "block", "title": "`pkg/gone.py` was deleted but is still imported", "detail": "Imported by 1 file the change did not touch.", "files": ["pkg/user.py"], "action": "Restore it or update the importers.", "needs_human": False},
    {"id": "new-orphan:added", "kind": "new-orphan", "severity": "warn", "title": "3 new files that nothing reaches", "detail": "No entry point reaches these files.", "files": ["dir with space/ü#%.py", "../evil.py", "/abs.py", "weird\\name.py", "pkg/gone.py", "dir with space/ü#%.py"], "action": "Wire them in or drop them.", "needs_human": False},
    {"id": "new-cycle:a+b", "kind": "new-cycle", "severity": "warn", "title": "Modules `a`, `b` now depend on each other", "detail": "Closed by a new import.", "files": [], "action": "Cut one dependency.", "needs_human": False},
    {"id": "no-active-owner:changed", "kind": "no-active-owner", "severity": "warn", "title": "1 changed file nobody active maintains", "detail": "Its last maintainer went quiet.", "files": ["legacy/old.py"], "action": "Name it in the change description.", "needs_human": True},
    {"id": "new-dependency:modules", "kind": "new-dependency", "severity": "info", "title": "2 new dependencies between modules", "detail": "`a` -> `b`; `b` -> `c`.", "files": ["a/x.py", "b/y.py"], "action": "Read them.", "needs_human": False},
    {"id": "orphan-resolved:all", "kind": "orphan-resolved", "severity": "info", "title": "1 orphan file gone", "detail": "It was removed.", "files": ["pkg/gone.py"], "action": "Nothing.", "needs_human": False},
    {"id": "cycle-resolved:a+b", "kind": "cycle-resolved", "severity": "info", "title": "A cycle is gone", "detail": "Modules `a`, `b` no longer depend on each other.", "files": [], "action": "Nothing.", "needs_human": False},
]
RESULT = {
    "schema_version": 1,
    "kind": "change-check",
    "meta": {"git": {"head": "a" * 40, "history_rev": "b" * 40}, "change": {"base": "b" * 40}, "analysis": {"structure": "complete", "reason": None}},
    "change": {"since": "main", "base": "b" * 9, "head": "a" * 9, "uncommitted": False},
    "summary": {"files": 5, "findings": {"block": 1, "warn": 3, "info": 3}},
    "changed_files": [{"path": "pkg/gone.py", "change": "deleted"}, {"path": "pkg/user.py", "change": "modified"}],
    "notes": ["Static imports only."],
    "findings": FINDINGS,
}


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.root = Path("/tmp/some project/ü#%/sub")
        self.log = sarif(RESULT, self.root)
        self.run = self.log["runs"][0]

    def test_document_shape(self):
        self.assertEqual((self.log["$schema"], self.log["version"], len(self.log["runs"])), (sarifview.SCHEMA, "2.1.0", 1))
        driver = self.run["tool"]["driver"]
        self.assertEqual((driver["name"], driver["version"]), ("tessri", __version__))
        self.assertEqual([r["id"] for r in driver["rules"]], [f"tessri/{kind}" for kind, _, _ in RULES])
        self.assertNotIn("invocations", self.run)
        self.assertNotIn("automationDetails", self.run)
        json.dumps(self.log)  # serialisable

    def test_one_result_per_finding_in_order(self):
        results = self.run["results"]
        self.assertEqual([r["properties"]["tessri/finding"]["id"] for r in results], [f["id"] for f in FINDINGS])
        for r in results:
            self.assertEqual(self.run["tool"]["driver"]["rules"][r["ruleIndex"]]["id"], r["ruleId"])
            self.assertEqual(r["ruleId"], "tessri/" + r["properties"]["tessri/finding"]["kind"])
            self.assertNotIn("partialFingerprints", r)
            self.assertNotIn("fingerprints", r)

    def test_kinds_and_levels(self):
        by = {r["properties"]["tessri/finding"]["kind"]: (r["kind"], r["level"]) for r in self.run["results"]}
        self.assertEqual(by["dangling-import"], ("fail", "error"))
        self.assertEqual(by["new-orphan"], ("fail", "warning"))
        self.assertEqual(by["no-active-owner"], ("fail", "warning"))
        for kind in INFORMATIONAL:
            self.assertEqual(by[kind], ("informational", "none"))

    def test_message_carries_evidence_and_action(self):
        text = self.run["results"][3]["message"]["text"]
        self.assertIn("1 changed file nobody active maintains. Its last maintainer went quiet. Do: Name it in the change description.", text)
        self.assertTrue(text.endswith("A person has to decide this."))
        self.assertNotIn("A person has to decide", self.run["results"][0]["message"]["text"])

    def test_locations_are_file_level_and_safe(self):
        orphan = self.run["results"][1]
        self.assertEqual(orphan["locations"], [{"physicalLocation": {"artifactLocation": {"uri": "dir%20with%20space/%C3%BC%23%25.py", "uriBaseId": ROOT_ID}}}])
        related = orphan["relatedLocations"]
        self.assertEqual([(r["id"], r["physicalLocation"]["artifactLocation"]["uri"]) for r in related], [(1, "weird%5Cname.py")])  # ../, absolute, deleted and the duplicate are left out
        self.assertTrue(all("region" not in loc["physicalLocation"] for loc in [*orphan["locations"], *related]))
        self.assertEqual(orphan["properties"]["tessri/finding"]["files"], FINDINGS[1]["files"])  # the evidence keeps every path

    def test_posix_colon_names_are_kept_and_drive_paths_are_not(self):
        finding = dict(FINDINGS[1], files=["C:/x.py", "c:\\x.py", "a:valid.py", "C:", "dir/b:c.py", "new\nline.py"])
        result = sarif(dict(RESULT, findings=[finding]), self.root)["runs"][0]["results"][0]
        uris = [result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]] + [r["physicalLocation"]["artifactLocation"]["uri"] for r in result["relatedLocations"]]
        self.assertEqual(uris, ["a%3Avalid.py", "C%3A", "dir/b%3Ac.py", "new%0Aline.py"])

    def test_locationless_findings_stay_without_a_location(self):
        cycle, resolved = self.run["results"][2], self.run["results"][5]
        for r in (cycle, resolved):
            self.assertNotIn("locations", r)
            self.assertNotIn("relatedLocations", r)
        self.assertEqual(resolved["properties"]["tessri/finding"]["files"], ["pkg/gone.py"])  # deleted: evidence only

    def test_dangling_import_points_at_the_importer(self):
        self.assertEqual(self.run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "pkg/user.py")

    def test_root_uri_is_the_selected_root_with_a_trailing_slash(self):
        uri = self.run["originalUriBaseIds"][ROOT_ID]["uri"]
        self.assertTrue(uri.startswith("file:///") and uri.endswith("/"))
        self.assertTrue(uri.endswith("/some%20project/%C3%BC%23%25/sub/"))
        self.assertNotIn(" ", uri)

    def test_run_properties_keep_the_check_identity(self):
        props = self.run["properties"]["tessri/check"]
        self.assertEqual(sorted(props), ["change", "kind", "meta", "notes", "schema_version", "summary"])
        self.assertEqual(props["meta"]["git"]["head"], "a" * 40)
        self.assertEqual(props["notes"], ["Static imports only."])

    def test_locationless_findings_are_kept_and_counted_by_default(self):
        # the new cycle (no example file), the resolved orphan (its only file is deleted) and the resolved cycle
        self.assertEqual(self.run["properties"]["tessri/locationless"], {"policy": "keep", "count": 3, "omitted": []})
        self.assertEqual(len(self.run["results"]), len(FINDINGS))

    def test_omit_moves_locationless_findings_whole_into_the_run_properties(self):
        run = sarif(RESULT, self.root, locationless="omit")["runs"][0]
        kept = [r for r in self.run["results"] if "locations" in r]
        self.assertEqual(run["results"], kept)  # same results, same order, only the location-free ones gone
        self.assertTrue(all("locations" in r for r in run["results"]))
        gone = run["properties"]["tessri/locationless"]
        self.assertEqual((gone["policy"], gone["count"]), ("omit", 3))
        self.assertEqual(gone["omitted"], [FINDINGS[2], FINDINGS[5], FINDINGS[6]])  # the whole finding, not a summary of it
        self.assertEqual(run["properties"]["tessri/check"], self.run["properties"]["tessri/check"])  # the check mirror is untouched
        json.dumps(run)

    def test_unknown_locationless_policy_is_refused(self):
        with self.assertRaises(ValueError):
            sarif(RESULT, self.root, locationless="drop")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


@unittest.skipIf(sys.platform == "win32", "the root is a POSIX absolute path")
class CliTest(TempRepo):
    """A branch that deletes a file another file still imports: one block finding, plus whatever else the check says."""

    def setUp(self):
        super().setUp()
        self.now = time.time()
        write_tree(self.root, {"pkg/__init__.py": "", "pkg/a.py": "import pkg.b\n", "pkg/b.py": "x = 1\n", "main.py": "import pkg.a\n", "README.md": "# r\n"})
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base", when=self.stamp(30))
        git(self.root, "branch", "-M", "main")
        git(self.root, "checkout", "-qb", "feature")
        (self.root / "pkg/b.py").unlink()
        git(self.root, "commit", "-qam", "drop b", when=self.stamp(1))

    def stamp(self, days_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(self.now - days_ago * 86400))

    def test_sarif_on_stdout_and_gate_parity(self):
        code, out, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif")
        self.assertEqual(code, 0)
        log = json.loads(out)
        run = log["runs"][0]
        kinds = [r["properties"]["tessri/finding"]["kind"] for r in run["results"]]
        self.assertIn("dangling-import", kinds)
        dangling = run["results"][kinds.index("dangling-import")]
        self.assertEqual((dangling["level"], dangling["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]), ("error", "pkg/a.py"))
        self.assertEqual(run["originalUriBaseIds"][ROOT_ID]["uri"], self.root.as_uri() + "/")
        self.assertEqual(run["properties"]["tessri/check"]["meta"]["analysis"], {"structure": "complete", "reason": None})
        code, gated, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif", "--fail-on", "block")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(gated)["runs"][0]["results"], run["results"])  # the gate changes the exit code, not the document

    def test_same_findings_as_json(self):
        _, as_json, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "json")
        _, as_sarif, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif")
        findings = json.loads(as_json)["findings"]
        self.assertEqual([r["properties"]["tessri/finding"] for r in json.loads(as_sarif)["runs"][0]["results"]], findings)

    def test_out_file_and_errors(self):
        target = self.root.parent / (self.root.name + "-reports") / "check.sarif"
        self.addCleanup(lambda: __import__("shutil").rmtree(target.parent, ignore_errors=True))
        code, out, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(target.read_text())["version"], "2.1.0")
        code, out, err = run_cli("check", "--repo", str(self.root), "--since", "no-such-ref", "--format", "sarif")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no-such-ref", err)

    def test_skipped_check_is_an_empty_log_that_says_so(self):
        git(self.root, "checkout", "-q", "main")
        (self.root / "README.md").write_text("# r\nmore\n")
        code, out, _ = run_cli("check", "--repo", str(self.root), "--format", "sarif")
        self.assertEqual(code, 0)
        run = json.loads(out)["runs"][0]
        self.assertEqual(run["results"], [])
        self.assertEqual(run["properties"]["tessri/check"]["meta"]["analysis"], {"structure": "skipped", "reason": "no-code-changes"})

    def test_nested_root_is_declared_as_the_root(self):
        code, out, _ = run_cli("check", "--repo", str(self.root / "pkg"), "--since", "main", "--format", "sarif")
        self.assertEqual(code, 0)
        run = json.loads(out)["runs"][0]
        self.assertEqual(run["originalUriBaseIds"][ROOT_ID]["uri"], (self.root / "pkg").as_uri() + "/")
        for r in run["results"]:
            for loc in r.get("locations", []):
                self.assertFalse(loc["physicalLocation"]["artifactLocation"]["uri"].startswith("pkg/"))

    def test_locationless_omit_is_opt_in_and_leaves_the_gate_alone(self):
        _, kept_out, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif")
        kept = json.loads(kept_out)["runs"][0]
        code, out, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif", "--locationless", "omit")
        self.assertEqual(code, 0)
        run = json.loads(out)["runs"][0]
        self.assertTrue(all("locations" in r for r in run["results"]))
        self.assertEqual(run["results"], [r for r in kept["results"] if "locations" in r])
        without = [r["properties"]["tessri/finding"] for r in kept["results"] if "locations" not in r]
        self.assertEqual(kept["properties"]["tessri/locationless"], {"policy": "keep", "count": len(without), "omitted": []})
        self.assertEqual(run["properties"]["tessri/locationless"], {"policy": "omit", "count": len(without), "omitted": without})
        code, gated, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "sarif", "--locationless", "omit", "--fail-on", "block")
        self.assertEqual(code, 1)  # the block finding is located, and the gate would count it even if it were not
        self.assertEqual(json.loads(gated)["runs"][0]["results"], run["results"])

    def test_locationless_applies_to_sarif_only(self):
        for fmt in ("json", "md"):
            code, out, err = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", fmt, "--locationless", "omit")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--locationless", err)
        code, _, _ = run_cli("check", "--repo", str(self.root), "--since", "main", "--format", "json", "--locationless", "keep")
        self.assertEqual(code, 0)  # the default is always allowed


if __name__ == "__main__":
    unittest.main()
