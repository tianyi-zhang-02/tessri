"""The URL fragment as the explorer's restorable state.

`#overview`, `#impact`, `#modules` and nested ids stay plain section links. A nonempty impact query is
`#impact?path=<encoded>&edges=all|imports&hops=<n>`, parsed and produced by two pure functions of the page script
(`TessriCore.parseFragment`, `TessriCore.impactFragment`), which node runs here without a DOM; the script uses the
standard `URLSearchParams`, which the vm context is given explicitly. The wiring to the page (restoring on load, a
hop limit the control did not offer getting its own option, replacing the address as the query changes, one history
entry per view change) needs a browser and is not exercised here."""

import json
import re
import shutil
import subprocess
import unittest

from helpers import TempRepo, write_tree
from test_htmlreport import page_for, scan
from test_modules import PROJECT

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const [htmlPath, jobsPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, 'utf8');
const pick = id => html.match(new RegExp('<script[^>]*id="' + id + '"[^>]*>([\\s\\S]*?)</script>'))[1];
const ctx = {URLSearchParams};
vm.createContext(ctx);
new vm.Script(pick('app')).runInContext(ctx);
const core = ctx.TessriCore;
const jobs = JSON.parse(fs.readFileSync(jobsPath, 'utf8'));
const out = jobs.map(job => job[0] === 'parse' ? core.parseFragment(job[1]) : core.impactFragment(job[1], job[2], job[3]));
process.stdout.write(JSON.stringify(out));
"""

NASTY = ["a b.py", "a+b.py", "odd#name.py", "why?.py", "x&y.py", "100%.py", "文件/路径.py", "it's (ok).py", "dir/sub/file.py", "semi;colon=eq.py"]


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's script")
class FragmentTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, PROJECT)
        self.html = page_for(scan(self.root))
        (self.root / "page.html").write_text(self.html, encoding="utf-8")
        (self.root / "run.js").write_text(RUNNER, encoding="utf-8")

    def run_jobs(self, jobs):
        (self.root / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        run = subprocess.run(["node", str(self.root / "run.js"), str(self.root / "page.html"), str(self.root / "jobs.json")], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def parse(self, *hashes):
        return self.run_jobs([["parse", h] for h in hashes])

    def link(self, *args):
        return self.run_jobs([["link", *a] for a in args])

    def test_plain_section_links_and_nested_ids_carry_no_query(self):
        for hash_, view in [("#overview", "overview"), ("#impact", "impact"), ("#modules", "modules"), ("#orphan-table", "orphan-table"), ("#workspace-content", "workspace-content"), ("", ""), ("#", ""), ("#imp%61ct", "impact"), ("#impact?", "impact"), ("#impact?edges=imports&hops=2", "impact"), ("#modules?path=x", "modules")]:
            self.assertEqual(self.parse(hash_), [{"view": view, "query": None}], hash_)

    def test_a_query_restores_the_path_the_policy_and_the_hops(self):
        full, defaults = self.parse("#impact?path=src%2Fapp%2Fmain.py&edges=imports&hops=2", "#impact?path=core")
        self.assertEqual(full, {"view": "impact", "query": {"path": "src/app/main.py", "edges": "imports", "hops": 2}})
        self.assertEqual(defaults, {"view": "impact", "query": {"path": "core", "edges": "all", "hops": None}})

    def test_encoded_characters_survive_a_round_trip(self):
        links = self.link(*[[p, "imports", "2"] for p in NASTY])
        for path, fragment in zip(NASTY, links):
            self.assertTrue(fragment.startswith("#impact?path="), fragment)
            encoded = fragment[len("#impact?path="):].split("&edges=")[0]
            self.assertFalse(re.search(r"[#?& ]", encoded), fragment)  # the path never breaks the fragment grammar
            self.assertTrue(fragment.endswith("&edges=imports&hops=2"), fragment)
        back = self.run_jobs([["parse", fragment] for fragment in links])
        self.assertEqual([r["query"]["path"] for r in back], NASTY)
        self.assertTrue(all(r["query"] == {"path": r["query"]["path"], "edges": "imports", "hops": 2} for r in back))
        plus, space = self.parse("#impact?path=a+b.py", "#impact?path=a%20b.py")  # both spellings of a space
        self.assertEqual((plus["query"]["path"], space["query"]["path"]), ("a b.py", "a b.py"))

    def test_invalid_or_unknown_parameters_fall_back_and_never_fail(self):
        cases = {
            "#impact?path=a.py&edges=bogus": ("a.py", "all", None),
            "#impact?path=a.py&hops=0": ("a.py", "all", None),
            "#impact?path=a.py&hops=-1": ("a.py", "all", None),
            "#impact?path=a.py&hops=abc": ("a.py", "all", None),
            "#impact?path=a.py&hops=1.5": ("a.py", "all", None),
            "#impact?path=a.py&hops=007": ("a.py", "all", None),
            "#impact?path=a.py&hops=%2B3": ("a.py", "all", None),
            "#impact?path=a.py&hops=9007199254740993": ("a.py", "all", None),  # beyond a safe integer
            "#impact?path=a.py&hops=99": ("a.py", "all", 99),  # any positive safe integer is kept, never widened to no limit
            "#impact?path=a.py&hops=9007199254740991": ("a.py", "all", 9007199254740991),
            "#impact?path=a.py&hops=3": ("a.py", "all", 3),
            "#impact?path=a.py&colour=red": ("a.py", "all", None),  # unknown parameters are ignored
            "#impact?path=first.py&path=second.py": ("first.py", "all", None),  # the first value wins
            "#impact?__proto__=x&constructor=y&path=a.py": ("a.py", "all", None),
            "#impact?path=%20%20padded.py%20": ("padded.py", "all", None),
        }
        results = self.parse(*cases)
        for (hash_, want), got in zip(cases.items(), results):
            self.assertEqual(got, {"view": "impact", "query": {"path": want[0], "edges": want[1], "hops": want[2]}}, hash_)
            self.assertEqual(sorted(got), ["query", "view"], hash_)
        for hash_ in ("#impact?path=", "#impact?path=%20", "#imp%E0act?path=a.py"):
            self.assertEqual(self.parse(hash_)[0]["query"], None, hash_)  # an empty path or an unreadable view: no query, no crash
        broken, literal = self.parse("#impact?path=%E0%A4", "#impact?path=%ZZ")
        self.assertEqual(broken["query"]["path"], "\ufffd")  # a malformed escape becomes the replacement character, then a visible lookup error
        self.assertEqual(literal["query"]["path"], "%ZZ")

    def test_links_omit_defaults_and_encode_the_path(self):
        self.assertEqual(
            self.link(["src/app/main.py", "all", ""], ["core", "imports", "2"], ["", "imports", "3"], ["   ", "all", "1"], ["x.py", "all", "0"], ["x.py", "all", "abc"], ["x.py", "all", None], ["x.py", "all", "1.5"], ["x.py", "imports", 3], ["x.py", "all", "42"], ["a b#c?&+.py", "all", ""]),
            ["#impact?path=src%2Fapp%2Fmain.py", "#impact?path=core&edges=imports&hops=2", "#impact", "#impact", "#impact?path=x.py", "#impact?path=x.py", "#impact?path=x.py", "#impact?path=x.py", "#impact?path=x.py&edges=imports&hops=3", "#impact?path=x.py&hops=42", "#impact?path=a%20b%23c%3F%26%2B.py"],
        )


if __name__ == "__main__":
    unittest.main()
