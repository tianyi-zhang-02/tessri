"""What the analyzers read from each file, kept between runs, so that a second run parses only what changed.

An entry is keyed by the analyzer (with the format of what it keeps) and a digest of the file's text, never by the
file's place: a file that moved or was copied is found again, a file that changed is read again, and nothing in an
entry depends on what else the repository holds. The store is one JSON file per repository in the user's cache
directory: `TESSRI_CACHE_DIR` when set, else `XDG_CACHE_HOME/tessri`, else `~/Library/Caches/tessri` on macOS,
`%LOCALAPPDATA%\\tessri\\cache` on Windows and `~/.cache/tessri` elsewhere. The file is named after the
repository's git directory, so every worktree of a repository and every scratch copy `check` makes of a base commit
share it; without git it is named after the root. Entries no run has used for KEEP_DAYS go at the next write, and
the file is replaced whole, atomically, so a run that stops halfway leaves the old one. A cache changes no number:
the same tree and history give the same output with it, without it (`--no-cache`, or `cache = false` in the
configuration) and after the directory is deleted."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__

FORMAT = 1  # the file's layout; a file of another format or another version of the package is started over
KEEP_DAYS = 30  # an entry no run has used for this long is dropped at the next write
REFRESH_DAYS = 7  # a run that only read entries still rewrites the file when what it used was last marked this long ago
MAX_BYTES = 256_000_000  # a file past this is not read: something went wrong, start over


def digest(text: str) -> str:
    """The key of a file's text."""
    return hashlib.sha1(text.encode("utf-8", "surrogatepass"), usedforsecurity=False).hexdigest()


def directory() -> Path:
    """Where the stores live; see the module docstring."""
    given = os.environ.get("TESSRI_CACHE_DIR")
    if given:
        return Path(given).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "tessri"
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "tessri"
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "tessri" / "cache"
    return home / ".cache" / "tessri"


def repository_key(root: Path) -> str:
    """The name of a repository's store: from its git directory, which its worktrees share, else from the root."""
    root = Path(root)
    try:
        res = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"], capture_output=True, text=True, timeout=30)
        where = res.stdout.strip() if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        where = ""
    ident = str((root / where).resolve()) if where else str(root.resolve())
    return hashlib.sha1(ident.encode("utf-8", "surrogateescape"), usedforsecurity=False).hexdigest()[:16]


class Store:
    """The entries of one repository: `get` and `put` by namespace and digest, `save` to write what changed."""

    def __init__(self, path: Path | None, now: float | None = None):
        self.path = path  # None keeps the entries in memory for this run only
        self.now = time.time() if now is None else now
        self.day = int(self.now // 86400)
        self.entries: dict[str, dict] = {}
        self.used: set[str] = set()
        self.hits = 0
        self.misses = 0
        self.dirty = False
        self.loaded = False

    def _load(self) -> None:
        self.loaded = True
        if self.path is None:
            return
        try:
            if self.path.stat().st_size > MAX_BYTES:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # no file yet, or not one of ours: start over
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != __version__:
            return
        entries = data.get("entries")
        if isinstance(entries, dict):
            self.entries = {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, dict) and "v" in v}

    def get(self, namespace: str, key: str) -> Any:
        """The value kept under `namespace` for `key`, or None."""
        if not self.loaded:
            self._load()
        full = f"{namespace}:{key}"
        entry = self.entries.get(full)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        self.used.add(full)
        return entry["v"]

    def put(self, namespace: str, key: str, value: Any) -> None:
        """Keep a JSON value under `namespace` for `key`."""
        if not self.loaded:
            self._load()
        full = f"{namespace}:{key}"
        self.entries[full] = {"t": self.day, "v": value}
        self.used.add(full)
        self.dirty = True

    def save(self) -> bool:
        """Write the file when an entry was added, or when the entries this run used were last marked long ago, so
        that what is in use stays and what is not goes after KEEP_DAYS. True when written."""
        if self.path is None or not self.loaded:
            return False
        stale = any(self.entries[k].get("t", 0) < self.day - REFRESH_DAYS for k in self.used)
        if not (self.dirty or stale):
            return False
        for k in self.used:
            self.entries[k]["t"] = self.day
        keep = {k: v for k, v in self.entries.items() if isinstance(v.get("t"), int) and self.day - v["t"] <= KEEP_DAYS}
        data = {"format": FORMAT, "version": __version__, "entries": keep}
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            return False  # a read-only home or a full disk costs time, never the run
        self.entries = keep
        self.dirty = False
        return True


def for_repository(root: Path, enabled: bool = True, now: float | None = None) -> Store | None:
    """The store of the repository at `root`, or None when the cache is off."""
    if not enabled:
        return None
    return Store(directory() / f"{repository_key(root)}.json", now)
