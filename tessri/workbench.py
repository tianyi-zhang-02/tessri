"""A local, read-only review session over the existing brief. No tests or agent commands run here."""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

from . import brief, briefhtml, config, gitlog, mcp, reviewview, since as since_mod

MAX_SOURCE_BYTES = 200_000
MAX_SOURCE_FILES = 200


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--literal-pathspecs", "-C", str(root), *args], check=True, capture_output=True, timeout=60).stdout


def source(root: Path, path: str, base: str | None = None) -> dict:
    """Capture only regular repository-relative text files; never follow a repository symlink."""
    root = root.resolve()
    parts = PurePosixPath(path).parts
    if not parts or PurePosixPath(path).is_absolute() or any(p in ("..", ".git") for p in parts) or "\\" in path:
        return {"text": None, "reason": "Unsafe or unsupported repository path"}
    try:
        if base:
            entry = _git(root, "ls-tree", "-z", base, "--", path)
            if not entry or entry.split(b" ", 1)[0] not in (b"100644", b"100755"):
                return {"text": None, "reason": "No regular file at the base"}
            obj = entry.split(b"\t", 1)[0].split()[-1].decode("ascii")
            if int(_git(root, "cat-file", "-s", obj)) > MAX_SOURCE_BYTES:
                return {"text": None, "reason": f"Source exceeds {MAX_SOURCE_BYTES:,} bytes"}
            raw = _git(root, "cat-file", "blob", obj)
        else:
            target = root.joinpath(*parts)
            if not target.resolve().is_relative_to(root) or any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
                return {"text": None, "reason": "Symlink source is not captured"}
            if not target.is_file():
                return {"text": None, "reason": "No regular file in the working tree"}
            with target.open("rb") as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            return {"text": None, "reason": f"Source exceeds {MAX_SOURCE_BYTES:,} bytes"}
        if b"\0" in raw:
            return {"text": None, "reason": "Binary source is not displayed"}
        return {"text": raw.decode("utf-8"), "reason": None}
    except UnicodeDecodeError:
        return {"text": None, "reason": "Source is not UTF-8 text"}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"text": None, "reason": "Source could not be read"}


def fingerprint(root: Path, ref: str | None, reports: tuple[Path, ...] = ()) -> str:
    """Cheap checkout metadata plus dirty contents, base ref and supplied report contents. Not validation provenance."""
    key = mcp.fingerprint(root)
    digest = hashlib.sha256(repr(key).encode("utf-8", "replace"))
    digest.update(str(gitlog.commit_id(root, ref) if ref else None).encode())
    if key:
        for path, *_ in key[2]:
            # Includes content changes even when a tool preserves size and mtime.
            row = source(root, path)
            digest.update(json.dumps(row, sort_keys=True).encode())
    for path in reports:
        try:
            digest.update(str(path).encode())
            with path.open("rb") as stream:
                while chunk := stream.read(65536):
                    digest.update(chunk)
        except OSError:
            digest.update(b"unavailable")
    return digest.hexdigest()


def assemble(root: Path, result: dict) -> dict:
    """Add bounded source snapshots to the unchanged brief data; no new analysis claims."""
    related: dict[str, list[str]] = {}
    for finding in result["consequences"]["findings"]:
        paths = list(finding["files"])
        for row in result["check"]["dangling_imports"]:
            if finding["id"] == "dangling-import:" + row["deleted"]:
                paths = list(dict.fromkeys([*paths, row["deleted"]]))
        related[finding["id"]] = paths
    changed = [r["path"] for r in result["triage"]["files"]]
    paths = list(dict.fromkeys([p for group in related.values() for p in group] + changed + result["triage"]["tests"]["paths"]))
    sources = {p: {"current": source(root, p), "base": source(root, p, result["change"]["base"])} for p in paths[:MAX_SOURCE_FILES]}
    return {"brief": result, "sources": sources, "related": related, "source_limit": MAX_SOURCE_FILES,
            "source_omitted": max(0, len(paths) - len(sources))}


class Session:
    def __init__(self, root: Path, cfg: config.Config, since: str | None = None, *, ran=(), reports=(), coverage_reports=(), config_factory=None):
        self.root, self.cfg = root.resolve(), cfg
        self.since = since or since_mod.default_since(self.root)
        self.config_factory = config_factory
        self.options = dict(ran=ran, reports=tuple(str(Path(p).resolve()) for p in reports), coverage_reports=tuple(str(Path(p).resolve()) for p in coverage_reports))
        self.reports = tuple(Path(p).resolve() for p in (*reports, *coverage_reports))
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.data: dict = {}
        self.key = ""
        self.refresh()

    def current_key(self) -> str:
        return fingerprint(self.root, self.since or (self.data.get("brief", {}).get("change", {}).get("since")), self.reports)

    def refresh(self) -> dict:
        with self.lock:
            before = self.current_key()
            if self.config_factory:
                self.cfg = self.config_factory()
            result = brief.compute(self.root, self.cfg, self.since, **self.options)
            data = assemble(self.root, result)
            after = fingerprint(self.root, result["change"]["since"], self.reports)
            data["changed_during_capture"] = before != after
            self.data, self.key = data, before
            return data

    def stale(self) -> bool:
        with self.lock:
            return self.data["changed_during_capture"] or self.current_key() != self.key


def make_server(session: Session, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not write capability URLs or repository paths to request logs.

        def send(self, status: int, body: str, kind: str = "application/json"):
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}" and self.path.startswith(f"/{session.token}/")

        def do_GET(self):
            if not self.allowed():
                self.send(404, '{}')
                return
            route = self.path[len(session.token) + 2:]
            with session.lock:
                if route == "":
                    self.send(200, reviewview.render(session.data, live=True), "text/html")
                elif route == "status":
                    self.send(200, json.dumps({"stale": session.stale()}))
                elif route == "snapshot":
                    self.send(200, json.dumps(session.data))
                elif route == "brief":
                    self.send(200, briefhtml.render(session.data["brief"]), "text/html")
                else:
                    self.send(404, '{}')

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if not self.allowed() or self.path != f"/{session.token}/refresh" or self.headers.get("X-Tessri-Review") != session.token or (origin and origin != expected):
                self.send(403, '{}')
                return
            try:
                self.send(200, json.dumps(session.refresh()))
            except (brief.BriefError, config.ConfigError, OSError, subprocess.SubprocessError) as exc:
                self.send(409, json.dumps({"error": str(exc)}))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(session: Session, port: int = 0, open_browser: bool = True) -> None:
    with make_server(session, port) as server:
        url = f"http://127.0.0.1:{server.server_port}/{session.token}/"
        print(f"Tessri local review: {url}\nRead-only checkout. Ctrl-C stops the local session.", flush=True)
        if open_browser:
            try:
                if not webbrowser.open(url):
                    print("Open the URL above in your browser.", flush=True)
            except webbrowser.Error:
                print("Open the URL above in your browser.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
