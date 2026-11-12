"""`tessri mcp`: the questions as Model Context Protocol tools, over standard input and output.

An agent that speaks MCP starts this as a subprocess and asks Tessri's questions as tool calls. Each tool is one
command: its result carries the command's `--format json` object as `structuredContent` and the command's text or
Markdown as `content`, both from one analysis, so the agent sees what the terminal shows. Nothing is written and no
network is touched. Every call sees the checkout as it is: an analysis is reused for a later call only while the
checkout's fingerprint (HEAD, the paths git reports as changed or untracked with their sizes and modification
times, the configuration files) is unchanged, and for at most an hour; a change query (`triage`, `check`, `brief`)
always reads afresh.

Two revisions of the protocol are spoken, because clients are on both: the 2026-07-28 revision has no handshake
(every request carries its version in `_meta`, and `server/discover` says what the server is), the earlier ones
open with `initialize`. Standard output carries protocol messages only; notices go to standard error. A mistake in
a call's arguments is a tool result with `isError`, in the sentence the command line prints; a malformed request,
an unknown method or an unknown tool is a JSON-RPC error."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

from . import __version__, brief, config, gitlog, graphview, modules, runs, since, sinceview
from .analyze import Analysis, analyze
from .explain import TargetError, explain, why_json
from .gitlog import _git_line as git_line  # one-line probes, as the history reader runs them
from .model import SCHEMA_VERSION
from .render import markdown as scan_markdown
from .report import build_report
from .triage import TriageError, compute as triage_compute, markdown as triage_markdown

CURRENT = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # the revisions that open with `initialize`
SUPPORTED = (CURRENT, *LEGACY)
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
SERVER_KEY = "io.modelcontextprotocol/serverInfo"
TTL_MS = 3_600_000  # how long a client may cache `server/discover`; the tool list never changes while running
REUSE_SECONDS = 3600  # how long an analysis of an unchanged checkout is reused: ages are day-granular, so an hour costs nothing
CONFIG_FILES = (".tessri.toml", "pyproject.toml")  # what `config.load` reads; usually tracked, but stat'd regardless

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_VERSION = -32022

INSTRUCTIONS = (
    "Tessri reads a repository and its git history and answers a maintainer's questions with the evidence for every "
    "claim; it never edits code. Pick the tool by the question: tessri_impact before changing a file or directory "
    "(dependents, candidate tests, maintainers); tessri_triage to review a change (which files deserve a person "
    "first, who can look); tessri_check when a change is done (what it did to the structure); tessri_brief to hand a "
    "change over for review (triage and check in one page, with the checks the host ran passed in `ran`); tessri_why to verify "
    "a claim about one file before acting on it; tessri_scan and tessri_graph to get to know a repository or plan a "
    "cleanup. Paths are repository-relative with `/`; `root` names the checkout (tessri_repos lists them) and is "
    "optional when the server serves one. Each result holds the command's JSON as structuredContent and its text as "
    "content. Reachability is static: a file nothing reaches is a candidate, not a verdict; read tessri_why first."
)

ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
ROOT = {"type": "string", "description": "the checkout: an absolute path the server was started with, or the name tessri_repos lists for it; optional when the server serves one checkout"}


class Mistake(Exception):
    """A call that cannot be answered as asked: the sentence the command line prints, returned as a tool result."""


class _Invalid(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.data = code, data


@dataclass(frozen=True)
class Checkout:
    name: str
    root: Path


@dataclass
class Kept:
    """One analysis held for reuse, with the fingerprint of the checkout it was made from."""

    fingerprint: tuple
    analysis: Analysis


def fingerprint(root: Path) -> tuple | None:
    """What the analysis depends on, read cheaply: HEAD, every path git reports as changed or untracked (ignored
    files are never analysed) with its size and modification time, and the configuration files' stats. None without
    a repository or when git cannot answer, so that nothing is reused there."""
    head = gitlog.commit_id(root, "HEAD")
    if head is None:
        return None
    try:
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"], capture_output=True, check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    def stat(rel: str) -> tuple:
        try:
            st = os.stat(root / rel)
        except OSError:
            return (rel, None, None)
        return (rel, st.st_mtime_ns, st.st_size)

    changed = tuple(stat(entry[3:].decode("utf-8", "surrogateescape")) for entry in status.split(b"\0") if len(entry) > 3)
    return (head, hashlib.sha256(status).hexdigest(), changed, tuple(stat(name) for name in CONFIG_FILES))


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, dict]
    required: tuple[str, ...]
    run: Callable[["Server", dict], tuple[str, dict]]  # (text as the command prints it, the command's JSON object)

    def schema(self) -> dict:
        return {"type": "object", "properties": self.properties, "required": list(self.required), "additionalProperties": False}

    def listing(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description, "inputSchema": self.schema(), "annotations": dict(ANNOTATIONS)}


def _git_block(root: Path) -> dict:
    """What `meta.git` says, from probes alone: no history is read for a listing."""
    head = gitlog.commit_id(root, "HEAD")
    if head is None:
        return {"available": False, "reason": gitlog.unavailable_reason(root), "head": None, "shallow": None, "commits": None}
    count = git_line(root, "rev-list", "--count", "HEAD")
    return {"available": True, "reason": None, "head": head, "shallow": git_line(root, "rev-parse", "--is-shallow-repository") == "true", "commits": int(count) if count and count.isdigit() else None}


def _repos(server: Server, args: dict) -> tuple[str, dict]:
    rows = [{"name": c.name, "root": str(c.root), "git": _git_block(c.root)} for c in server.checkouts]
    lines = []
    for r in rows:
        git = r["git"]
        state = f"{git['commits']} commits, head {git['head'][:7]}" + (", shallow" if git["shallow"] else "") if git["available"] else f"no git history ({git['reason']})"
        lines.append(f"- {r['name']}: {r['root']} ({state})")
    return "\n".join(lines) + "\n", {"schema_version": SCHEMA_VERSION, "kind": "repos", "repos": rows}


def _scan(server: Server, args: dict) -> tuple[str, dict]:
    _, a = server.analysis(args)
    report = build_report(a, full=bool(args.get("full", False)))
    return scan_markdown(report, 40), report


def _why(server: Server, args: dict) -> tuple[str, dict]:
    _, a = server.analysis(args)
    try:
        return explain(a, args["path"]) + "\n", why_json(a, args["path"])
    except TargetError as exc:
        raise Mistake(str(exc)) from exc


def _impact(server: Server, args: dict) -> tuple[str, dict]:
    root, a = server.analysis(args)
    try:
        report = runs.load(args["report"], set(a.records), root) if args.get("report") else None
        found = modules.impact(a, args["target"], None, hops=args.get("hops"), edges=args.get("edges", "all"), report=report)
    except (TargetError, runs.RunsError) as exc:
        raise Mistake(str(exc)) from exc
    return graphview.impact_text(found), found


def _graph(server: Server, args: dict) -> tuple[str, dict]:
    _, a = server.analysis(args)
    level = args.get("level", "module")
    graph = modules.build_graph(a, args.get("module_depth"), bool(args.get("include_tests", False)), level)
    text = graphview.markdown(graph, 40) if level == "module" else json.dumps(graph, indent=2) + "\n"  # a file-level picture has no Markdown form
    return text, graph


def _triage(server: Server, args: dict) -> tuple[str, dict]:
    root, cfg = server.configured(args)
    try:
        result = triage_compute(root, cfg, args.get("since"))
    except TriageError as exc:
        raise Mistake(str(exc)) from exc
    return triage_markdown(result, 20, cfg.active_days), result


def _check(server: Server, args: dict) -> tuple[str, dict]:
    root, cfg = server.configured(args)
    try:
        result = since.check(root, cfg, args.get("since"))
    except since.CheckError as exc:
        raise Mistake(str(exc)) from exc
    return sinceview.markdown(result, 20), result


def _brief(server: Server, args: dict) -> tuple[str, dict]:
    root, cfg = server.configured(args)
    try:
        result = brief.compute(root, cfg, args.get("since"), ran=args.get("ran") or [], reports=args.get("report") or [], report_base=root)
    except brief.BriefError as exc:
        raise Mistake(str(exc)) from exc
    return brief.markdown(result), result


_REPORT = {"type": "array", "items": {"type": "string"}, "default": [], "description": "test reports the host wrote, as JUnit XML (pytest --junitxml, jest-junit and the like), paths relative to the root: the candidate tests are held against what ran"}
_SINCE = {"type": "string", "description": "a commit, branch or tag; the change is where it and HEAD part, plus uncommitted work. Absent: the default branch (origin/HEAD, else origin/main, origin/master, main or master; HEAD when none exists). HEAD: only uncommitted work"}

TOOLS: tuple[Tool, ...] = (
    Tool("tessri_repos", "Repositories", "Which checkouts this server reads: each one's name, root and git state.", {}, (), _repos),
    Tool(
        "tessri_scan",
        "Scan",
        "How the codebase fits together and what nobody maintains: every file's status, volume, hotspots, ownership, review load, cleanup candidates and the caveats of the analysis.",
        {"root": ROOT, "full": {"type": "boolean", "default": False, "description": "include the per-file table (large on a big repository)"}},
        (),
        _scan,
    ),
    Tool(
        "tessri_why",
        "Why",
        "The evidence behind one file's verdict: reachability and entry points, history, owners, dependents and dependencies with the kind of evidence behind each edge.",
        {"root": ROOT, "path": {"type": "string", "description": "the file: a repository-relative path, a unique path suffix, or a module name"}},
        ("path",),
        _why,
    ),
    Tool(
        "tessri_impact",
        "Impact",
        "What a change to one file or directory can reach: dependents by distance, the tests that reach it, the owners of the affected code, and the kinds of evidence followed.",
        {
            "root": ROOT,
            "target": {"type": "string", "description": "a file or directory, repository-relative, or a dotted package name"},
            "edges": {"type": "string", "enum": ["all", "imports"], "default": "all", "description": "all: recognized dependency syntax, package files and references found in strings or dynamic loading; imports: syntax and package files only"},
            "hops": {"type": ["integer", "null"], "minimum": 1, "default": None, "description": "follow edges at most this many steps away (null: any number)"},
            "report": _REPORT,
        },
        ("target",),
        _impact,
    ),
    Tool(
        "tessri_graph",
        "Graph",
        "Who imports whom: the modules, the dependencies between them, the cycles and the few dependencies to cut, with owners; or every import as a pair at the file level.",
        {
            "root": ROOT,
            "level": {"type": "string", "enum": ["module", "file"], "default": "module", "description": "file: every import as a pair (large on a big repository)"},
            "module_depth": {"type": ["integer", "null"], "minimum": 1, "default": None, "description": "a module is the first N directories of a path (null: split by size)"},
            "include_tests": {"type": "boolean", "default": False, "description": "draw test files too"},
        },
        (),
        _graph,
    ),
    Tool("tessri_triage", "Triage", "Which files of a change deserve a person first, what the change can ripple into, and who can look.", {"root": ROOT, "since": _SINCE}, (), _triage),
    Tool(
        "tessri_check",
        "Check",
        "What a change did to the structure: new orphans and cycles, imports of deleted files, changed code nobody maintains, with a finding for each.",
        {"root": ROOT, "since": _SINCE},
        (),
        _check,
    ),
    Tool(
        "tessri_brief",
        "Brief",
        "One page to hand a change over for review: triage and check from one analysis, the commits and uncommitted files the evidence covers, the files to look at first, the findings, candidate tests apart from the checks the host ran, who can look and what needs a person.",
        {
            "root": ROOT,
            "since": _SINCE,
            "ran": {"type": "array", "items": {"type": "string"}, "default": [], "description": "the checks the host actually ran, one string each with the command, its result and exit code, recorded verbatim; without it the brief says that none was recorded"},
            "report": _REPORT,
        },
        (),
        _brief,
    ),
)
BY_NAME = {t.name: t for t in TOOLS}


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "null":
        return value is None
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list)
    return True


def validate(tool: Tool, args: Any) -> str | None:
    """Why `args` does not fit the tool's schema, or None when it does."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    for name in tool.required:
        if name not in args:
            return f"`{name}` is required"
    for name, value in args.items():
        spec = tool.properties.get(name)
        if spec is None:
            return f"unknown argument `{name}`; the tool takes {', '.join(tool.properties) or 'none'}"
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not any(_type_ok(value, k) for k in kinds):
            return f"`{name}` must be {' or '.join(kinds)}"
        if "items" in spec and isinstance(value, list) and not all(_type_ok(item, spec["items"]["type"]) for item in value):
            return f"`{name}` must be an array of {spec['items']['type']}s"
        if "enum" in spec and value not in spec["enum"]:
            return f"`{name}` must be one of {', '.join(spec['enum'])}"
        if "minimum" in spec and value is not None and value < spec["minimum"]:
            return f"`{name}` must be at least {spec['minimum']}"
    return None


def _error(rid: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def name_checkouts(roots: Sequence[Path]) -> list[Checkout]:
    """Each root by its directory's name; a second root with the same name gets `-2`, a third `-3`."""
    out: list[Checkout] = []
    seen: dict[str, int] = {}
    for root in roots:
        base = root.name or str(root)
        seen[base] = seen.get(base, 0) + 1
        out.append(Checkout(base if seen[base] == 1 else f"{base}-{seen[base]}", root))
    return out


class Server:
    def __init__(self, roots: Sequence[Path]):
        self.checkouts = name_checkouts([Path(r) for r in roots])
        self.version: str | None = None  # the revision an `initialize` settled on; None until then or under 2026-07-28
        self.kept: dict[Path, Kept] = {}  # the last analysis per root, reused while the checkout's fingerprint holds
        self.clock: Callable[[], float] = time.time

    # --- the checkout a call is about ---------------------------------------------------------------------------

    def checkout(self, args: dict) -> Path:
        given = args.get("root")
        if given is None:
            if len(self.checkouts) == 1:
                root = self.checkouts[0].root
            else:
                raise Mistake(f"`root` is required: this server serves {len(self.checkouts)} checkouts; `tessri_repos` lists them")
        else:
            try:
                resolved = Path(given).expanduser().resolve()
            except OSError:
                resolved = None
            match = next((c for c in self.checkouts if c.name == given or c.root == resolved), None)
            if match is None:
                raise Mistake(f"`{given}` is not a root this server was started with; `tessri_repos` lists them")
            root = match.root
        if not root.is_dir():
            raise Mistake(f"{root}: not a directory")
        return root

    def configured(self, args: dict) -> tuple[Path, config.Config]:
        root = self.checkout(args)
        try:
            cfg = config.load(root)
        except config.ConfigError as exc:
            raise Mistake(str(exc)) from exc
        return root, cfg

    def analysis(self, args: dict) -> tuple[Path, Analysis]:
        """The analysis of the checkout as it is now: the one kept from an earlier call when the fingerprint still
        matches and it is less than REUSE_SECONDS old, otherwise a fresh one, kept for the next call."""
        root, cfg = self.configured(args)
        key = fingerprint(root)
        kept = self.kept.get(root)
        if key is not None and kept is not None and kept.fingerprint == key and self.clock() - kept.analysis.now < REUSE_SECONDS:
            return root, kept.analysis
        found = analyze(root, cfg, now=self.clock())
        if key is not None:
            self.kept[root] = Kept(key, found)
        else:
            self.kept.pop(root, None)
        return root, found

    # --- the protocol --------------------------------------------------------------------------------------------

    def handle(self, message: Any) -> dict | None:
        """The response to one message, or None when none is due (a notification, or a response to nothing)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            rid = message.get("id") if isinstance(message, dict) else None
            return _error(rid, INVALID_REQUEST, "not a JSON-RPC 2.0 request") if rid is not None else None
        rid, method, params = message.get("id"), message.get("method"), message.get("params")
        if not isinstance(method, str):
            return None  # a response to a request this server never makes
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(rid, INVALID_PARAMS, "params must be an object") if rid is not None else None
        meta = params.get("_meta")
        requested = meta.get(VERSION_KEY) if isinstance(meta, dict) else None
        modern = requested is not None
        if rid is None:
            return None  # notifications/initialized, cancelled, progress: nothing to answer
        if modern and requested not in SUPPORTED:
            return _error(rid, UNSUPPORTED_VERSION, "Unsupported protocol version", {"supported": list(SUPPORTED), "requested": requested})
        try:
            result = self._dispatch(method, params)
        except _Invalid as exc:
            return _error(rid, exc.code, str(exc), exc.data)
        except Exception as exc:  # a bug, not the client's mistake: the server stays up and says so
            return _error(rid, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if modern:
            result = {"resultType": "complete", **result}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            asked = params.get("protocolVersion")
            self.version = asked if asked in LEGACY else LEGACY[0]
            return {"protocolVersion": self.version, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "tessri", "version": __version__}, "instructions": INSTRUCTIONS}
        if method == "server/discover":
            return {"supportedVersions": list(SUPPORTED), "capabilities": {"tools": {}}, "_meta": {SERVER_KEY: {"name": "tessri", "version": __version__}}, "instructions": INSTRUCTIONS, "ttlMs": TTL_MS, "cacheScope": "public"}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.listing() for t in TOOLS]}
        if method == "tools/call":
            return self.call(params.get("name"), params.get("arguments"))
        raise _Invalid(METHOD_NOT_FOUND, f"unknown method {method!r}")

    def call(self, name: Any, args: Any) -> dict:
        """One tool call as a result object: the text and the JSON, or `isError` with the sentence."""
        tool = BY_NAME.get(name) if isinstance(name, str) else None
        if tool is None:
            raise _Invalid(INVALID_PARAMS, f"unknown tool {name!r}; the tools are {', '.join(BY_NAME)}")
        args = {} if args is None else args
        problem = validate(tool, args)
        if problem:
            raise _Invalid(INVALID_PARAMS, f"{tool.name}: {problem}")
        try:
            text, data = tool.run(self, args)
        except Mistake as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False}

    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
        """Read newline-delimited messages until the input closes; write each response as one line."""
        stdin = sys.stdin if stdin is None else stdin
        out = sys.stdout if stdout is None else stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                response: dict | None = _error(None, PARSE_ERROR, "not JSON")
            else:
                saved = sys.stdout
                sys.stdout = sys.stderr  # nothing a command prints may reach the protocol stream
                try:
                    response = self.handle(message)
                finally:
                    sys.stdout = saved
            if response is not None:
                out.write(json.dumps(response) + "\n")
                out.flush()
        return 0
