import contextlib
import io
import json
import random
import unittest
from datetime import datetime, timezone

from helpers import TempRepo, git, write_tree
from tessri import config, graphview, modules
from tessri.analyze import analyze
from tessri.cli import main
from tessri.explain import TargetError

PROJECT = {
    "app/__init__.py": "",
    "app/main.py": "from core import engine\nfrom util import helpers\n\nif __name__ == '__main__':\n    engine.run()\n    helpers.go()\n",
    "core/__init__.py": "",
    "core/engine.py": "from util import helpers\n\n\ndef run():\n    return helpers.go()\n",
    "util/__init__.py": "",
    "util/helpers.py": "def go():\n    return 1\n",
    "tests/test_engine.py": "from core import engine\n\n\ndef test_run():\n    assert engine.run()\n",
}

# a and b import each other, twice one way and once the other
CYCLE = {
    "a/__init__.py": "",
    "a/x.py": "from b import y\nfrom b import z\n\nif __name__ == '__main__':\n    print(y, z)\n",
    "b/__init__.py": "",
    "b/y.py": "from a import x\n",
    "b/z.py": "VALUE = 1\n",
}


def scan(root):
    return analyze(root, config.load(root))


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def brute_force_components(nodes, adj):
    """Strongly connected groups by mutual reachability: slow and obviously right."""
    reach = {}
    for n in nodes:
        seen, stack = set(), [n]
        while stack:
            for m in adj.get(stack.pop(), ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        reach[n] = seen
    groups = {frozenset(m for m in nodes if m == n or (m in reach[n] and n in reach[m])) for n in nodes}
    return sorted((sorted(g) for g in groups if len(g) > 1), key=lambda g: (-len(g), g))


def random_graph(rng, size=8, density=0.2):
    nodes = [f"m{i}" for i in range(size)]
    return nodes, {(a, b): rng.randint(1, 9) for a in nodes for b in nodes if a != b and rng.random() < density}


def adjacency(edges):
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
    return adj


class AssignTest(unittest.TestCase):
    def test_fixed_depth_keeps_leading_directories(self):
        paths = ["a/b/c.py", "a/d.py", "top.py"]
        self.assertEqual(modules.assign(paths, depth=1), {"a/b/c.py": "a", "a/d.py": "a", "top.py": "."})
        self.assertEqual(modules.assign(paths, depth=2), {"a/b/c.py": "a/b", "a/d.py": "a", "top.py": "."})

    def test_a_small_repository_is_split_by_top_directory(self):
        paths = [f"{d}/sub/f{i}.py" for d in ("one", "two") for i in range(5)] + ["setup.py"]
        self.assertEqual(set(modules.assign(paths).values()), {"one", "two", "."})

    def test_a_big_package_is_split_and_the_wrapper_directories_disappear(self):
        paths = [f"src/pkg/{sub}/f{i}.py" for sub in ("x", "y") for i in range(25)] + [f"docs/d{i}.py" for i in range(10)]
        got = modules.assign(paths)
        self.assertEqual(set(got.values()), {"src/pkg/x", "src/pkg/y", "docs"})

    def test_files_directly_inside_a_split_directory_stay_in_it(self):
        paths = [f"src/pkg/{sub}/f{i}.py" for sub in ("x", "y") for i in range(25)] + ["src/pkg/__init__.py"]
        self.assertEqual(modules.assign(paths)["src/pkg/__init__.py"], "src/pkg")

    def test_splitting_stops_at_the_depth_limit(self):
        deep = "/".join("abcdefgh")
        got = modules.assign([f"{deep}/f{i}.py" for i in range(100)])
        self.assertEqual(set(got.values()), {"/".join("abcdef")})

    def test_a_module_is_always_the_directory_of_its_files_or_an_ancestor(self):
        rng = random.Random(7)
        names = ["a", "b", "c", "d"]
        paths = {"/".join(rng.choice(names) for _ in range(rng.randint(0, 5))) + f"/f{i}.py" for i in range(300)}
        paths = {p.lstrip("/") for p in paths}
        for path, key in modules.assign(paths).items():
            folder = path.rpartition("/")[0]
            self.assertTrue(key == "." and "/" not in folder or folder == key or folder.startswith(key + "/"), (path, key))


class ComponentsTest(unittest.TestCase):
    def test_acyclic_graph_has_none(self):
        self.assertEqual(modules.components("abc", {"a": {"b"}, "b": {"c"}}), [])

    def test_mutual_pair(self):
        self.assertEqual(modules.components("abc", {"a": {"b"}, "b": {"a", "c"}}), [["a", "b"]])

    def test_three_ring_with_a_tail(self):
        adj = {"a": {"b"}, "b": {"c"}, "c": {"a", "t"}}
        self.assertEqual(modules.components("abct", adj), [["a", "b", "c"]])

    def test_separate_cycles_are_listed_largest_first(self):
        adj = {"a": {"b"}, "b": {"a"}, "x": {"y"}, "y": {"z"}, "z": {"x"}}
        self.assertEqual(modules.components("abxyz", adj), [["x", "y", "z"], ["a", "b"]])

    def test_a_module_importing_itself_is_not_a_cycle(self):
        self.assertEqual(modules.components("a", {"a": {"a"}}), [])

    def test_a_very_long_ring_does_not_hit_the_recursion_limit(self):
        nodes = [f"n{i}" for i in range(5000)]
        ring = {n: {nodes[(i + 1) % len(nodes)]} for i, n in enumerate(nodes)}
        self.assertEqual([len(g) for g in modules.components(nodes, ring)], [5000])

    def test_matches_brute_force_on_random_graphs(self):
        rng = random.Random(11)
        for _ in range(300):
            nodes, edges = random_graph(rng, size=rng.randint(2, 10), density=rng.choice((0.1, 0.2, 0.35)))
            adj = adjacency(edges)
            self.assertEqual(modules.components(nodes, adj), brute_force_components(nodes, adj), edges)


class CutEdgesTest(unittest.TestCase):
    def test_acyclic_graph_needs_no_cut(self):
        self.assertEqual(modules.cut_edges("abc", {("a", "b"): 3, ("b", "c"): 1, ("a", "c"): 2}), [])

    def test_a_pair_is_cut_in_its_lighter_direction(self):
        self.assertEqual(modules.cut_edges("ab", {("a", "b"): 5, ("b", "a"): 1}), [("b", "a")])
        self.assertEqual(modules.cut_edges("ab", {("a", "b"): 1, ("b", "a"): 5}), [("a", "b")])

    def test_the_cut_leaves_no_cycle_and_every_edge_in_it_is_needed(self):
        rng = random.Random(5)
        for _ in range(300):
            nodes, edges = random_graph(rng, size=rng.randint(2, 9), density=rng.choice((0.15, 0.3, 0.5)))
            for group in modules.components(nodes, adjacency(edges)):
                inside = {k: v for k, v in edges.items() if k[0] in group and k[1] in group}
                cut = modules.cut_edges(group, inside)
                rest = [k for k in inside if k not in cut]
                self.assertEqual(modules.components(group, adjacency(rest)), [], (inside, cut))
                for edge in cut:
                    self.assertNotEqual(modules.components(group, adjacency(rest + [edge])), [], (inside, cut, edge))

    def test_result_does_not_depend_on_the_order_edges_were_listed(self):
        rng = random.Random(3)
        nodes, edges = random_graph(rng, size=7, density=0.4)
        items = list(edges.items())
        want = modules.cut_edges(nodes, dict(items))
        for _ in range(10):
            rng.shuffle(items)
            self.assertEqual(modules.cut_edges(nodes, dict(items)), want)


class GraphTest(TempRepo):
    def graph(self, files=PROJECT, **kw):
        write_tree(self.root, files)
        return modules.build_graph(scan(self.root), **kw)

    def test_modules_and_the_dependencies_between_them(self):
        g = self.graph()
        self.assertEqual([m["id"] for m in g["modules"]], ["app", "core", "util"])
        edges = {(e["from"], e["to"]): e for e in g["edges"]}
        self.assertEqual(set(edges), {("app", "core"), ("app", "util"), ("core", "util")})
        self.assertEqual((edges[("app", "core")]["imports"], edges[("app", "core")]["files"]), (1, 1))
        self.assertEqual(edges[("app", "core")]["examples"], [["app/main.py", "core/engine.py"]])
        by_id = {m["id"]: m for m in g["modules"]}
        self.assertEqual((by_id["util"]["uses"], by_id["util"]["used_by"], by_id["util"]["instability"]), (0, 2, 0.0))
        self.assertEqual((by_id["app"]["uses"], by_id["app"]["used_by"], by_id["app"]["instability"]), (2, 0, 1.0))
        self.assertEqual(g["cycles"], [])
        self.assertEqual(g["summary"], {"modules": 3, "dependencies": 3, "cycles": 0, "files": 6, "imports": 3})

    def test_tests_are_left_out_unless_asked_for(self):
        g = self.graph(include_tests=True)
        by_id = {m["id"]: m for m in g["modules"]}
        self.assertTrue(by_id["tests"]["tests"])
        self.assertFalse(by_id["core"]["tests"])
        self.assertIn(("tests", "core"), {(e["from"], e["to"]) for e in g["edges"]})
        self.assertNotIn("tests", [m["id"] for m in self.graph(files={})["modules"]])

    def test_module_depth_can_be_fixed(self):
        files = {"p/a/x.py": "from p.b import y\n", "p/b/y.py": "VALUE = 1\n", "p/main.py": "from p.a import x\n\nif __name__ == '__main__':\n    print(x)\n"}
        self.assertEqual([m["id"] for m in self.graph(files, depth=1)["modules"]], ["p"])

    def test_a_cycle_is_found_and_its_lighter_side_is_the_cut(self):
        g = self.graph(CYCLE)
        edges = {(e["from"], e["to"]): e for e in g["edges"]}
        self.assertEqual((edges[("a", "b")]["imports"], edges[("a", "b")]["files"]), (2, 1))
        self.assertEqual([c["modules"] for c in g["cycles"]], [["a", "b"]])
        cycle = g["cycles"][0]
        self.assertEqual([(e["from"], e["to"], e["imports"]) for e in cycle["cut"]], [("b", "a", 1)])
        self.assertEqual((cycle["imports"], cycle["cut_imports"]), (3, 1))
        self.assertEqual((edges[("a", "b")]["cut"], edges[("b", "a")]["cut"]), (False, True))
        self.assertEqual({m["id"]: m["cycle"] for m in g["modules"]}, {"a": 1, "b": 1})
        self.assertEqual(edges[("b", "a")]["cycle"], 1)

    def test_importing_a_submodule_does_not_depend_on_its_package(self):
        g = self.graph(files={"x.py": "import a.b.c\n\nif __name__ == '__main__':\n    print(a.b.c)\n", "a/__init__.py": "", "a/b/__init__.py": "", "a/b/c.py": "VALUE = 1\n"}, level="file")
        self.assertEqual(g["edges"], [["x.py", "a/b/c.py"]])

    def test_a_name_defined_in_the_package_does_depend_on_it(self):
        g = self.graph(files={"x.py": "from a import VALUE\n\nif __name__ == '__main__':\n    print(VALUE)\n", "a/__init__.py": "VALUE = 1\n"}, level="file")
        self.assertEqual(g["edges"], [["x.py", "a/__init__.py"]])

    def test_a_name_in_a_string_keeps_the_file_reachable_but_is_not_an_import(self):
        write_tree(self.root, {"x.py": "REGISTRY = {'w': 'a.b.c.Worker'}\n\nif __name__ == '__main__':\n    print(REGISTRY)\n", "a/__init__.py": "", "a/b/__init__.py": "", "a/b/c.py": "class Worker:\n    pass\n"})
        a = scan(self.root)
        self.assertIn("a/b/c.py", a.graph.edges["x.py"])
        self.assertEqual(a.records["a/b/c.py"].reachability, "prod")
        self.assertEqual(modules.build_graph(a, level="file")["edges"], [])

    def test_imports_inside_a_module_are_counted_but_are_not_dependencies(self):
        g = self.graph({"p/__init__.py": "", "p/a.py": "from p import b\n\nif __name__ == '__main__':\n    print(b)\n", "p/b.py": "VALUE = 1\n"})
        self.assertEqual([(m["id"], m["internal_imports"], m["uses"], m["used_by"]) for m in g["modules"]], [("p", 1, 0, 0)])
        self.assertEqual((g["edges"], g["summary"]["dependencies"], g["summary"]["imports"]), ([], 0, 1))

    def test_file_level_graph_lists_every_import_with_its_module(self):
        g = self.graph(level="file")
        self.assertEqual(g["kind"], "file-graph")
        self.assertEqual(g["summary"], {"files": 6, "imports": 3})
        self.assertIn(["app/main.py", "core/engine.py"], g["edges"])
        self.assertEqual({n["path"]: n["module"] for n in g["nodes"]}["core/engine.py"], "core")

    def test_output_is_deterministic(self):
        write_tree(self.root, PROJECT)
        a = scan(self.root)
        self.assertEqual(json.dumps(modules.build_graph(a)), json.dumps(modules.build_graph(a)))


class OwnersTest(TempRepo):
    def test_modules_carry_their_owners_and_never_an_address(self):
        git(self.root, "init", "-q", "-b", "main")
        write_tree(self.root, PROJECT)
        git(self.root, "add", "-A")
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        git(self.root, "commit", "-q", "-m", "init", when=when, author=("Alice Adams", "alice@example.com"))
        g = modules.build_graph(scan(self.root))
        by_id = {m["id"]: m for m in g["modules"]}
        self.assertEqual(by_id["core"]["owners"][0], {"name": "Alice Adams", "share": 100, "idle_days": 0})
        self.assertEqual(by_id["core"]["ownership"], "owned")
        self.assertNotIn("alice@example.com", json.dumps(g))
        found = modules.impact(scan(self.root), "util")
        self.assertEqual(found["owners"][0]["name"], "Alice Adams")
        self.assertNotIn("@", json.dumps(found))

    def test_without_git_there_are_no_owners(self):
        write_tree(self.root, PROJECT)
        g = modules.build_graph(scan(self.root))
        self.assertNotIn("owners", g["modules"][0])
        self.assertNotIn("owners", modules.impact(scan(self.root), "util"))


class ImpactTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, PROJECT)
        self.a = scan(self.root)

    def test_a_file_reaches_its_importers_and_theirs(self):
        found = modules.impact(self.a, "util/helpers.py")
        self.assertEqual((found["kind"], found["files"], found["module"]), ("file", 1, "util"))
        self.assertEqual(found["dependents"]["files"], 2)  # core/engine.py and app/main.py, both one import away
        self.assertEqual(found["dependents"]["direct"], 2)
        self.assertEqual({m["module"]: m["files"] for m in found["dependents"]["modules"]}, {"app": 1, "core": 1})
        self.assertEqual(found["tests"], {"files": 1, "direct": 0, "paths": ["tests/test_engine.py"]})  # two hops away, through the engine
        self.assertEqual(found["depends_on"], [])

    def test_candidates_are_held_against_a_report_when_one_is_given(self):
        report = {"sources": ["r.xml"], "cases": 3, "files": {"tests/test_engine.py": {"passed": 2, "failed": 0, "skipped": 0}}, "unmatched": {"cases": 1, "named": ["elsewhere"]}}
        found = modules.impact(self.a, "util/helpers.py", report=report)
        self.assertEqual(found["tests"]["report"], {"sources": ["r.xml"], "cases": 3, "ran": {"tests/test_engine.py": "passed"}, "passed": 1, "failed": [], "skipped": 0, "not_run": [], "unmatched": {"cases": 1, "named": ["elsewhere"]}})
        text = graphview.impact_text(found)
        self.assertIn("- in the report (`r.xml`): 1 of them ran, 1 passed, 0 failed; 0 did not run (the report also has 1 cases of no file in this repository)", text)
        self.assertIn("Tests that reach it, nearest first: `tests/test_engine.py` (passed)", text)
        self.assertNotIn("report", modules.impact(self.a, "util/helpers.py")["tests"])

    def test_distances_are_counted(self):
        found = modules.impact(self.a, "util/helpers.py")
        self.assertEqual(found["dependents"]["by_distance"], [2])
        self.assertEqual(modules.impact(self.a, "core/__init__.py")["dependents"]["by_distance"][:1], [1])

    def test_hops_limit_how_far_it_follows(self):
        self.assertEqual(modules.impact(self.a, "util/helpers.py", hops=1)["tests"]["files"], 0)
        self.assertEqual(modules.impact(self.a, "util/helpers.py", hops=2)["tests"]["files"], 1)

    def test_a_directory_and_a_dotted_name_both_work(self):
        by_dir = modules.impact(self.a, "core")
        self.assertEqual((by_dir["kind"], by_dir["files"]), ("directory", 2))
        self.assertEqual(by_dir["dependents"]["files"], 1)  # app/main.py
        self.assertEqual(by_dir["depends_on"], [{"module": "util", "files": 1}])
        self.assertEqual(modules.impact(self.a, "core/")["target"], "core")
        self.assertEqual(modules.impact(self.a, "core.engine")["target"], "core/engine.py")
        self.assertEqual(modules.impact(self.a, "./util/helpers.py")["target"], "util/helpers.py")

    def test_a_package_init_is_affected_by_imports_that_only_pass_through_it(self):
        write_tree(self.root, {"x.py": "import a.b.c\n\nif __name__ == '__main__':\n    print(a.b.c)\n", "a/__init__.py": "", "a/b/__init__.py": "", "a/b/c.py": "VALUE = 1\n"})
        found = modules.impact(scan(self.root), "a/__init__.py")  # x.py never names it, but importing a.b.c runs it
        self.assertEqual([(m["module"], m["files"]) for m in found["dependents"]["modules"]], [(".", 1)])
        edges = modules.build_graph(scan(self.root), level="file")["edges"]
        self.assertIn(["x.py", "a/b/c.py"], edges)
        self.assertNotIn(["x.py", "a/__init__.py"], edges)

    def test_a_file_nothing_imports_has_no_dependents(self):
        found = modules.impact(self.a, "app/main.py")
        self.assertEqual((found["dependents"]["files"], found["tests"]["files"], found["dependents"]["by_distance"]), (0, 0, []))

    def test_cycles_terminate_and_leave_the_target_out(self):
        write_tree(self.root, CYCLE)
        found = modules.impact(scan(self.root), "a/x.py")
        self.assertEqual({m["module"] for m in found["dependents"]["modules"]}, {"b"})
        self.assertEqual(found["dependents"]["files"], 1)

    def test_unknown_and_unanalysed_targets_are_refused(self):
        with self.assertRaises(TargetError):
            modules.impact(self.a, "nowhere.py")
        write_tree(self.root, {"notes.md": "# notes\n"})
        with self.assertRaises(TargetError) as ctx:
            modules.impact(scan(self.root), "notes.md")
        self.assertIn("no analyzer", str(ctx.exception))


def sample_graph():
    mods = [
        {"id": "app", "files": 3, "code": 120, "cycle": None, "ownership": "owned", "owners": [{"name": "Alice", "share": 80, "idle_days": 1}], "contributors": 1, "uses": 2, "used_by": 0, "instability": 1.0},
        {"id": 'we"ird\\mod', "files": 2, "code": 0, "cycle": 1, "ownership": "no-active-owner", "owners": [], "contributors": 0, "uses": 1, "used_by": 1, "instability": 0.5},
        {"id": "lib", "files": 1, "code": 10, "cycle": 1, "ownership": "owned", "owners": [{"name": "Bob", "share": 100, "idle_days": 400}], "contributors": 1, "uses": 1, "used_by": 2, "instability": 0.33},
    ]
    edge = lambda a, b, n, cut=False, cyc=None: {"from": a, "to": b, "imports": n, "files": 1, "examples": [[f"{a}/x.py", f"{b}/y.py"]], "cycle": cyc, "cut": cut}  # noqa: E731
    edges = [edge("app", "lib", 9), edge("app", 'we"ird\\mod', 4), edge('we"ird\\mod', "lib", 3, cyc=1), edge("lib", 'we"ird\\mod', 1, cut=True, cyc=1)]
    cycle = {"id": 1, "modules": sorted(['we"ird\\mod', "lib"]), "imports": 4, "cut": [{k: edges[3][k] for k in ("from", "to", "imports", "files", "examples")}], "cut_imports": 1}
    return {
        "repo": {"name": "demo"},
        "settings": {"module_depth": None, "include_tests": False, "owner_inactive_days": 180},
        "summary": {"modules": 3, "dependencies": 4, "cycles": 1, "files": 6, "imports": 17},
        "modules": mods,
        "edges": edges,
        "cycles": [cycle],
        "caveats": ["static"],
    }


class ViewTest(unittest.TestCase):
    def test_mermaid_escapes_labels_and_marks_the_cut(self):
        text = graphview.mermaid(sample_graph())
        self.assertTrue(text.startswith("flowchart LR"))
        self.assertIn("#quot;", text)
        self.assertNotIn('we"ird', text)
        self.assertIn("n0 -->|9| n2", text)
        self.assertIn("linkStyle 3 stroke", text)  # the fourth arrow drawn is the cut one
        self.assertIn("class n1 noowner", text)

    def test_mermaid_marks_the_cut_arrow_by_its_position_among_the_drawn_ones(self):
        g = sample_graph()
        g["edges"] = [
            {"from": "app", "to": "lib", "imports": 1, "files": 1, "examples": [], "cycle": None, "cut": False},
            {"from": "app", "to": 'we"ird\\mod', "imports": 4, "files": 1, "examples": [], "cycle": None, "cut": False},
            {"from": "lib", "to": 'we"ird\\mod', "imports": 3, "files": 1, "examples": [], "cycle": 1, "cut": True},
        ]
        text = graphview.mermaid(g, min_imports=2)
        self.assertEqual(text.count("-->"), 2)
        self.assertIn("linkStyle 1 stroke", text)

    def test_dot_quotes_names(self):
        text = graphview.dot(sample_graph())
        self.assertIn('"we\\"ird\\\\mod"', text)
        self.assertIn('"lib" -> "we\\"ird\\\\mod" [label=1, color=red];', text)
        self.assertTrue(text.rstrip().endswith("}"))

    def test_a_big_graph_is_thinned_to_its_heaviest_dependencies(self):
        rng = random.Random(1)
        g = sample_graph()
        g["modules"] = [{**g["modules"][0], "id": f"m{i}"} for i in range(40)]
        g["edges"] = sorted(
            ({"from": f"m{a}", "to": f"m{b}", "imports": rng.randint(1, 12), "files": 1, "examples": [], "cycle": None, "cut": False} for a in range(40) for b in range(40) if a != b and rng.random() < 0.3),
            key=lambda e: -e["imports"],
        )
        modules_, edges, floor = graphview.drawn(g, None)
        self.assertLessEqual(len(edges), graphview.MAX_DRAWN)
        self.assertGreater(len(g["edges"]), graphview.MAX_DRAWN)
        dropped = [e["imports"] for e in g["edges"] if e not in edges]
        self.assertTrue(all(n < floor for n in dropped))
        self.assertTrue(all(e["imports"] >= floor for e in edges))
        self.assertEqual({m["id"] for m in modules_}, {e["from"] for e in edges} | {e["to"] for e in edges})
        self.assertIn(f"at least {floor} imports", graphview.mermaid(g))
        self.assertEqual(len(graphview.drawn(g, 1)[1]), len(g["edges"]))

    def test_markdown_lists_cycles_modules_and_dependencies(self):
        text = graphview.markdown(sample_graph())
        for want in ("# Module graph: demo", "**Cycle 1**", "1 dependency (1 import) to cut", "## Modules", "## Heaviest dependencies", "Bob 100% (silent 400d)", "no code", "cut to break cycle 1"):
            self.assertIn(want, text)

    def test_markdown_says_so_when_there_are_no_cycles(self):
        g = sample_graph()
        g["cycles"] = []
        self.assertIn("No cycles", graphview.markdown(g))


class CliTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, PROJECT)

    def test_graph_in_each_format(self):
        code, out, _ = run_cli("graph", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("# Module graph", out)
        code, out, _ = run_cli("graph", str(self.root), "--format", "json")
        self.assertEqual(json.loads(out)["kind"], "module-graph")
        self.assertTrue(run_cli("graph", str(self.root), "--format", "mermaid")[1].startswith("flowchart"))
        self.assertTrue(run_cli("graph", str(self.root), "--format", "dot")[1].startswith("digraph"))

    def test_file_level_needs_json(self):
        code, _, err = run_cli("graph", str(self.root), "--level", "file")
        self.assertEqual(code, 2)
        self.assertIn("--format json", err)
        code, out, _ = run_cli("graph", str(self.root), "--level", "file", "--format", "json")
        self.assertEqual((code, json.loads(out)["kind"]), (0, "file-graph"))

    def test_module_depth_must_be_positive(self):
        self.assertEqual(run_cli("graph", str(self.root), "--module-depth", "0")[0], 2)

    def test_module_depth_changes_the_modules(self):
        write_tree(self.root, {"pkg/a/x.py": "from pkg.b import y\n", "pkg/b/y.py": "VALUE = 1\n"})
        ids = lambda *extra: [m["id"] for m in json.loads(run_cli("graph", str(self.root), "--format", "json", *extra)[1])["modules"]]  # noqa: E731
        self.assertIn("pkg", ids())
        self.assertNotIn("pkg/a", ids())
        self.assertEqual([i for i in ids("--module-depth", "2") if i.startswith("pkg")], ["pkg/a", "pkg/b"])

    def test_graph_can_be_written_to_a_file(self):
        target = self.root / "out" / "graph.json"
        code, out, err = run_cli("graph", str(self.root), "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("wrote", err)
        self.assertEqual(json.loads(target.read_text())["summary"]["modules"], 3)

    def test_impact_as_text_and_json(self):
        code, out, _ = run_cli("impact", "util/helpers.py", "--repo", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("Changing util/helpers.py", out)
        self.assertIn("`core`", out)
        code, out, _ = run_cli("impact", "util", "--repo", str(self.root), "--format", "json")
        self.assertEqual(json.loads(out)["kind"], "directory")

    def test_impact_hops(self):
        tests = lambda *extra: json.loads(run_cli("impact", "util/helpers.py", "--repo", str(self.root), "--format", "json", *extra)[1])["tests"]["files"]  # noqa: E731
        self.assertEqual((tests(), tests("--hops", "1")), (1, 0))

    def test_impact_reports_a_bad_target_without_a_traceback(self):
        code, out, err = run_cli("impact", "nowhere.py", "--repo", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("nowhere.py", err)


if __name__ == "__main__":
    unittest.main()
