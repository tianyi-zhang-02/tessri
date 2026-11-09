"""`tessri hook`: what a coding agent's lifecycle hook runs. The host's event arrives as JSON on stdin, the answer
leaves as the host's JSON on stdout, and when there is nothing to add the command prints nothing.

Claude Code and Codex read the same hook shape (`templates.HOOKS`, installed by `integration` as the profiles
`claude-hooks` and `codex-hooks`), send the same fields (`hook_event_name`, `session_id`, `cwd`, `tool_input`,
`stop_hook_active`) and accept the same answers, so one command serves both. It speaks at two moments:

- after an edit (`PostToolUse` of `Edit` and `Write`, names Codex's `apply_patch` answers to as well): what each
  edited code file can reach, for the agent, as `hookSpecificOutput.additionalContext`: the files that depend on
  it, the tests that reach it and who maintains the code it reaches. Once per file and session, and only when
  something depends on the file.
- when the agent stops (`Stop`): what the uncommitted work did to the structure, the warn and block findings of
  `check --since HEAD`, each once per session. By default they go to the person as a `systemMessage`. With
  `stop_hook = "block"` in the configuration the agent gets them first, as `decision: block` with the findings as
  the reason; the host marks its next stop `stop_hook_active`, and what is still open then goes to the person.

The hook changes nothing and never stands in the host's way: an error is one line on stderr and exit 1, which both
hosts show and move past.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, modules, since
from .analyze import analyze
from .explain import TargetError

STATE_DIR = Path(tempfile.gettempdir()) / "tessri-hooks"  # what each session was already told; one small file per session
STATE_DAYS = 7  # a session file older than this is dropped
EDITS_SPOKEN = 5  # files spoken about after one edit (a patch can touch many)
FILES_LISTED = 6
TESTS_LISTED = 5
PATH_KEYS = ("file_path", "notebook_path", "path")  # where Claude Code's edit tools put the path
PATCH_HEADER = re.compile(r"^\*\*\* (?:Update File|Add File|Move to): (.+?)\s*$", re.MULTILINE)  # Codex's patches
AUDIENCES = ("inform", "block")  # `stop_hook`: the findings go to the person, or to the agent first


class HookError(Exception):
    """Input the hook cannot work with; one line for the host to show."""


def run(stdin: str, repo: str | None = None) -> int:
    """Read one event, print one answer or nothing, exit 0; any failure is one stderr line and exit 1."""
    try:
        try:
            event = json.loads(stdin) if stdin.strip() else None
        except ValueError:
            event = None
        if not isinstance(event, dict):
            raise HookError("stdin is not a JSON object (the host's event)")
        answer = respond(event, repo)
    except Exception as exc:  # noqa: BLE001 - a hook must never stand in the host's way, whatever went wrong
        print(f"tessri hook: {exc}", file=sys.stderr)
        return 1
    if answer is not None:
        sys.stdout.write(json.dumps(answer) + "\n")
    return 0


def respond(event: dict, repo: str | None = None, now: float | None = None) -> dict | None:
    """The answer to one host event, or None when there is nothing to add."""
    now = time.time() if now is None else now
    name = event.get("hook_event_name")
    if name == "PostToolUse":
        return after_edit(event, repo, now)
    if name == "Stop":
        return at_stop(event, repo, now)
    return None


# --- the repository and the session ---------------------------------------------------------------------------------


def project_root(event: dict, repo: str | None) -> Path | None:
    """`--repo` when given; else the git top level above the host's `cwd`, else that directory itself."""
    if repo:
        root = Path(repo).expanduser()
        if not root.is_dir():
            raise HookError(f"{repo}: not a directory")
        return root.resolve()
    cwd = event.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    if not start.is_dir():
        return None
    try:
        res = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        res = None
    top = res.stdout.strip() if res is not None and res.returncode == 0 else ""
    return (Path(top) if top else start).resolve()


class Memory:
    """What this session has been told already, so that nothing is said twice. One JSON file per host session in
    STATE_DIR, named by a hash of the session id; without a session id nothing is remembered."""

    def __init__(self, session: object, now: float):
        self.now = now
        self.path = STATE_DIR / (hashlib.sha256(session.encode("utf-8")).hexdigest()[:16] + ".json") if isinstance(session, str) and session else None
        self.told: dict[str, list[str]] = {}
        if self.path is not None:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                self.told = {k: [x for x in v if isinstance(x, str)] for k, v in loaded.items() if isinstance(k, str) and isinstance(v, list)}

    def seen(self, audience: str, key: str) -> bool:
        return key in self.told.get(audience, [])

    def note(self, audience: str, key: str) -> None:
        self.told.setdefault(audience, []).append(key)

    def save(self) -> None:
        if self.path is None:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.told, sort_keys=True), encoding="utf-8")
        for stale in STATE_DIR.glob("*.json"):
            try:
                if stale != self.path and self.now - stale.stat().st_mtime > STATE_DAYS * 86400:
                    stale.unlink()
            except OSError:
                pass


# --- after an edit ----------------------------------------------------------------------------------------------------


def edited_files(event: dict, root: Path) -> list[str]:
    """Project-relative paths of the files the tool touched and that are still there: the path fields of Claude
    Code's edit tools, and the `*** Update File:` headers of a Codex patch wherever they sit in `tool_input`."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    cwd = event.get("cwd")
    base = Path(cwd) if isinstance(cwd, str) and cwd else root
    found: list[str] = []
    for key, value in tool_input.items():
        if not isinstance(value, str):
            continue
        for raw in [value] if key in PATH_KEYS else PATCH_HEADER.findall(value):
            path = Path(raw)
            if not path.is_absolute():
                path = base / path
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:  # outside the project
                continue
            if rel not in found and (root / rel).is_file():
                found.append(rel)
    return found


def after_edit(event: dict, repo: str | None, now: float) -> dict | None:
    root = project_root(event, repo)
    if root is None:
        return None
    paths = edited_files(event, root)
    if not paths:
        return None
    memory = Memory(event.get("session_id"), now)
    fresh = [p for p in paths if not memory.seen("edits", p)]
    if not fresh:
        return None
    analysis = analyze(root, config.load(root), now=now)
    said = []
    for rel in fresh[:EDITS_SPOKEN]:
        memory.note("edits", rel)
        if rel not in analysis.records:
            continue
        try:
            found = modules.impact(analysis, rel)
        except TargetError:
            continue
        direct = sorted(p for p in analysis.graph.inbound.get(rel, ()) if p in analysis.records and not analysis.records[p].is_test)
        text = impact_text(rel, found, direct)
        if text:
            said.append(text)
    memory.save()
    if not said:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n\n".join(said)}}


def _listed(paths: list[str], limit: int) -> str:
    shown = ", ".join(f"`{p}`" for p in paths[:limit])
    return shown + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def _count(n: int, one: str) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {one}s"


def impact_text(rel: str, found: dict, direct: list[str]) -> str | None:
    """A few factual sentences for the agent, or None when nothing in the repository depends on the file."""
    d, t = found["dependents"], found["tests"]
    if not d["files"] and not t["files"]:
        return None
    if d["files"]:
        where = f" in {_count(len(d['modules']), 'module')}" if len(d["modules"]) > 1 else ""
        depend = f"{_count(d['files'], 'code file')}{where} depend{'s' if d['files'] == 1 else ''} on it, {d['direct']} directly" + (f" ({_listed(direct, FILES_LISTED)})" if direct else "")
    else:
        depend = "no code file depends on it"
    if t["files"]:
        tests = f"{_count(t['files'], 'test file')} reach{'es' if t['files'] == 1 else ''} it ({_listed(t['paths'], TESTS_LISTED)}), candidates to run, not runs"
    else:
        tests = "no test file reaches it"
    sentences = [f"Tessri, on `{rel}`: {depend}; {tests}."]
    owners = found.get("owners") or []
    if owners:
        people = ", ".join(f"{o['name']} {o['share']}%" for o in owners)
        others = found.get("contributors", 0) - len(owners)
        if sum(o["share"] for o in owners) < 50 and others > 0:
            people += f" and {_count(others, 'other')}"
        sentences.append(f"The code it reaches is maintained by {people}.")
    sentences.append(f"The evidence and the full lists: `tessri impact {rel}`.")
    return " ".join(sentences)


# --- when the agent stops --------------------------------------------------------------------------------------------


def at_stop(event: dict, repo: str | None, now: float) -> dict | None:
    root = project_root(event, repo)
    if root is None:
        return None
    cfg = config.load(root)
    try:
        result = since.check(root, cfg, since="HEAD", now=now)
    except since.CheckError:  # not a git repository, or no commit yet: nothing to compare the work with
        return None
    findings = [f for f in result["findings"] if f["severity"] != "info"]
    if not findings:
        return None
    audience = "agent" if cfg.stop_hook == "block" and not event.get("stop_hook_active") else "person"
    memory = Memory(event.get("session_id"), now)
    fresh = [f for f in findings if not memory.seen(audience, f["id"])]
    if not fresh:
        return None
    for f in fresh:
        memory.note(audience, f["id"])
    memory.save()
    text = stop_text(fresh)
    if audience == "agent":
        return {"decision": "block", "reason": text}
    return {"systemMessage": text}


def stop_text(findings: list[dict]) -> str:
    """One paragraph: each finding's own title, the files it names, and where the evidence is."""
    bits = []
    for f in findings[:4]:
        files = _listed(f["files"], 3)
        bits.append(f["title"] + (f" ({files})" if files else ""))
    more = f"; and {_count(len(findings) - 4, 'more finding')}" if len(findings) > 4 else ""
    return "Tessri, on the uncommitted work: " + "; ".join(bits) + more + ". The evidence: `tessri check --since HEAD`; the page to hand over: `tessri brief --since HEAD`."
