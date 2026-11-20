import atexit
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# The command line, the hooks and the server keep what the analyzers read in the user's cache directory; the suite
# must leave that alone, so every test process gets a cache directory of its own, removed when it exits.
_CACHE_DIR = tempfile.mkdtemp(prefix="tessri-test-cache-")
os.environ["TESSRI_CACHE_DIR"] = _CACHE_DIR
atexit.register(shutil.rmtree, _CACHE_DIR, ignore_errors=True)


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")  # byte-exact: no CRLF translation on Windows


def git(root: Path, *args: str, when: str | None = None, author: tuple[str, str] | None = None) -> None:
    env = dict(os.environ)
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    if author:
        name, email = author
        env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", *args], cwd=root, env=env, check=True, capture_output=True)


class TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
