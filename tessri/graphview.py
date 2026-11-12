"""Text views of the module graph and of an impact analysis: Markdown, Mermaid and Graphviz DOT."""

from __future__ import annotations

from .render import _STATE_TEXT, _n, _owners, _table

MAX_DRAWN = 80  # most dependencies a diagram shows unless asked for more
CUT_ROWS = 15  # cut dependencies listed per cycle in Markdown


def _many(n: int, one: str, many: str | None = None) -> str:
    return f"{_n(n)} {one if n == 1 else many or one + 's'}"


def _cycle_text(group: list[str]) -> str:
    return " ⇄ ".join(f"`{m}`" for m in group)


def markdown(graph: dict, limit: int = 40) -> str:
    s = graph["summary"]
    gone = graph["settings"]["owner_inactive_days"]
    out = [
        f"# Module graph: {graph['repo']['name']}",
        "",
        f"**{_many(s['modules'], 'module')}**, **{_many(s['dependencies'], 'dependency', 'dependencies')}** between them and **{_many(s['cycles'], 'cycle')}**, "
        f"from {_many(s['imports'], 'import')} across {_many(s['files'], 'code file')}. "
        "An arrow A → B means a file in A imports a file in B. A module is a directory"
        + (f" (the first {graph['settings']['module_depth']} levels)." if graph["settings"]["module_depth"] else ", split until none holds much more than its share of the files."),
        "",
    ]
    cycles = graph["cycles"]
    if cycles:
        out += [
            "## Cycles",
            "",
            "Modules that depend on each other, directly or through others: none of them can be understood, tested or released without the rest. "
            "For each cycle, the dependencies that point against the dominant direction are listed; removing or inverting exactly these leaves no cycle. "
            "It is a heuristic for a few, light edges, not a proof of the minimum.",
            "",
        ]
        for c in cycles:
            names = _cycle_text(c["modules"]) if len(c["modules"]) <= 6 else f"{len(c['modules'])} modules, including " + ", ".join(f"`{m}`" for m in c["modules"][:4])
            out += [f"**Cycle {c['id']}**: {names}. {_many(c['imports'], 'import')} among them; {_many(len(c['cut']), 'dependency', 'dependencies')} ({_many(c['cut_imports'], 'import')}) to cut:", ""]
            rows = [
                [f"`{e['from']}`", f"`{e['to']}`", _n(e["imports"]), f"`{e['examples'][0][0]}` imports `{e['examples'][0][1]}`"]
                for e in sorted(c["cut"], key=lambda e: (-e["imports"], e["from"], e["to"]))[:CUT_ROWS]
            ]
            out += _table(["From", "To", "Imports", "For example"], rows, {2})
            if len(c["cut"]) > CUT_ROWS:
                out += [f"{len(c['cut']) - CUT_ROWS} more in the JSON output.", ""]
    else:
        out += ["No cycles: no module depends on itself through others.", ""]

    has_owners = any("owners" in m for m in graph["modules"])
    ranked = sorted(graph["modules"], key=lambda m: (-m["used_by"], -m["code"], m["id"]))
    headers = ["Module", "Files", "Code", "Uses", "Used by", "Cycle"] + (["Owners", "State"] if has_owners else [])
    rows = []
    for m in ranked[:limit]:
        row = [f"`{m['id']}`", _n(m["files"]), _n(m["code"]), m["uses"], m["used_by"], m["cycle"] or "-"]
        if has_owners:
            row += [_owners(m["owners"], gone, m["contributors"]), _state(m)]
        rows.append(row)
    out += ["## Modules", "", "Most depended-on first. *Uses* counts the modules it imports from, *Used by* the modules that import it.", ""]
    out += _table(headers, rows, {1, 2, 3, 4})
    if len(ranked) > limit:
        out += [f"{len(ranked) - limit} more modules in the JSON output.", ""]

    edges = graph["edges"][:limit]
    if edges:
        out += ["## Heaviest dependencies", ""]
        out += _table(
            ["From", "To", "Imports", "Files", "Note"],
            [[f"`{e['from']}`", f"`{e['to']}`", _n(e["imports"]), _n(e["files"]), f"cut to break cycle {e['cycle']}" if e["cut"] else ""] for e in edges],
            {2, 3},
        )
    out += ["## Caveats", ""] + [f"- {c}" for c in graph["caveats"]]
    return "\n".join(out).rstrip() + "\n"


def _state(m: dict) -> str:
    return _STATE_TEXT[m["ownership"]] if m["code"] else "no code"


def drawn(graph: dict, min_imports: int | None) -> tuple[list[dict], list[dict], int]:
    """(modules, edges, threshold) to draw. A picture with hundreds of arrows says nothing, so unless a
    threshold is given, the lightest dependencies are left out until at most MAX_DRAWN remain."""
    edges = graph["edges"]
    floor = min_imports
    if floor is None:
        floor = 1
        while sum(e["imports"] >= floor for e in edges) > MAX_DRAWN:
            floor += 1
    kept = [e for e in edges if e["imports"] >= floor]
    touched = {e["from"] for e in kept} | {e["to"] for e in kept}
    modules = [m for m in graph["modules"] if m["id"] in touched] if kept else graph["modules"]
    return modules, kept, floor


def _label(m: dict) -> str:
    return f"{m['id']}\n{_many(m['files'], 'file')}, {_many(m['code'], 'line')}"


def mermaid(graph: dict, min_imports: int | None = None) -> str:
    modules, edges, floor = drawn(graph, min_imports)
    ids = {m["id"]: f"n{i}" for i, m in enumerate(modules)}
    out = ["flowchart LR", f"  %% {len(edges)} of {len(graph['edges'])} dependencies drawn (at least {_many(floor, 'import')}); red ones are the cuts that break a cycle"]
    for m in modules:
        text = _label(m).replace('"', "#quot;").replace("\n", "<br/>")
        out.append(f'  {ids[m["id"]]}["{text}"]')
    for e in edges:
        out.append(f"  {ids[e['from']]} -->|{e['imports']}| {ids[e['to']]}")
    cut = [i for i, e in enumerate(edges) if e["cut"]]
    if cut:
        out.append("  linkStyle " + ",".join(map(str, cut)) + " stroke:#d33,stroke-width:2px")
    unowned = [ids[m["id"]] for m in modules if m.get("ownership") == "no-active-owner"]
    if unowned:
        out.append("  classDef noowner stroke-dasharray:4 3")
        out.append("  class " + ",".join(unowned) + " noowner")
    return "\n".join(out) + "\n"


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def dot(graph: dict, min_imports: int | None = None) -> str:
    modules, edges, floor = drawn(graph, min_imports)
    out = [
        "digraph tessri {",
        f"  // {len(edges)} of {len(graph['edges'])} dependencies drawn (at least {_many(floor, 'import')}); red ones are the cuts that break a cycle",
        "  rankdir=LR;",
        '  node [shape=box, fontname="Helvetica"];',
    ]
    for m in modules:
        attrs = [f"label={_q(_label(m))}"]
        if m.get("ownership") == "no-active-owner":
            attrs.append("style=dashed")
        out.append(f"  {_q(m['id'])} [{', '.join(attrs)}];")
    for e in edges:
        attrs = [f"label={e['imports']}"]
        if e["cut"]:
            attrs.append("color=red")
        out.append(f"  {_q(e['from'])} -> {_q(e['to'])} [{', '.join(attrs)}];")
    out.append("}")
    return "\n".join(out) + "\n"


def _report(held: dict) -> str:
    """The candidate tests against the report the host wrote: how many ran and how they fared, how many did not."""
    ran = len(held["ran"])
    parts = [f"{_n(held['passed'])} passed", f"{_n(len(held['failed']))} failed"] + ([f"{_n(held['skipped'])} skipped"] if held["skipped"] else [])
    sources = ", ".join(f"`{s}`" for s in held["sources"])
    text = f"in the report ({sources}): {_n(ran)} of them ran, {', '.join(parts)}; {_n(len(held['not_run']))} did not run"
    if held["unmatched"]["cases"]:
        text += f" (the report also has {_n(held['unmatched']['cases'])} cases of no file in this repository)"
    return text


def impact_text(imp: dict) -> str:
    d, t = imp["dependents"], imp["tests"]
    what = f"{imp['target']}  ({imp['files']} file{'s' if imp['files'] != 1 else ''}, {_n(imp['code'])} code lines)"
    out = [f"Changing {what} can affect:", ""]
    if not d["files"] and not t["files"]:
        out.append("- no file in the analysed set depends on it through the followed edges")
    else:
        out.append(
            f"- **{_many(d['files'], 'code file')}** in **{_many(len(d['modules']), 'module')}** ({d['share']}% of the code), "
            f"{_n(d['direct'])} of them directly (one followed edge away)"
        )
        out.append(f"- **{_many(t['files'], 'test file')}** reaching it (candidates to run, not runs), {_n(t['direct'])} directly")
        if t.get("report"):
            out.append("- " + _report(t["report"]))
        if len(d['by_distance']) > 1:
            out.append("- code files by number of followed edges away: " + ", ".join(f"{n}: {_n(c)}" for n, c in enumerate(d['by_distance'], 1)))
    if imp.get("edges"):
        out.append("- " + _policy(imp["edges"]))
    out.append("")
    if d["modules"]:
        gone = imp.get("inactive_days", 0)
        has_owners = "owners" in d["modules"][0]
        rows = []
        for m in d["modules"][:15]:
            row = [f"`{m['module']}`", _n(m["files"]), _n(m["direct"])]
            if has_owners:
                row += [_owners(m["owners"], gone, m["contributors"]), _state(m)]
            rows.append(row)
        out += _table(["Affected module", "Files", "Direct"] + (["Owners", "State"] if has_owners else []), rows, {1, 2})
        if len(d["modules"]) > 15:
            out += [f"{len(d['modules']) - 15} more modules in the JSON output.", ""]
    if imp.get("owners"):
        out += ["People who maintain the affected code (tell them, or ask them to review): " + _owners(imp["owners"], imp["inactive_days"], imp["contributors"]), ""]
    if t["paths"]:
        held = t.get("report")
        shown = ", ".join(f"`{p}`" + (f" ({held['ran'].get(p, 'not run')})" if held else "") for p in t["paths"][:10])
        out += [f"Tests that reach it, nearest first: {shown}" + (f" and {t['files'] - 10} more" if t["files"] > 10 else ""), ""]
    if imp["depends_on"]:
        out += ["It depends on: " + ", ".join(f"`{r['module']}` ({r['files']})" for r in imp["depends_on"][:10]), ""]
    out.append(
        "Static analysis of this repository under the selected edge policy and hop limit: registries, dependency injection and "
        "consumers outside the repository are not counted, and a file outside this set is not shown to be unaffected."
    )
    return "\n".join(out) + "\n"


def _policy(e: dict) -> str:
    """One line saying which evidence the walk followed, what it met and did not follow, and what imports alone reach."""
    refs = e["references"]
    example = ""
    if refs["listed"]:
        first = refs["listed"][0]
        example = f" (for example `{first['from']}` → `{first['to']}`, {first['kind']})"
    unknown = e["unclassified"]
    tail = f"; {_many(unknown['edges'], 'edge')} from {', '.join(unknown['analyzers']) or 'an analyzer'} without provenance" if unknown["edges"] else ""
    steps = f"at most {_many(e['hops'], 'step')}" if e["hops"] is not None else "any number of steps"
    if e["policy"] == "imports":
        skipped = sum(e["excluded"].values())
        return (
            f"edges followed, {steps}: recognized dependency syntax and the package files Python runs for it; "
            f"{_many(skipped, 'string, dynamic or unclassified edge')} met at the frontier not followed{example}{tail}"
        )
    narrow = e["imports_only"]
    return (
        f"edges followed, {steps}: recognized dependency syntax, package files, and {_many(refs['count'], 'reference')} found in strings, "
        f"dynamic loading or unclassified evidence{example}; syntax and package files alone reach {_many(narrow['files'], 'code file')} and "
        f"{_many(narrow['tests'], 'test file')}{tail}"
    )
