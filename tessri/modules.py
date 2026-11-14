"""The import graph rolled up into modules, and the blast radius of changing one file or module.

Edges come from the analyzers: file A imports file B. References from config and docs are not
dependencies and stay out. A module is a directory. Unless a depth is given, directories are split until
none holds much more than a twelfth of the code files, so a repository with one big package still gets a
useful picture instead of a single node.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

from . import __version__, meta
from .analyze import Analysis
from .explain import TargetError, resolve_target
from .model import SCHEMA_VERSION, STATUSES
from .analyzers import KINDS
from .ownership import Area, owner_rows, rollup

MIN_CAP = 20  # a directory with at most this many files is never split
TARGET_MODULES = 12  # otherwise split until the biggest module holds about 1/12 of the files
MAX_DEPTH = 6
EXAMPLES = 3  # sample imports kept per dependency
IMPACT_OWNERS = 5  # people listed as affected by a change
IMPACT_TESTS = 40  # test files listed per impact
POLICIES = {"all": frozenset(KINDS), "imports": frozenset({"import", "package"})}  # `impact --edges`: which evidence to follow
REFERENCE_KINDS = frozenset({"dynamic", "string", "unknown"})  # evidence that is not recognized dependency syntax
REFERENCES_LISTED = 8  # references listed in the impact result; the count is always complete

CAVEATS = [
    "Edges are static imports between files in this repository. Dynamic imports, plugin registries, "
    "dependency injection and consumers outside the repository are invisible.",
    "A re-exporting `__init__.py` or index file pulls in every module that imports through it, so a hub package looks more tangled than its real call graph.",
]


def assign(paths: Iterable[str], depth: int | None = None) -> dict[str, str]:
    """path -> module key (its directory, "." for files at the top). With `depth`, keep that many leading
    directories; without, descend only while a directory holds more than its share of the files."""
    parts = {p: tuple(p.split("/")[:-1]) for p in paths}
    if depth is not None:
        return {p: "/".join(d[:depth]) or "." for p, d in parts.items()}
    cap = max(MIN_CAP, len(parts) // TARGET_MODULES)
    size: Counter[tuple[str, ...]] = Counter()
    for d in parts.values():
        for k in range(1, len(d) + 1):
            size[d[:k]] += 1
    out = {}
    for p, d in parts.items():
        k = min(len(d), 1)
        while k < len(d) and k < MAX_DEPTH and size[d[:k]] > cap:
            k += 1
        out[p] = "/".join(d[:k]) or "."
    return out


def components(nodes: Iterable[str], adj: Mapping[str, Iterable[str]]) -> list[list[str]]:
    """Strongly connected components with more than one node: groups that all reach each other
    (iterative Tarjan, so a deep graph cannot hit the recursion limit)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: list[list[str]] = []
    counter = 0
    for start in sorted(set(nodes)):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(adj.get(start, ()))))]
        while work:
            node, successors = work[-1]
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(adj.get(nxt, ())))))
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    group = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        group.append(member)
                        if member == node:
                            break
                    if len(group) > 1:
                        found.append(sorted(group))
    return sorted(found, key=lambda g: (-len(g), g))


def cut_edges(nodes: Iterable[str], weight: Mapping[tuple[str, str], int]) -> list[tuple[str, str]]:
    """Dependencies to remove or invert so that no cycle is left, chosen to be few and light.

    Orders the modules so that most weight points forward (Eades, Lin and Smyth's greedy: peel off sinks and
    sources, otherwise the module that sends out the most more than it takes in), then returns the edges that
    point backwards, minus any that closes no cycle once the rest are in place. It is a heuristic: the true
    minimum is NP-hard, but removing exactly these edges always leaves an acyclic graph, and putting back
    any one of them makes a cycle again.
    """
    left = set(nodes)
    out_w: dict[str, dict[str, int]] = {n: {} for n in left}
    in_w: dict[str, dict[str, int]] = {n: {} for n in left}
    for (s, t), w in weight.items():
        if s in left and t in left and s != t:
            out_w[s][t] = in_w[t][s] = w
    front: list[str] = []
    back: list[str] = []

    def take(n: str) -> None:
        left.discard(n)
        for t in out_w[n]:
            in_w[t].pop(n, None)
        for s in in_w[n]:
            out_w[s].pop(n, None)

    while left:
        peeled = True
        while peeled:
            peeled = False
            for n in sorted(left):
                if n in left and not out_w[n]:
                    back.append(n)
                    take(n)
                    peeled = True
                elif n in left and not in_w[n]:
                    front.append(n)
                    take(n)
                    peeled = True
        if left:
            best = min(left, key=lambda n: (-(sum(out_w[n].values()) - sum(in_w[n].values())), n))
            front.append(best)
            take(best)
    position = {n: i for i, n in enumerate(front + back[::-1])}
    edges = [(s, t) for (s, t) in weight if s != t and s in position and t in position]
    against = {(s, t) for (s, t) in edges if position[s] > position[t]}
    kept: dict[str, set[str]] = defaultdict(set)
    for s, t in edges:
        if (s, t) not in against:
            kept[s].add(t)
    for s, t in sorted(against, key=lambda e: (-weight[e], e)):  # heaviest first: keep every edge that closes no cycle
        if not _reaches(kept, t, s):
            kept[s].add(t)
            against.discard((s, t))
    return sorted(against)


def _reaches(adj: Mapping[str, Iterable[str]], start: str, goal: str) -> bool:
    seen = {start}
    stack = [start]
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _contributors(area: Area) -> int:
    """People with at least 1% of the area's code."""
    return sum(lines * 100 >= area.code for lines in area.lines.values())


def _header(a: Analysis, kind: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "tessri", "version": __version__},
        "generated_at": datetime.fromtimestamp(a.now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {"name": a.root.name},
        "kind": kind,
        "meta": meta.of(a),
    }


def _imported(a: Analysis, path: str) -> set[str]:
    """What the import statements of `path` name. Importing `a.b.c` also runs the `__init__` of `a` and `a.b`, which
    would make every package look like a dependency of everything beneath it; paths and names in strings are
    guesses. Both are left out."""
    g = a.graph
    return g.edges.get(path, set()) - g.indirect.get(path, set()) - {path}


def _members(a: Analysis, include_tests: bool) -> list[str]:
    """Files that can be nodes: code the analyzers understood."""
    return sorted(p for p, r in a.records.items() if r.kind == "code" and r.analyzer and (include_tests or not r.is_test))


def build_graph(a: Analysis, depth: int | None = None, include_tests: bool = False, level: str = "module", assignment: Mapping[str, str] | None = None) -> dict:
    """`assignment` fixes the module of every file in advance, so two states of one repository can be compared module
    by module instead of each choosing its own split."""
    paths = _members(a, include_tests)
    member = set(paths)
    module_of = {p: assignment[p] for p in paths} if assignment is not None else assign(paths, depth)
    imports = sorted((s, t) for s in member for t in _imported(a, s) if t in member)

    if level == "file":
        out = _header(a, "file-graph")
        out["settings"] = {"module_depth": depth, "include_tests": include_tests}
        out["summary"] = {"files": len(paths), "imports": len(imports)}
        out["nodes"] = [_file_node(a, p, module_of[p]) for p in paths]
        out["edges"] = [[s, t] for s, t in imports]
        out["caveats"] = CAVEATS
        return out

    internal: Counter[str] = Counter()
    links: Counter[tuple[str, str]] = Counter()
    sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    examples: dict[tuple[str, str], list[list[str]]] = defaultdict(list)
    for s, t in imports:
        ms, mt = module_of[s], module_of[t]
        if ms == mt:
            internal[ms] += 1
            continue
        key = (ms, mt)
        links[key] += 1
        sources[key].add(s)
        if len(examples[key]) < EXAMPLES:
            examples[key].append([s, t])

    keys = sorted(set(module_of.values()))
    adj: dict[str, set[str]] = {k: set() for k in keys}
    uses: dict[str, set[str]] = {k: set() for k in keys}
    used_by: dict[str, set[str]] = {k: set() for k in keys}
    for ms, mt in links:
        adj[ms].add(mt)
        uses[ms].add(mt)
        used_by[mt].add(ms)
    cycles = components(keys, adj)
    cycle_of = {m: i for i, group in enumerate(cycles, 1) for m in group}
    cut: set[tuple[str, str]] = set()
    for group in cycles:
        inside = {k: n for k, n in links.items() if k[0] in group and k[1] in group}
        cut.update(cut_edges(group, inside))

    by_module: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        by_module[module_of[p]].append(p)
    nodes = []
    for key in keys:
        recs = [a.records[p] for p in by_module[key]]
        node = {
            "id": key,
            "files": len(recs),
            "code": sum(r.code for r in recs),
            "status": {s.lower(): sum(r.code for r in recs if r.status == s) for s in STATUSES},
            "commits_year": sum(r.commits_year for r in recs),
            "uses": len(uses[key]),
            "used_by": len(used_by[key]),
            "instability": round(len(uses[key]) / (len(uses[key]) + len(used_by[key])), 2) if uses[key] or used_by[key] else None,
            "internal_imports": internal[key],
            "cycle": cycle_of.get(key),
        }
        if include_tests:
            node["tests"] = bool(recs) and all(r.is_test for r in recs)
        if a.ownership is not None:
            area = rollup(a.ownership, ((r.path, r.code) for r in recs))
            node["owners"], node["contributors"], node["ownership"] = owner_rows(area.owners), _contributors(area), area.state
        nodes.append(node)

    edges = [
        {
            "from": ms,
            "to": mt,
            "imports": n,
            "files": len(sources[(ms, mt)]),
            "examples": examples[(ms, mt)],
            "cycle": cycle_of[ms] if cycle_of.get(ms) is not None and cycle_of.get(ms) == cycle_of.get(mt) else None,
            "cut": (ms, mt) in cut,
        }
        for (ms, mt), n in sorted(links.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    cycle_rows = []
    for i, group in enumerate(cycles, 1):
        inside = [e for e in edges if e["cycle"] == i]
        removed = [e for e in inside if e["cut"]]
        cycle_rows.append(
            {
                "id": i,
                "modules": group,
                "imports": sum(e["imports"] for e in inside),
                "cut": [{k: e[k] for k in ("from", "to", "imports", "files", "examples")} for e in removed],
                "cut_imports": sum(e["imports"] for e in removed),
            }
        )

    out = _header(a, "module-graph")
    out["settings"] = {"module_depth": depth, "include_tests": include_tests, "owner_inactive_days": a.cfg.owner_inactive_days}
    out["summary"] = {"modules": len(keys), "dependencies": len(edges), "cycles": len(cycles), "files": len(paths), "imports": len(imports)}
    out["modules"] = nodes
    out["edges"] = edges
    out["cycles"] = cycle_rows
    out["caveats"] = CAVEATS
    return out


def _file_node(a: Analysis, path: str, module: str) -> dict:
    r = a.records[path]
    node = {"path": path, "module": module, "language": r.language, "code": r.code, "status": r.status, "test": r.is_test}
    if r.ownership is not None:
        node["owner"], node["ownership"] = r.owner, r.ownership
    return node


# --- blast radius ----------------------------------------------------------------------------------------


def resolve_seeds(a: Analysis, target: str) -> tuple[str, str, list[str]]:
    """(label, "file" | "directory", files) for a path, a directory or a dotted package name."""
    name = target.strip()
    while name.startswith("./"):
        name = name[2:]
    name = name.rstrip("/")
    if name in a.records:
        return _only_analysed(a, name, "file", [name])
    for folder in dict.fromkeys((name, name.replace(".", "/"))):
        under = sorted(p for p, r in a.records.items() if p.startswith(folder + "/") and r.kind == "code" and r.analyzer)
        if folder and under:
            return folder, "directory", under
    path = resolve_target(a, name)
    return _only_analysed(a, path, "file", [path])


def _only_analysed(a: Analysis, label: str, kind: str, files: list[str]) -> tuple[str, str, list[str]]:
    rec = a.records[files[0]]
    if not rec.analyzer:
        raise TargetError(f"`{label}` is {rec.language}, which no analyzer covers, so its dependents are unknown")
    return label, kind, files


def _walk(a: Analysis, seeds: list[str], hops: int | None, allowed: frozenset[str]) -> tuple[dict[str, int], dict]:
    """Breadth-first over the dependents of `seeds`, following only edges whose evidence kind is in `allowed`.

    Returns the distance of every file reached and the statistics of the walk. Every inbound edge of an expanded
    node is counted once per (source, target) pair, followed or excluded by its kind; a node at the hop limit is not
    expanded, so the counts describe the visited frontier, not every edge in the repository. A followed edge may
    lead to a file already reached, so edge counts are not file counts."""
    g = a.graph
    dist = {s: 0 for s in seeds}
    queue = deque(seeds)
    followed: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    references: list[dict] = []  # the edges met that are not recognized dependency syntax, in walk order
    unknown_from: set[str] = set()  # files whose analyzer gave no provenance for an edge met
    while queue:
        node = queue.popleft()
        if hops is not None and dist[node] >= hops:
            continue
        for dependent in sorted(g.inbound.get(node, ())):
            kind = g.kind(dependent, node)
            if kind in REFERENCE_KINDS:
                references.append({"from": dependent, "to": node, "kind": kind})
                if kind == "unknown":
                    unknown_from.add(dependent)
            if kind not in allowed:
                excluded[kind] += 1
                continue
            followed[kind] += 1
            if dependent not in dist:
                dist[dependent] = dist[node] + 1
                queue.append(dependent)
    return dist, {"followed": followed, "excluded": excluded, "references": references, "unknown_from": unknown_from}


def impact(a: Analysis, target: str, depth: int | None = None, limit: int = IMPACT_TESTS, hops: int | None = None, edges: str = "all", report: dict | None = None) -> dict:
    """Everything that would be affected by changing `target`: files that depend on it directly or through others,
    following at most `hops` edges of the kinds the policy `edges` allows ("all": every edge an analyzer found;
    "imports": recognized dependency syntax and the package initializers Python runs for it). A package's
    `__init__` runs for every import beneath it, so those count under both policies. With `report`, a test report
    the host wrote as `runs.load` reads it, the candidate tests are held against what ran."""
    from . import runs as testruns

    if edges not in POLICIES:
        raise ValueError(f"unknown edge policy {edges!r}; choose one of {', '.join(POLICIES)}")
    label, kind, seeds = resolve_seeds(a, target)
    g = a.graph
    seed_set = set(seeds)
    allowed = POLICIES[edges]
    dist, walk = _walk(a, seeds, hops, allowed)
    affected = {p: d for p, d in dist.items() if p not in seed_set and p in a.records}
    prod = {p: d for p, d in affected.items() if not a.records[p].is_test}
    tests = {p: d for p, d in affected.items() if a.records[p].is_test}

    pool = _members(a, include_tests=False)
    module_of = assign(pool, depth)
    grouped: dict[str, list[str]] = defaultdict(list)
    for p in prod:
        grouped[module_of.get(p, ".")].append(p)
    modules = []
    for key, files in grouped.items():
        row = {"module": key, "direct": sum(prod[p] == 1 for p in files), "files": len(files), "code": sum(a.records[p].code for p in files)}
        if a.ownership is not None:
            area = rollup(a.ownership, ((p, a.records[p].code) for p in files))
            row["owners"], row["contributors"], row["ownership"] = owner_rows(area.owners), _contributors(area), area.state
        modules.append(row)
    modules.sort(key=lambda r: (-r["files"], r["module"]))

    needs: dict[str, set[str]] = defaultdict(set)  # forward: what the seeds name as dependencies, never the reverse walk
    for s in seeds:
        for dep in _imported(a, s):
            if dep not in seed_set and dep in a.records and not a.records[dep].is_test and (edges == "all" or g.kind(s, dep) in allowed):
                needs[module_of.get(dep, ".")].add(dep)

    ordered_tests = sorted(tests, key=lambda p: (tests[p], p))
    refs = walk["references"]
    unknown_edges = walk["followed"]["unknown"] + walk["excluded"]["unknown"]
    evidence = {
        "policy": edges,
        "hops": hops,
        "kinds": [k for k in KINDS if k in allowed],
        "followed": {k: walk["followed"][k] for k in KINDS if k in allowed},
        "excluded": {k: walk["excluded"][k] for k in KINDS if k not in allowed},
        "references": {"count": len(refs), "limit": REFERENCES_LISTED, "listed": refs[:REFERENCES_LISTED]},
        "unclassified": {"edges": unknown_edges, "analyzers": sorted({a.records[p].analyzer or "?" for p in walk["unknown_from"] if p in a.records})},
    }
    if edges == "all":  # what the narrower policy would reach from the same seeds under the same hop limit
        narrow, _ = _walk(a, seeds, hops, POLICIES["imports"])
        reached = [p for p, d in narrow.items() if p not in seed_set and p in a.records]
        evidence["imports_only"] = {"files": sum(not a.records[p].is_test for p in reached), "tests": sum(a.records[p].is_test for p in reached)}
    out = {
        "schema_version": SCHEMA_VERSION,
        "target": label,
        "kind": kind,
        "meta": meta.of(a),
        "files": len(seeds),
        "code": sum(a.records[p].code for p in seeds),
        "module": module_of.get(seeds[0]) if kind == "file" else None,
        "dependents": {
            "direct": sum(d == 1 for d in prod.values()),
            "files": len(prod),
            "code": sum(a.records[p].code for p in prod),
            "share": round(100 * len(prod) / len(pool), 1) if pool else 0.0,
            "by_distance": [sum(d == n for d in prod.values()) for n in range(1, max(prod.values(), default=0) + 1)],
            "modules": modules,
        },
        "tests": {"files": len(tests), "direct": sum(d == 1 for d in tests.values()), "paths": ordered_tests[:limit], **({"report": testruns.against(report, ordered_tests)} if report is not None else {})},
        "edges": evidence,
        "depends_on": [{"module": k, "files": len(v)} for k, v in sorted(needs.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
    }
    if a.ownership is not None:
        area = rollup(a.ownership, ((p, a.records[p].code) for p in prod))
        out["owners"], out["contributors"] = owner_rows(area.owners, IMPACT_OWNERS), _contributors(area)
        out["inactive_days"] = a.ownership.inactive_days
    return out


# --- data for the explorer in the HTML report -------------------------------------------------------------

EXPLORER_MAX_FILES = 20000  # past this the page would be too heavy to carry the import graph


def explorer(a: Analysis) -> dict | None:
    """Everything a browser needs to answer `impact` for any file or directory: the analysed code files, the
    modules the non-test ones fall into, who owns each, and each relationship's legacy flag and evidence kind.
    None when there is nothing to explore or too much of it."""
    paths = sorted(p for p, r in a.records.items() if r.kind == "code" and r.analyzer)
    if not paths or len(paths) > EXPLORER_MAX_FILES:
        return None
    g = a.graph
    pool = [p for p in paths if not a.records[p].is_test]
    module_of = assign(pool)
    keys = sorted(set(module_of.values()))
    people: dict[str, int] = {}
    people_rows: list[dict] = []
    files = []
    for p in paths:
        r = a.records[p]
        who = -1
        if r.owner:
            if r.owner not in people:
                people[r.owner] = len(people_rows)
                people_rows.append({"name": r.owner, "idle_days": r.owner_idle_days})
            who = people[r.owner]
        files.append([p, keys.index(module_of[p]) if p in module_of else -1, r.code, int(r.is_test), who, r.analyzer])
    index = {p: i for i, p in enumerate(paths)}
    edges = sorted(
        (index[s], index[t], int(t in g.indirect.get(s, ())), g.kind(s, t))
        for s in paths
        for t in g.edges.get(s, ())
        if t in index and t != s
    )
    return {"modules": keys, "files": files, "edges": [list(e) for e in edges], "people": people_rows, "inactive_days": a.cfg.owner_inactive_days}
