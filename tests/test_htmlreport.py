import json
import random
import re
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from helpers import TempRepo, git, write_tree
from tessri import config, htmlreport, modules
from tessri.analyze import analyze
from tessri.cli import main
from tessri.report import build_report
from test_modules import CYCLE, PROJECT, brute_force_components, random_graph, run_cli

REPO = Path(__file__).resolve().parent.parent
VOID = {"meta", "br", "input", "link", "img", "hr", "wbr", "path", "rect", "circle", "source"}


class Page(HTMLParser):
    """Collects what a reader of the page would meet: ids, links, external references, unbalanced tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs, self.srcs, self.stack, self.problems = [], [], [], [], []
        self.text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if "href" in a:
            self.hrefs.append(a["href"])
        if "src" in a:
            self.srcs.append(a["src"])
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"</{tag}> closes {self.stack[-1:] or 'nothing'}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def parse(text):
    page = Page()
    page.feed(text)
    page.close()
    return page


def scan(root, **settings):
    cfg = config.load(root)
    for key, value in settings.items():
        setattr(cfg, key, value)
    return analyze(root, cfg)


def page_for(a):
    return htmlreport.build_html(a)


def script_of(text, ident):
    return re.search(r'<script[^>]*id="%s"[^>]*>(.*?)</script>' % ident, text, re.S).group(1)


class Committed(TempRepo):
    """PROJECT committed by a person whose name needs escaping."""

    PERSON = ("Eve \"O'Neil\" & Co", "eve@example.com")

    def setUp(self):
        super().setUp()
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, PROJECT)
        git(self.root, "add", "-A")
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        git(self.root, "commit", "-q", "-m", "init", when=when, author=self.PERSON)


class PageTest(Committed):
    def setUp(self):
        super().setUp()
        self.a = scan(self.root)
        self.html = page_for(self.a)
        self.page = parse(self.html)

    def test_it_is_one_well_formed_document(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertEqual(self.page.problems, [])
        self.assertEqual(self.page.stack, [])
        self.assertEqual(len(self.page.ids), len(set(self.page.ids)), "ids must be unique")

    def test_it_never_reaches_for_the_network(self):
        self.assertEqual(self.page.srcs, [])
        self.assertTrue(all(h.startswith("#") for h in self.page.hrefs), self.page.hrefs)
        for needle in ("@import", "url(http", "<link", "<iframe", "fetch(", "XMLHttpRequest", "import("):
            self.assertNotIn(needle, self.html)

    def test_every_section_is_there_and_the_nav_points_at_real_ids(self):
        for ident in ("overview", "attention", "directories", "modules", "impact", "ownership", "hotspots", "cleanup", "notes"):
            self.assertIn(ident, self.page.ids)
        for href in self.page.hrefs:
            self.assertIn(href[1:], self.page.ids)

    def test_numbers_match_the_report(self):
        report = build_report(self.a)
        text = " ".join(self.page.text)
        self.assertIn(f"{report['summary']['code_lines']:,}", text)
        self.assertIn(self.root.name, text)

    @unittest.skipIf(sys.platform == "win32", "a file name Windows forbids")
    def test_markup_in_names_cannot_reach_the_page(self):
        self.assertNotIn(self.PERSON[0], self.html)
        self.assertIn("Eve &quot;O&#x27;Neil&quot; &amp; Co", self.html)
        write_tree(self.root, {"core/<b>&\"q'.py": "VALUE = 1\n"})
        html = page_for(scan(self.root))
        self.assertNotIn("<b>&\"q'", html)
        self.assertIn("&lt;b&gt;&amp;&quot;q&#x27;", html)
        self.assertEqual(parse(html).problems, [])

    @unittest.skipIf(sys.platform == "win32", "a file name Windows forbids")
    def test_embedded_data_is_valid_json_and_cannot_close_its_script(self):
        write_tree(self.root, {"core/</script><script>alert(1)</script>.py": "VALUE = 1\n"})
        html = page_for(scan(self.root))
        raw = script_of(html, "data")
        self.assertNotIn("</", raw)
        self.assertNotIn("<", raw)
        data = json.loads(raw)
        self.assertIn("core/</script><script>alert(1)</script>.py", [f[0] for f in data["explorer"]["files"]])
        self.assertEqual(html.count("<script"), 3)  # theme boot, data, app

    def test_embedded_explorer_data_is_what_the_python_side_computes(self):
        data = json.loads(script_of(self.html, "data"))
        self.assertEqual(data["explorer"], json.loads(json.dumps(modules.explorer(self.a))))
        self.assertEqual([m["id"] for m in data["graph"]["modules"]], ["app", "core", "util"])
        self.assertEqual(data["inactive_days"], self.a.cfg.owner_inactive_days)

    def test_the_same_analysis_gives_the_same_page(self):
        self.assertEqual(self.html, page_for(self.a))

    def test_owners_appear_by_name_only(self):
        self.assertNotIn("eve@example.com", self.html)
        self.assertIn("O&#x27;Neil", self.html)


class DegradedTest(TempRepo):
    def test_without_git_the_page_says_so_instead_of_inventing_owners(self):
        write_tree(self.root, PROJECT)
        html = page_for(scan(self.root))
        page = parse(html)
        self.assertEqual(page.problems, [])
        self.assertIn("this directory has none", html)
        self.assertNotIn("No active owner", html)
        self.assertIn("no git history", html)

    def test_a_repository_no_analyzer_covers_has_no_graph_but_still_a_page(self):
        write_tree(self.root, {"main.go": "package main\n\nfunc main() {}\n", "README.md": "# hi\n"})
        html = page_for(scan(self.root))
        self.assertEqual(parse(html).problems, [])
        self.assertIn("No import graph", html)
        self.assertIn("Not available", html)
        self.assertIsNone(json.loads(script_of(html, "data"))["explorer"])

    def test_an_empty_directory_still_renders(self):
        html = page_for(scan(self.root))
        self.assertEqual(parse(html).problems, [])

    def test_a_huge_repository_leaves_the_explorer_out(self):
        write_tree(self.root, PROJECT)
        with mock.patch.object(modules, "EXPLORER_MAX_FILES", 2):
            html = page_for(scan(self.root))
        self.assertIn("too many to carry", html)
        self.assertIsNone(json.loads(script_of(html, "data"))["explorer"])

    def test_a_cycle_shows_up_in_the_page(self):
        write_tree(self.root, CYCLE)
        html = page_for(scan(self.root))
        self.assertIn("Cycle 1", html)
        self.assertIn('class="edge cut"', html)
        self.assertEqual(parse(html).problems, [])


def fake_graph(rng, size):
    nodes, weight = random_graph(rng, size=size, density=0.25)
    adj = {}
    for a, b in weight:
        adj.setdefault(a, set()).add(b)
    cut = set()
    for group in modules.components(nodes, adj):
        cut.update(modules.cut_edges(group, {k: v for k, v in weight.items() if k[0] in group and k[1] in group}))
    mods = [{"id": m, "files": 1, "code": 10, "status": {"active": 10, "stable": 0, "dormant": 0, "orphan": 0}, "uses": 0, "used_by": 0, "cycle": None, "commits_year": 0} for m in nodes]
    edges = [{"from": a, "to": b, "imports": w, "files": 1, "examples": [], "cycle": None, "cut": (a, b) in cut} for (a, b), w in sorted(weight.items())]
    return {"modules": mods, "edges": edges}


def longest_paths(nodes, edges):
    """Column of each node: the length of the longest chain of (uncut) dependencies leading to it."""
    before = {n: [] for n in nodes}
    for e in edges:
        if not e["cut"]:
            before[e["to"]].append(e["from"])
    memo = {}

    def depth(n):
        if n not in memo:
            memo[n] = 1 + max((depth(p) for p in before[n]), default=-1)
        return memo[n]

    return {n: depth(n) for n in nodes}


class LayoutTest(unittest.TestCase):
    def test_arrows_run_left_to_right_except_the_cuts(self):
        rng = random.Random(2)
        for _ in range(100):
            g = fake_graph(rng, rng.randint(2, 12))
            where, width, height = htmlreport._layout(g["modules"], g["edges"])
            for e in g["edges"]:
                if not e["cut"]:
                    self.assertLess(where[e["from"]][0], where[e["to"]][0], e)

    def test_each_module_sits_in_the_column_of_its_longest_chain(self):
        rng = random.Random(9)
        step = htmlreport.NODE_W + htmlreport.COL_GAP
        for _ in range(400):
            g = fake_graph(rng, rng.randint(2, 15))
            where, _, _ = htmlreport._layout(g["modules"], g["edges"])
            want = longest_paths([m["id"] for m in g["modules"]], g["edges"])
            self.assertEqual({i: (x - htmlreport.PAD) // step for i, (x, _) in where.items()}, want)

    def test_nodes_never_overlap_and_stay_inside_the_canvas(self):
        rng = random.Random(3)
        for _ in range(100):
            g = fake_graph(rng, rng.randint(1, 14))
            where, width, height = htmlreport._layout(g["modules"], g["edges"])
            self.assertEqual(len(where), len(g["modules"]))
            boxes = sorted(where.values())
            for (x1, y1), (x2, y2) in zip(boxes, boxes[1:]):
                self.assertTrue(x1 != x2 or abs(y1 - y2) >= htmlreport.NODE_H)
            for x, y in boxes:
                self.assertTrue(0 <= x and x + htmlreport.NODE_W <= width and 0 <= y and y + htmlreport.NODE_H <= height)

    def test_the_svg_draws_every_module_and_every_chosen_edge(self):
        rng = random.Random(4)
        g = fake_graph(rng, 9)
        g["summary"] = {"modules": 9}
        svg, shown, floor = htmlreport._graph_svg(g)
        self.assertEqual(svg.count('class="node'), len(htmlreport.drawn(g, None)[0]))
        self.assertEqual(svg.count('<g class="edge'), shown)
        drawn_edges = htmlreport.drawn(g, None)[1]
        self.assertEqual(svg.count('<g class="edge cut"'), sum(e["cut"] for e in drawn_edges))
        self.assertEqual(svg.count("url(#ah-cut)"), sum(e["cut"] for e in drawn_edges))
        self.assertEqual(svg.count("url(#ah)"), sum(not e["cut"] for e in drawn_edges))
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertEqual(parse(svg).problems, [])


NODE_RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const [htmlPath, targetsPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, 'utf8');
const pick = id => html.match(new RegExp('<script[^>]*id="' + id + '"[^>]*>([\\s\\S]*?)</script>'))[1];
const data = JSON.parse(pick('data'));
const ctx = {};
vm.createContext(ctx);
new vm.Script(pick('app')).runInContext(ctx);
const core = ctx.TessriCore;
const jobs = JSON.parse(fs.readFileSync(targetsPath, 'utf8'));
const out = jobs.map(([name, hops, policy = 'all']) => core.impactOf(data.explorer, name, hops, null, policy));
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's script")
class ExplorerDifferentialTest(TempRepo):
    """The page answers `impact` in the browser; it must give the numbers `tessri impact` gives."""

    def check(self, a, targets, hops_list=(None, 1, 2), policies=('all',)):
        html = page_for(a)
        (self.root / "page.html").write_text(html, encoding="utf-8")
        jobs = [[t, h, p] for t in targets for h in hops_list for p in policies]
        (self.root / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        (self.root / "run.js").write_text(NODE_RUNNER, encoding="utf-8")
        run = subprocess.run(["node", str(self.root / "run.js"), str(self.root / "page.html"), str(self.root / "jobs.json")], capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        results = json.loads(run.stdout)
        self.assertEqual(len(results), len(jobs))
        for (target, hops, policy), got in zip(jobs, results):
            want = modules.impact(a, target, hops=hops, edges=policy)
            label = f"{target} hops={hops} edges={policy}"
            self.assertNotIn("error", got, label)
            self.assertEqual((got["target"], got["kind"], got["files"], got["code"]), (want["target"], want["kind"], want["files"], want["code"]), label)
            for key in ("direct", "files", "code", "by_distance"):
                self.assertEqual(got["dependents"][key], want["dependents"][key], f"{label} dependents.{key}")
            self.assertAlmostEqual(got["dependents"]["share"], want["dependents"]["share"], delta=0.11, msg=label)
            self.assertEqual(
                [(m["module"], m["files"], m["direct"], m["code"]) for m in got["dependents"]["modules"]],
                [(m["module"], m["files"], m["direct"], m["code"]) for m in want["dependents"]["modules"]],
                label,
            )
            self.assertEqual(got["tests"], want["tests"], label)
            self.assertEqual(got["depends_on"], want["depends_on"], label)
            self.assertEqual(got["edges"], want["edges"], label)

    def test_both_policies_with_python_packages_and_typescript_inference(self):
        from test_provenance import PYTHON, TYPESCRIPT

        write_tree(self.root, {**PYTHON, **TYPESCRIPT})
        a = scan(self.root)
        targets = sorted(a.records) + ['pkg', 'pkg/sub', 'src', 'tests']
        self.check(a, targets, policies=('all', 'imports'))

    def test_unknown_plugin_evidence_and_bounded_reference_examples(self):
        from tessri.analyzers.python import PythonAnalyzer
        from test_provenance import PYTHON, Stub

        write_tree(self.root, {**PYTHON, 'main.go': 'package main\n', **{
            f'guess{i}.py': 'VALUE = "pkg.sub.leaf"\n' for i in range(12)
        }})
        a = analyze(self.root, config.load(self.root), analyzers=[PythonAnalyzer(), Stub()])
        self.check(a, ['pkg/sub/leaf.py', 'pkg', 'main.go'], policies=('all', 'imports'))

    def test_a_small_project(self):
        write_tree(self.root, PROJECT)
        a = scan(self.root)
        self.check(a, ["util/helpers.py", "core/engine.py", "app/main.py", "tests/test_engine.py", "core", "util", "app", "core.engine", "./util/", "util/helpers.py"])

    def test_a_cycle_and_a_package_that_only_passes_imports_through(self):
        write_tree(self.root, CYCLE)
        write_tree(self.root, {"x.py": "import a.b.c\n\nif __name__ == '__main__':\n    print(a.b.c)\n", "a/b/__init__.py": "", "a/b/c.py": "VALUE = 1\n"})
        a = scan(self.root)
        self.check(a, [p for p, r in a.records.items() if r.analyzer] + ["a", "a/b", "b"], policies=('all', 'imports'))

    def test_this_repository(self):
        a = analyze(REPO, config.load(REPO))
        files = sorted(p for p, r in a.records.items() if r.analyzer)
        folders = sorted({p.rpartition("/")[0] for p in files if "/" in p})
        self.check(a, files + folders, policies=('all', 'imports'))

    def test_bad_targets_are_refused_in_the_browser_too(self):
        write_tree(self.root, PROJECT)
        a = scan(self.root)
        (self.root / "page.html").write_text(page_for(a), encoding="utf-8")
        (self.root / "jobs.json").write_text(json.dumps([["nowhere.py", None], ["", None]]), encoding="utf-8")
        (self.root / "run.js").write_text(NODE_RUNNER, encoding="utf-8")
        run = subprocess.run(["node", str(self.root / "run.js"), str(self.root / "page.html"), str(self.root / "jobs.json")], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(all("error" in r for r in json.loads(run.stdout)))


class CliTest(Committed):
    def test_scan_writes_the_page(self):
        target = self.root / "out" / "report.html"
        code, out, err = run_cli("scan", str(self.root), "--format", "html", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("wrote", err)
        text = target.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertEqual(parse(text).problems, [])

    def test_scan_prints_the_page_without_out(self):
        code, out, _ = run_cli("scan", str(self.root), "--format", "html")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("<!doctype html>"))

    def test_other_formats_are_unchanged(self):
        self.assertEqual(json.loads(run_cli("scan", str(self.root), "--format", "json")[1])["schema_version"], 1)
        self.assertIn("# Tessri", run_cli("scan", str(self.root))[1])


if __name__ == "__main__":
    unittest.main()
