"""Command line entry point: `tessri scan | why | graph | impact | triage | check | brief | hook | integration | mcp`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, brief, config, graphview, hook, htmlreport, integration, modules, runs, sarifview, since, sinceview
from .analyze import analyze
from .explain import TargetError, explain, why_json
from .render import markdown
from .report import build_report
from .triage import TriageError, compute as triage_compute, markdown as triage_markdown

SINCE_HELP = "compare with the point where REF and HEAD part, plus uncommitted work (default: the default branch, origin/HEAD else origin/main, origin/master, main or master; HEAD means only uncommitted work)"


def _add_root(p: argparse.ArgumentParser, positional: bool = False) -> None:
    """`--repo PATH` on every command; `scan`, `graph` and `integration` also take the root as their first argument."""
    if positional:
        p.add_argument("path", nargs="?", metavar="PATH", help="repository root, the same as --repo (default: .)")
    p.add_argument("--repo", metavar="PATH", help="repository root (default: .)")


def _root_given(args: argparse.Namespace) -> str:
    """The root the command line names, once: `--repo`, or the positional where there is one, or `.`."""
    given = [p for p in (getattr(args, "path", None), args.repo) if p is not None]
    if len(set(given)) > 1:
        raise SystemExit(f"tessri: the root was given twice ({given[0]} and {given[1]}); give it once")
    return given[0] if given else "."


def _add_analysis_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--active-days", type=int, metavar="N", help="touched within N days => ACTIVE (default 90)")
    p.add_argument("--dormant-days", type=int, metavar="N", help="untouched for N days and barely used => DORMANT (default 365)")
    p.add_argument("--owner-inactive-days", type=int, metavar="N", help="an author silent in the whole repository for N days no longer counts as an owner (default 180)")
    p.add_argument("--ignore-author", dest="ignore_authors", action="append", default=[], metavar="GLOB", help="never credit commits whose author name or email matches (repeatable; bots are ignored already)")
    p.add_argument("--review-days", type=_non_negative, metavar="N", help="review load: changes in the last N days against the N before (default 30, 0 turns it off)")
    p.add_argument("--keep", action="append", default=[], metavar="GLOB", help="never report matching files as orphans (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip matching files entirely (repeatable)")
    p.add_argument("--entry", action="append", default=[], metavar="MODULE_OR_PATH", help="extra entry point (repeatable)")
    p.add_argument("--depth", type=int, metavar="N", help="directory depth for the per-directory table (default 1)")
    p.add_argument("--top", type=int, metavar="N", help="rows in the largest-files and hotspots tables (default 15)")


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def _config_for(root: Path, args: argparse.Namespace) -> config.Config:
    cfg = config.load(root)
    for key in ("active_days", "dormant_days", "owner_inactive_days", "review_days", "depth", "top"):
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)
    for key in ("keep", "exclude", "entry", "ignore_authors"):
        current = getattr(cfg, key)
        current.extend(v for v in getattr(args, key) if v not in current)
    return cfg


def _root(path: str) -> Path:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise SystemExit(f"tessri: {path}: not a directory")
    return root.resolve()


def _emit(text: str, out_path: str | None) -> None:
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"tessri: wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _cmd_scan(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    analysis = analyze(root, _config_for(root, args))
    report = build_report(analysis, full=args.full)
    if args.format == "json":
        text = json.dumps(report, indent=2) + "\n"
    elif args.format == "html":
        text = htmlreport.build_html(analysis, report)
    else:
        text = markdown(report, args.limit)
    _emit(text, args.out)
    return 0


def _cmd_why(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    analysis = analyze(root, _config_for(root, args))
    try:
        text = json.dumps(why_json(analysis, args.target), indent=2) + "\n" if args.format == "json" else explain(analysis, args.target) + "\n"
    except TargetError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    _emit(text, args.out)
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    if args.level == "file" and args.format != "json":
        print("tessri: --level file is only available as --format json (a file-level picture is too large to read)", file=sys.stderr)
        return 2
    graph = modules.build_graph(analyze(root, _config_for(root, args)), args.module_depth, args.include_tests, args.level)
    if args.format == "json":
        text = json.dumps(graph, indent=2) + "\n"
    elif args.format == "mermaid":
        text = graphview.mermaid(graph, args.min_imports)
    elif args.format == "dot":
        text = graphview.dot(graph, args.min_imports)
    else:
        text = graphview.markdown(graph, args.limit)
    _emit(text, args.out)
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    cfg = _config_for(root, args)
    try:
        result = triage_compute(root, cfg, args.since)
    except TriageError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    _emit(json.dumps(result, indent=2) + "\n" if args.format == "json" else triage_markdown(result, args.limit, cfg.active_days), args.out)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    if args.locationless != "keep" and args.format != "sarif":
        print("tessri: --locationless applies to --format sarif only", file=sys.stderr)
        return 2
    try:
        result = since.check(root, _config_for(root, args), args.since)
    except since.CheckError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    if args.format == "sarif":
        text = json.dumps(sarifview.sarif(result, root, args.locationless), indent=2) + "\n"
    elif args.format == "json":
        text = json.dumps(result, indent=2) + "\n"
    else:
        text = sinceview.markdown(result, args.limit)
    _emit(text, args.out)
    return 1 if since.failing(result, args.fail_on) else 0


def _cmd_brief(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    cfg = _config_for(root, args)
    try:
        result = brief.compute(root, cfg, args.since, ran=args.ran, limit=args.limit, reports=args.report, coverage_reports=args.coverage)
    except brief.BriefError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    _emit(json.dumps(result, indent=2) + "\n" if args.format == "json" else brief.markdown(result), args.out)
    return 0


def _cmd_impact(args: argparse.Namespace) -> int:
    root = _root(_root_given(args))
    analysis = analyze(root, _config_for(root, args))
    try:
        report = runs.load(args.report, set(analysis.records)) if args.report else None
        found = modules.impact(analysis, args.target, args.module_depth, hops=args.hops, edges=args.edges, report=report)
    except (TargetError, runs.RunsError) as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    _emit(json.dumps(found, indent=2) + "\n" if args.format == "json" else graphview.impact_text(found), args.out)
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    return hook.run(sys.stdin.read(), args.repo)


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import Server

    return Server([_root(r) for r in (args.root or ["."])]).serve()


def _cmd_integration(args: argparse.Namespace) -> int:
    given = _root_given(args)
    root = Path(given).expanduser()
    if not root.is_dir():
        print(f"tessri: {given}: not a directory", file=sys.stderr)
        return 2
    root = root.resolve()
    try:
        doc = integration.status(root) if args.op == "status" else integration.run(root, args.op, args.agent, dry_run=args.dry_run)
    except integration.IntegrationError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    _emit(json.dumps(doc, indent=2) + "\n" if args.format == "json" else integration.text(doc), None)
    return 1 if doc.get("conflicts") else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tessri", description="Tessri: keep code understandable. How a codebase fits together, what a change can reach, who is able to review it and what nobody maintains, from code and git history, with the evidence for every claim.")
    parser.add_argument("--version", action="version", version=f"tessri {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="analyse a repository and print the report")
    _add_root(scan, positional=True)
    scan.add_argument("--format", choices=("md", "json", "html"), default="md", help="html: one self-contained page with the module graph and an impact explorer")
    scan.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    scan.add_argument("--full", action="store_true", help="json: include the per-file table")
    scan.add_argument("--limit", type=int, default=40, metavar="N", help="md: rows per candidate table (default 40)")
    _add_analysis_options(scan)
    scan.set_defaults(func=_cmd_scan)

    why = sub.add_parser("why", help="show the evidence behind one file's verdict")
    why.add_argument("target", help="file path, or dotted module name")
    _add_root(why)
    why.add_argument("--format", choices=("text", "json"), default="text", help="json: the same facts as data, with the analysis metadata")
    why.add_argument("--out", help="write to this file instead of stdout")
    _add_analysis_options(why)
    why.set_defaults(func=_cmd_why)

    graph = sub.add_parser("graph", help="module dependency graph: who imports whom, cycles, owners")
    _add_root(graph, positional=True)
    graph.add_argument("--format", choices=("md", "json", "mermaid", "dot"), default="md")
    graph.add_argument("--level", choices=("module", "file"), default="module", help="file: every import as a pair, json only (default: module)")
    graph.add_argument("--module-depth", type=_positive, metavar="N", help="a module is the first N directories of a path (default: split by size)")
    graph.add_argument("--include-tests", action="store_true", help="draw test files too (hidden by default: every module is imported by its tests)")
    graph.add_argument("--min-imports", type=_positive, metavar="N", help="mermaid, dot: leave out dependencies made of fewer than N imports (default: as many as fit about 80 arrows)")
    graph.add_argument("--out", metavar="FILE", help="write the graph to FILE instead of stdout")
    graph.add_argument("--limit", type=int, default=40, metavar="N", help="md: rows per table (default 40)")
    _add_analysis_options(graph)
    graph.set_defaults(func=_cmd_graph)

    impact = sub.add_parser("impact", help="what a change to one file or directory can reach: dependents, tests, owners")
    impact.add_argument("target", help="file path, directory, or dotted package name")
    _add_root(impact)
    impact.add_argument("--format", choices=("text", "json"), default="text")
    impact.add_argument("--hops", type=_positive, metavar="N", help="follow edges at most N steps away (default: all of them)")
    impact.add_argument("--edges", choices=("all", "imports"), default="all", help="which evidence to follow: all = recognized dependency syntax, package files and references found in strings or dynamic loading (default); imports = recognized dependency syntax and package files only")
    impact.add_argument("--module-depth", type=_positive, metavar="N", help="group dependents by the first N directories (default: split by size)")
    impact.add_argument("--report", action="append", default=[], metavar="FILE", help="a test report the host wrote (JUnit XML: pytest --junitxml, jest-junit and the like; repeatable): the candidate tests are held against what ran")
    impact.add_argument("--out", metavar="FILE", help="write the result to FILE instead of stdout")
    _add_analysis_options(impact)
    impact.set_defaults(func=_cmd_impact)

    triage = sub.add_parser("triage", help="which files of a change deserve a human first, what it can ripple into, who can look")
    triage.add_argument("--since", metavar="REF", help=SINCE_HELP)
    _add_root(triage)
    triage.add_argument("--format", choices=("md", "json"), default="md")
    triage.add_argument("--limit", type=int, default=20, metavar="N", help="md: files listed (default 20)")
    triage.add_argument("--out", metavar="FILE", help="write the result to FILE instead of stdout")
    _add_analysis_options(triage)
    triage.set_defaults(func=_cmd_triage)

    check = sub.add_parser("check", help="what a change did to the structure: new orphans and cycles, imports of deleted files, changed code nobody maintains")
    check.add_argument("--since", metavar="REF", help=SINCE_HELP)
    _add_root(check)
    check.add_argument("--format", choices=("md", "json", "sarif"), default="md", help="sarif: the same findings as a SARIF 2.1.0 log, one result per finding, file-level locations")
    check.add_argument("--limit", type=int, default=20, metavar="N", help="md: rows per table (default 20)")
    check.add_argument("--fail-on", choices=("never", "warn", "block"), default="never", help="exit 1 when a finding is at least this serious: block = deleted files still imported, warn = also new orphans, cycles and unowned code (default: never)")
    check.add_argument("--locationless", choices=sarifview.LOCATIONLESS, default="keep", help="sarif: findings with no file-level location stay in `results` without a location (keep, default), or move whole into the run's properties (omit) for consumers such as GitHub code scanning that reject a result without a location; --fail-on counts them either way")
    check.add_argument("--out", metavar="FILE", help="write the result to FILE instead of stdout")
    _add_analysis_options(check)
    check.set_defaults(func=_cmd_check)

    briefp = sub.add_parser("brief", help="one page to hand a change over: triage and check from one analysis, the commits and uncommitted files in scope, candidate tests apart from the checks the host ran, and what needs a person")
    briefp.add_argument("--since", metavar="REF", help=SINCE_HELP)
    _add_root(briefp)
    briefp.add_argument("--format", choices=("md", "json"), default="md", help="json: the brief's sections plus the whole triage and check objects")
    briefp.add_argument("--limit", type=int, default=brief.LISTED, metavar="N", help=f"files in the look-first table (default {brief.LISTED}); the JSON always carries them all")
    briefp.add_argument("--ran", action="append", default=[], metavar="TEXT", help="a check the host actually ran, with its result and exit code, recorded verbatim (repeatable); without it the brief says that none was recorded")
    briefp.add_argument("--report", action="append", default=[], metavar="FILE", help="a test report the host wrote (JUnit XML: pytest --junitxml, jest-junit and the like; repeatable): the candidate tests are held against what ran")
    briefp.add_argument("--coverage", action="append", default=[], metavar="FILE", help="a coverage report the host wrote (Cobertura or Clover XML, lcov, or coverage.py's JSON; repeatable): the lines the change adds or changes are held against the statements that ran")
    briefp.add_argument("--out", metavar="FILE", help="write the brief to FILE instead of stdout")
    _add_analysis_options(briefp)
    briefp.set_defaults(func=_cmd_brief)

    hookp = sub.add_parser("hook", help="answer a coding agent's lifecycle hook: the host's event on stdin, the host's JSON on stdout, nothing when there is nothing to add; after an edit, what the edited file can reach; when the agent stops, what the uncommitted work did to the structure (installed by `integration install --agent claude-hooks` or `codex-hooks`)")
    _add_root(hookp)
    hookp.set_defaults(func=_cmd_hook)

    mcp = sub.add_parser("mcp", help="serve the questions as Model Context Protocol tools over stdin/stdout, for an agent that starts it as a subprocess")
    mcp.add_argument("--root", action="append", metavar="PATH", help="a checkout to serve (repeatable; default: the current directory); with several, every tool names one with `root`")
    mcp.set_defaults(func=_cmd_mcp)

    integ = sub.add_parser("integration", help="install, update, inspect or remove the project integration (agent skills, AGENTS.md block, MCP configuration, lifecycle hooks, a starter configuration file, the report and review workflows) with a receipt, reversibly")
    ops = integ.add_subparsers(dest="op", required=True, metavar="{install,update,status,remove}")
    for op, text in (
        ("install", "write the skill or block for each --agent and record a receipt; an existing file is a conflict, never claimed"),
        ("update", "refresh recorded files that are still as installed; edited ones are left alone"),
        ("status", "what the receipt records against what is on disk (reads only)"),
        ("remove", "remove recorded files and blocks that are still as installed, and the receipt when nothing remains"),
    ):
        p = ops.add_parser(op, help=text)
        _add_root(p, positional=True)
        p.add_argument("--format", choices=("text", "json"), default="text")
        if op != "status":
            p.add_argument("--agent", action="append", choices=tuple(integration.PROFILES), metavar="{" + ",".join(integration.PROFILES) + "}", help="profile to act on, repeatable (an agent's instructions, a host's server entry, `claude-hooks` or `codex-hooks` for the hooks a host runs, `config` for a starter .tessri.toml, `report` for a weekly scan workflow, `review` for the brief on every pull request); install needs at least one, update and remove default to every recorded profile")
            p.add_argument("--dry-run", action="store_true", help="show the plan without writing anything")
        p.set_defaults(func=_cmd_integration)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"tessri: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
