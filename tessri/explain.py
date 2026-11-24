"""`tessri why <file>`: the evidence behind a file's verdict, for agents and humans verifying a candidate.
`facts` collects it as data, `explain` renders that data as text and `why_json` wraps it for `--format json`, so
the two outputs cannot disagree."""

from __future__ import annotations

from collections import deque

from . import mentions, meta
from .analyze import Analysis
from .model import SCHEMA_VERSION

_REACH_TEXT = {
    "prod": "reachable from a production entry point",
    "test": "reachable only from tests",
    "none": "NOT reachable from any entry point, test or config reference",
}

ORPHAN_ADVICE = (
    "Before deleting: search the repo for the file's module name and public symbols (dynamic lookups, "
    "registries, external consumers), and run the test suite. If the file is intentionally public, add it "
    "to `keep` in .tessri.toml."
)


class TargetError(LookupError):
    pass


def resolve_target(a: Analysis, target: str) -> str:
    target = target.strip()
    while target.startswith("./"):
        target = target[2:]
    if target in a.records:
        return target
    suffix = [p for p in a.records if p.endswith("/" + target)]
    if len(suffix) == 1:
        return suffix[0]
    dotted = target.replace(".", "/")
    by_module = [p for p in a.records if p in (dotted + ".py", dotted + "/__init__.py")]
    if len(by_module) == 1:
        return by_module[0]
    options = suffix or by_module
    if options:
        raise TargetError(f"`{target}` is ambiguous: " + ", ".join(sorted(options)[:8]))
    raise TargetError(f"`{target}` is not a file in the analysed set (excluded, binary or unknown type?)")


def _fmt(items, empty="none", cap=12) -> str:
    items = sorted(items)
    if not items:
        return empty
    shown = ", ".join(items[:cap])
    return shown + (f" (+{len(items) - cap} more)" if len(items) > cap else "")


def _kinded(label: str, kind: str) -> str:
    """An edge's label with the kind of its evidence when that is anything but an import statement, so a string
    reference or a package file is never mistaken for one; an import is the default and goes unmarked."""
    return label if kind == "import" else f"{label} ({kind})"


def reaching_tests(a: Analysis, path: str) -> list[str]:
    """The test files from which the edges lead to `path`, following every edge the analyzers found, any number of
    steps (what `impact` follows under its default policy), nearest first."""
    g = a.graph
    dist = {path: 0}
    queue = deque([path])
    while queue:
        node = queue.popleft()
        for dependent in g.inbound.get(node, ()):
            if dependent not in dist:
                dist[dependent] = dist[node] + 1
                queue.append(dependent)
    del dist[path]
    return sorted((p for p in dist if p in a.records and a.records[p].is_test), key=lambda p: (dist[p], p))


def facts(a: Analysis, target: str) -> dict:
    """What is known about one file, as data: the verdict and its reasons, the file's history, who maintains it,
    its place in the import graph and, for a code file, its definitions with the reaching tests that name each.
    `git`, `owners` and `graph` are None when the analysis had nothing to say (no history, no ownership, no analyzer
    for the language), `definitions` None for a file that is not code, and `share` is a percentage as the text shows
    it."""
    path = resolve_target(a, target)
    rec = a.records[path]
    g = a.graph
    out: dict = {
        "query": target,
        "path": path,
        "file": {
            "language": rec.language,
            "kind": rec.kind,
            "code": rec.code,
            "comment": rec.comment,
            "blank": rec.blank,
            "test": rec.is_test,
            "analyzer": rec.analyzer,
        },
        "verdict": {
            "status": rec.status,
            "confidence": rec.confidence,
            "reachability": rec.reachability,
            "entry_points": list(rec.roots),
            "notes": list(rec.notes),
        },
        "git": None,
        "owners": None,
        "graph": None,
        "definitions": None,
        "advice": ORPHAN_ADVICE if rec.status == "ORPHAN" else None,
    }
    if rec.kind == "code":
        if rec.is_test:
            out["definitions"] = {"available": False, "reason": "a test file: its definitions are not held against the tests"}
        else:
            tests = reaching_tests(a, path) if rec.analyzer else []
            out["definitions"] = mentions.for_file(a.root, path, rec.language, tests, {t: a.records[t].language for t in tests})
    if a.activity is not None:
        out["git"] = {
            "tracked": rec.tracked,
            "last_commit": rec.last_commit,
            "age_days": rec.age_days,
            "first_commit": rec.first_commit,
            "commits_active": rec.commits_active,
            "commits_year": rec.commits_year,
            "authors_year": rec.authors_year,
            "fixes_90": rec.fixes_90,
            "fixes_year": rec.fixes_year,
        }
    found = a.ownership.files.get(path) if a.ownership else None
    if found is not None:
        own = a.ownership
        out["owners"] = {
            "state": found.state,
            "inactive_days": own.inactive_days,
            "people": [
                {"name": o.name, "share": round(100 * o.share), "idle_days": o.idle_days, "silent": o.idle_days > own.inactive_days}
                for o in own.owners(found.shares)
            ],
            "codeowners": None if found.declared is None else {"declared": list(found.declared), "match": found.declared_match},
        }
    if rec.analyzer:
        route = g.chain(path)
        dependents = sorted(g.inbound.get(path, ()))
        depends_on = sorted(g.edges.get(path, ()))
        out["graph"] = {
            "reached_via": route,
            "dependents": dependents,
            "config_refs": sorted(g.config_refs.get(path, ())),
            "doc_refs": sorted(g.doc_refs.get(path, ())),
            "depends_on": [{"path": d, "status": a.records[d].status if d in a.records else None} for d in depends_on],
            "stranded_if_removed": g.stranded_if_removed(path),
            # The evidence behind each edge above (analyzers.KINDS): an import statement, a package file Python runs,
            # a dynamic-import pattern, a name in a string, or unknown. `reached_via` has one entry per hop.
            "kinds": {
                "reached_via": [g.kind(src, dst) for src, dst in zip(route, route[1:])],
                "dependents": {d: g.kind(d, path) for d in dependents},
                "depends_on": {d: g.kind(path, d) for d in depends_on},
            },
        }
    return out


def render(f: dict) -> str:
    """The text of `tessri why`, from `facts`."""
    file, verdict = f["file"], f["verdict"]
    out = [f"{f['path']}  ({file['language']}, {file['code']} code lines)"]

    if verdict["status"]:
        out.append("status:        " + verdict["status"] + (f" (confidence {verdict['confidence']})" if verdict["confidence"] else ""))
    if file["analyzer"] is None:
        out.append(f"reachability:  not analysed (no analyzer for {file['language']})")
    else:
        out.append(f"reachability:  {_REACH_TEXT[verdict['reachability']]}")
    if verdict["entry_points"]:
        out.append("entry point:   " + "; ".join(verdict["entry_points"]))
    if file["test"]:
        out.append("kind:          test file")

    git = f["git"]
    if git is not None:
        if git["tracked"]:
            out.append(
                f"git:           last commit {git['last_commit']} ({git['age_days']}d ago), first {git['first_commit']}; "
                f"{git['commits_year']} commits / {git['authors_year']} authors in the last 365d"
            )
        else:
            out.append("git:           no history for this file (new or untracked)")

    owners = f["owners"]
    if owners is not None:
        who = ", ".join(f"{p['name']} {p['share']}%" + (f" (silent {p['idle_days']}d)" if p["silent"] else "") for p in owners["people"])
        out.append(f"owners:        {who or 'none (no usable history)'}" + ("; NO ACTIVE OWNER" if owners["state"] == "no-active-owner" else ""))
        declared = owners["codeowners"]
        if declared is not None:
            check = {True: "includes a person who maintains it", False: "none of them maintains it", None: "cannot be compared with the commit authors"}[declared["match"]]
            out.append(f"CODEOWNERS:    {' '.join(declared['declared']) or 'no declared owner'}" + (f" ({check})" if declared["declared"] else ""))

    graph = f["graph"]
    if graph is not None:
        kinds = graph["kinds"]
        if len(graph["reached_via"]) > 1:
            route = graph["reached_via"]
            hops = "".join(f" -> {dst}" if kind == "import" else f" -({kind})-> {dst}" for dst, kind in zip(route[1:], kinds["reached_via"]))
            out.append("reached via:   " + route[0] + hops)
        out.append(f"depended on by: {_fmt(_kinded(d, kinds['dependents'][d]) for d in graph['dependents'])}")
        out.append(f"named in config/scripts: {_fmt(graph['config_refs'])}")
        out.append(f"mentioned in docs: {_fmt(graph['doc_refs'])}")
        out.append("depends on:    " + _fmt(_kinded(f"{d['path']} [{d['status']}]" if d["status"] else d["path"], kinds["depends_on"][d["path"]]) for d in graph["depends_on"]))
        if graph["stranded_if_removed"]:
            out.append(f"deleting it would also strand: {_fmt(graph['stranded_if_removed'])}")

    d = f["definitions"]
    if d is not None and file["analyzer"] and not file["test"] and (not d["available"] or d["items"]):
        out.append("definitions:   " + (_definitions_text(d) if d["available"] else f"not read ({d['reason']})"))

    for note in verdict["notes"]:
        out.append(f"note:          {note}")
    if f["advice"]:
        out += ["", f["advice"]]
    return "\n".join(out)


def _definitions_text(d: dict) -> str:
    """One line on the definitions of a file: how many, and by name how the reaching tests treat them."""
    items = d["items"]
    parts = [str(len(items))]
    if d["tests"] == 0:
        parts.append("no test reaches the file")
    else:
        parts.append(f"named in a reaching test: {d['named']}")
        if d["unnamed"]:
            parts.append("named in none: " + _fmt([i["name"] for i in items if i["named_in"] == []], cap=6))
    if d["unsearched"]:
        parts.append("not searched (too short, private or too common): " + _fmt([i["name"] for i in items if i["named_in"] is None], cap=6))
    if d["unread"]:
        parts.append(f"{len(d['unread'])} reaching test{'s' if len(d['unread']) != 1 else ''} could not be read: " + _fmt(d["unread"], cap=4))
    return "; ".join(parts)


def explain(a: Analysis, target: str) -> str:
    return render(facts(a, target))


def why_json(a: Analysis, target: str) -> dict:
    """The `--format json` result for one target: the facts the text shows, plus the metadata block."""
    return {"schema_version": SCHEMA_VERSION, "kind": "why", "meta": meta.of(a), **facts(a, target)}
