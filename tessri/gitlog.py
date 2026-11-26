"""Per-file git activity and per-author credit from a single `git log` pass. The renames git detects are followed, so
a file keeps its history across a move; a file rewritten beyond git's similarity threshold when moved starts over."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import inventory

HALF_LIFE_DAYS = 365  # when crediting ownership, a commit loses half its weight per year
BULK_FILES = 300  # a commit touching this many files (mass reformat, vendor drop, first import) says little about who maintains each one
_BOT = re.compile(r"\[bot\]|^(?:dependabot|renovate|github-actions|pre-commit-ci)\b|[-_](?:ci|bot)$", re.I)  # a name, or the local part of an address, ending in -ci or -bot is automation
# A commit that repairs something: `fix: x`, `fix(scope): x`, `Fix typo`, `Fixes #3`, `bugfix`, `hotfix`, `Revert "x"`.
# Judged from the subject alone, so a repository that writes no such subjects simply shows no fix history.
FIX_SUBJECT = re.compile(r"^(?:fix(?:es|ed)?|bug-?fix|hotfix|revert)\b", re.I)
FIX_WINDOW_DAYS = 90
COMPANION_DAYS = 365  # how far back co-changes are read
COMPANION_COMMITS = 50  # the latest commits of each changed file that count


@dataclass
class FileActivity:
    first: int  # epoch seconds of the oldest commit touching the file
    last: int  # epoch seconds of the newest commit touching the file
    commits_active: int  # commits inside the active window
    commits_year: int  # commits in the last 365 days
    authors_year: int  # distinct authors in the last 365 days
    fixes_90: int = 0  # fix or revert commits in the last 90 days (see FIX_SUBJECT)
    fixes_year: int = 0  # fix or revert commits in the last 365 days


@dataclass
class Author:
    name: str  # as written on their newest commit
    emails: set[str]  # every address they committed from, lowercase; identifies the person and never goes in a report
    last: int  # epoch seconds of their newest commit anywhere in the repository
    commits_active: int = 0  # their commits inside the active window, merges included: in a merge-commit workflow the merger is often the reviewer


@dataclass
class Activity:
    files: dict[str, FileActivity]
    head: str | None
    shallow: bool
    commits: int
    authors: dict[str, Author]  # identity -> author; bots and ignored authors are left out
    credit: dict[str, dict[str, float]]  # path -> identity -> commits, recent ones weighing more
    recent: dict[str, dict[str, set[int]]] = field(default_factory=dict)  # path -> identity -> author times of their commits to it in the last 365 days: what `credit` counts, undecayed, bulk commits apart


REASONS = ("not-a-repository", "no-commits", "git-not-found", "git-error", "not-requested")


@dataclass(frozen=True)
class GitState:
    """What git could say about the analysed tree, probed apart from the history read: `load` returning None only
    says that no usable history came back, and a caller deciding what to trust needs to know why. `head` is HEAD
    resolved on its own; `Activity.head` is the revision history was read up to, which for a change is its base."""

    available: bool  # usable history was read
    reason: str | None  # None when available, else one of REASONS
    head: str | None  # full object id of HEAD; None when nothing resolves to a commit
    history_rev: str | None  # full object id of the commit history was read up to; None when unavailable or not requested


@dataclass
class Change:
    """One commit as review work: what it touched and how many lines moved."""

    sha: str  # abbreviated
    when: int  # epoch seconds, author date
    identity: str | None  # None for bots and ignored authors: their changes still need review, but they own nothing
    name: str
    subject: str
    files: dict[str, int] = field(default_factory=dict)  # path -> lines added plus deleted (0 for a binary file)


def _git_line(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def commit_id(root: Path, rev: str) -> str | None:
    """The full object id of `rev` as a commit, None when it does not resolve to one (no commits yet, unknown name,
    not a repository, no git)."""
    return _git_line(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")


def _probe(root: Path | None, *args: str) -> tuple[int | None, str, str]:
    """(exit code, stdout, stderr) of one git command, in English; the code is None when git could not start."""
    cmd = ["git", *(("-C", str(root)) if root else ()), *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env={**os.environ, "LC_ALL": "C"})
    except OSError:
        return None, "", ""
    except subprocess.SubprocessError as exc:
        return -1, "", str(exc)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


_NOT_A_REPOSITORY = re.compile(r"not a git repository", re.I)


def unavailable_reason(root: Path) -> str:
    """Why `load` returned None, one probe at a time. Only the answers git gives for "no repository here" and "HEAD
    is unborn" get those names; every other failure, including a `rev-parse` that fails inside a valid repository,
    is a `git-error`, so a read that broke is never reported as an empty repository."""
    code, _, _ = _probe(None, "--version")
    if code is None:
        return "git-not-found"
    if code != 0:
        return "git-error"
    code, out, err = _probe(root, "rev-parse", "--is-inside-work-tree")
    if (code == 0 and out == "false") or (code == 128 and _NOT_A_REPOSITORY.search(err)):
        return "not-a-repository"
    if code != 0 or out != "true":
        return "git-error"
    code, _, _ = _probe(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if code == 1:  # `--verify --quiet` exits 1 for exactly one thing: the name does not resolve, here an unborn HEAD
        return "no-commits"
    return "git-error"


def describe(root: Path, rev: str, activity: Activity | None, requested: bool = True) -> GitState:
    """The GitState behind an analysis: HEAD is resolved on its own, `rev` is the history revision that was asked
    for, and a missing history gets its reason. `requested=False` is for a result that read no history at all."""
    head = commit_id(root, "HEAD")
    if not requested:
        return GitState(False, "not-requested", head, None)
    if activity is None:
        return GitState(False, unavailable_reason(root), head, None)
    return GitState(True, None, head, commit_id(root, rev))


def identity(name: str, email: str) -> str:
    """One key per person. People commit from several addresses (work, personal, GitHub noreply), and keying by
    address made a maintainer look gone whenever their recent commits used another one, so the name is the key.
    Two people sharing a name get merged, which hides a gap rather than inventing one; a `.mailmap` entry is
    the exact fix either way. A name that is empty or is itself an address says nothing, so the address is used."""
    name = " ".join(name.split()).casefold()
    return name if name and "@" not in name else (email or name).lower()


def is_ignored(name: str, email: str, patterns: Sequence[str]) -> bool:
    """Bots never own code; `ignore_authors` globs are matched against the name and the email, ignoring case."""
    if _BOT.search(name) or _BOT.search(email) or _BOT.search(email.partition("@")[0]):
        return True
    return any(fnmatch.fnmatchcase(v.lower(), p.lower()) for p in patterns for v in (name, email))


@dataclass
class FileChange:
    """What a change did to one file, between a revision and the working tree."""

    added: int
    deleted: int
    state: str  # "added" | "modified" | "deleted" | "moved"
    origin: str | None = None  # a moved file's path at the revision

    @property
    def lines(self) -> int:
        return self.added + self.deleted


def _entries(records: list[str]) -> Iterator[tuple[str, str, str | None]]:
    """(status, path, path before or None) from a `--name-status -M -z` listing, in which a rename or copy is the
    status, the old name and the new name as records of their own."""
    i = 0
    while i + 1 < len(records):
        status = records[i]
        if status[:1] in ("R", "C") and i + 2 < len(records):
            yield status, records[i + 2], records[i + 1]
            i += 3
        else:
            yield status, records[i + 1], None
            i += 2


def renames(root: Path, rev: str = "HEAD") -> dict[str, str]:
    """Path at `rev` -> path in the working tree, for the files git sees as moved since `rev` (`-M`, its default
    similarity). Empty when nothing moved or git cannot tell."""
    text = _git_text(root, "diff", "--relative", "--name-status", "-M", "-z", rev)
    if not text:
        return {}
    return {old: new for status, new, old in _entries(text.split("\0")) if old is not None and status.startswith("R")}


def diff(root: Path, rev: str) -> dict[str, FileChange] | None:
    """Path -> what changed between `rev` and the working tree, untracked files included as additions of their line
    count. A file git sees as moved is one entry under its new name with `origin`, and its lines are the edits made on
    the way, so a pure move has none. None when git cannot read the diff."""
    names = _git_text(root, "diff", "--relative", "--name-status", "-M", "-z", rev)
    stats = _git_text(root, "diff", "--relative", "--numstat", "-M", "-z", rev)
    others = _git_text(root, "ls-files", "--others", "--exclude-standard", "-z")
    if names is None or stats is None or others is None:
        return None
    out: dict[str, FileChange] = {}
    for status, path, old in _entries(names.split("\0")):
        moved = old is not None and status.startswith("R")
        state = "moved" if moved else {"A": "added", "C": "added", "D": "deleted"}.get(status[:1], "modified")
        out[path] = FileChange(0, 0, state, old if moved else None)
    records = stats.split("\0")
    i = 0
    while i < len(records):
        record = records[i]
        i += 1
        if not record:
            continue
        added, _, rest = record.partition("\t")
        deleted, _, path = rest.partition("\t")
        if not path and i + 1 < len(records):  # a rename: the old and the new name follow as records of their own
            path = records[i + 1]
            i += 2
        counts = (int(added), int(deleted)) if added.isdigit() and deleted.isdigit() else (0, 0)  # binary files count no lines
        change = out.get(path)
        if change is None:
            out[path] = FileChange(*counts, "modified")
        else:
            change.added, change.deleted = counts
    for path in others.split("\0"):
        if path and path not in out:
            text = inventory.read_text(root / path)
            out[path] = FileChange(len(text.splitlines()) if text else 0, 0, "added")
    return out


class _Names:
    """The name a file has at the revision read, for every name it had earlier. History is read newest first, so when
    a commit that renamed `old` to `new` goes by, every older mention of `old` belongs to the file now called whatever
    `new` became, and every older mention of `new` is another file, one that was deleted before the rename: its name
    is marked dead (None) so that its history is never merged into the live file. An `old` re-created after the
    rename is a new file too, because its commits were seen before the rename went by."""

    def __init__(self) -> None:
        self.current: dict[str, str | None] = {}

    def renamed(self, old: str, new: str) -> str | None:
        """The current name of the file a commit renamed `old` to `new`; None when that file is dead."""
        now = self.current.pop(new, new)
        self.current[old] = now
        self.current[new] = None
        return now

    def of(self, path: str) -> str | None:
        return self.current.get(path, path)


def _commits(lines) -> Iterator[tuple[int, str, str, str, list[tuple[str, ...]]]]:
    """(epoch, author name, author email, subject, entries) for each commit in a `git log --name-status` stream; an
    entry is (status, path), or (status, old, new) for a rename or copy."""
    head: tuple[int, str, str, str] | None = None
    entries: list[tuple[str, ...]] = []
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("\x1e"):
            if head:
                yield (*head, entries)
            stamp, _, rest = line[1:].partition("\t")
            name, _, rest = rest.partition("\t")
            email, _, subject = rest.partition("\t")
            try:
                head = (int(stamp), name, email, subject)
            except ValueError:
                head = (0, name, email, subject)
            entries = []
        elif line:
            parts = line.split("\t")
            if parts[0][:1] in ("R", "C") and len(parts) >= 3:
                entries.append((parts[0], parts[1], parts[2]))
            elif len(parts) >= 2:
                entries.append((parts[0], parts[1]))
    if head:
        yield (*head, entries)


def _touched(entries: list[tuple[str, ...]], names: _Names) -> list[tuple[str, bool]]:
    """(current name, content changed) for each file a commit touched that still exists at the revision read, each
    once. A rename counts as touching the file it moved, but a pure move (`R100`) changes no content, so it is
    activity and not maintenance credit; a copy touches the copy only, and the source keeps its own history."""
    seen: dict[str, bool] = {}
    for entry in entries:
        if len(entry) == 3:
            status, old, new = entry
            name = names.renamed(old, new) if status.startswith("R") else names.of(new)
            changed = status != "R100"
        else:
            name, changed = names.of(entry[1]), True
        if name is not None:
            seen[name] = seen.get(name, False) or changed
    return list(seen.items())


def load(root: Path, now: float, active_days: int, ignore_authors: Sequence[str] = (), rev: str = "HEAD") -> Activity | None:
    """Return None when `root` is not a git work tree or has no commits. History is read up to `rev`: asking for
    the base of a change gives the picture before it, in which its own author owns nothing yet.

    Paths are relative to `root` (`--relative`), so a sub-directory of a larger
    repository is analysed on its own history. Merge commits list no files. The
    renames git detects (`-M`, its default similarity) are followed, so a moved
    file keeps its history under its current name, the name it has in the working
    tree: a move made since `rev`, committed or not, is read from the diff first.
    A move across the `--relative` boundary is an addition. Names and emails go
    through `.mailmap`, so one person with several addresses can be merged.
    """
    cmd = [
        "git", "-c", "core.quotepath=false", "-C", str(root), "log",
        "--relative", "-M", "--name-status", "--format=%x1e%at%x09%aN%x09%aE%x09%s", rev, "--",
    ]  # fmt: skip
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None

    active_cut = now - active_days * 86400
    year_cut = now - 365 * 86400
    fix_cut = now - FIX_WINDOW_DAYS * 86400
    stats: dict[str, list] = {}  # path -> [first, last, active, year, {authors}, fixes in the window, fixes in the year]
    authors: dict[str, Author] = {}
    credit: dict[str, dict[str, float]] = {}
    bulk: dict[str, dict[str, float]] = {}  # credit from bulk commits, used only for files nothing else touched
    recent: dict[str, dict[str, set[int]]] = {}
    commits = 0
    names = _Names()
    for old, new in renames(root, rev).items():  # the working tree's names come first: history is read under them
        names.renamed(old, new)
    assert proc.stdout is not None
    with proc:  # closes the pipe and reaps the process
        for when, who, email, subject, entries in _commits(proc.stdout):
            commits += 1
            files = _touched(entries, names)
            repair = bool(FIX_SUBJECT.match(subject))
            person = None if is_ignored(who, email, ignore_authors) else identity(who, email)
            weight = 0.5 ** (max(0.0, now - when) / (HALF_LIFE_DAYS * 86400))
            if person:
                known = authors.get(person)
                if known is None:  # the log is newest first, so the first sighting is the newest commit
                    authors[person] = Author(who, {email.lower()}, when)
                else:
                    known.emails.add(email.lower())
                    known.last = max(known.last, when)
                if when >= active_cut:
                    authors[person].commits_active += 1
            target = bulk if len(files) >= BULK_FILES else credit
            for path, changed in files:
                entry = stats.get(path)
                if entry is None:
                    entry = stats[path] = [when, when, 0, 0, set(), 0, 0]
                entry[0] = min(entry[0], when)
                entry[1] = max(entry[1], when)
                if when >= active_cut:
                    entry[2] += 1
                if when >= year_cut:
                    entry[3] += 1
                    entry[4].add(who)
                    if repair:
                        entry[6] += 1
                        if when >= fix_cut:
                            entry[5] += 1
                if person and changed:
                    slot = target.setdefault(path, {})
                    slot[person] = slot.get(person, 0.0) + weight
                    if target is credit and when >= year_cut:
                        recent.setdefault(path, {}).setdefault(person, set()).add(when)
    if proc.returncode != 0 or commits == 0:
        return None
    for path, slot in bulk.items():
        credit.setdefault(path, slot)

    return Activity(
        files={p: FileActivity(s[0], s[1], s[2], s[3], len(s[4]), s[5], s[6]) for p, s in stats.items()},
        head=_git_line(root, "rev-parse", "--short", rev),
        shallow=_git_line(root, "rev-parse", "--is-shallow-repository") == "true",
        commits=commits,
        authors=authors,
        credit=credit,
        recent=recent,
    )


@dataclass
class CoChange:
    """The commits that touched one file lately, and how many of them touched each other file too."""

    commits: int = 0
    together: dict[str, int] = field(default_factory=dict)


def co_changes(root: Path, rev: str, paths: Sequence[str], now: float, days: int = COMPANION_DAYS, limit: int = COMPANION_COMMITS, ignore_authors: Sequence[str] = ()) -> dict[str, CoChange] | None:
    """For each of `paths`, its commits up to `rev` in the last `days` days (the latest `limit` of them) and how many
    of those touched each other file: what usually changes together. Merge commits, bulk commits (BULK_FILES files
    or more) and ignored authors' commits are left out; files are read under the names the working tree has, like
    `load`, and a path is selected by its current name only. None when git cannot answer."""
    out = {p: CoChange() for p in paths}
    if not paths:
        return out
    listing = _git_text(root, "log", "--no-merges", "--format=%H%x09%at", rev, "--", *paths)
    if listing is None:
        return None
    cut = now - days * 86400
    inside = [sha for sha, _, stamp in (line.partition("\t") for line in listing.splitlines()) if stamp.isdigit() and int(stamp) >= cut]
    if not inside:
        return out
    body = _git_text(root, "log", "--no-walk=unsorted", "--stdin", "--relative", "-M", "--name-status", "--format=%x1e%at%x09%aN%x09%aE%x09%s", stdin="\n".join(inside) + "\n")
    if body is None:
        return None
    names = _Names()
    for old, new in renames(root, rev).items():
        names.renamed(old, new)
    wanted = set(paths)
    for _when, who, email, _subject, entries in _commits(body.split("\n")):  # newest first, as listed; not splitlines(), which would eat the \x1e marks
        if is_ignored(who, email, ignore_authors):
            continue
        files = {name for name, _ in _touched(entries, names)}
        if len(files) >= BULK_FILES:
            continue
        for path in files & wanted:
            entry = out[path]
            if entry.commits >= limit:
                continue
            entry.commits += 1
            for other in files:
                if other != path:
                    entry.together[other] = entry.together.get(other, 0) + 1
    return out


def _git_text(root: Path, *args: str, stdin: str | None = None) -> str | None:
    try:
        res = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
            input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def changes(root: Path, now: float, days: int, ignore_authors: Sequence[str] = ()) -> list[Change] | None:
    """Commits of the last `2 * days` days with the lines they moved per file, newest first, for comparing a
    window with the one before it. The window is cut by author date, like ownership: `git log --since` would
    stop at the first old-dated commit it meets and silently drop newer ones behind it, so the commits are listed
    first and the diffs are read only for the ones inside. Merge commits are left out (they carry no diff of
    their own); the renames git detects are followed, so a moved file's lines are counted under its current name.
    None when `root` has no usable git history."""
    cut = now - 2 * days * 86400
    listing = _git_text(root, "log", "--no-merges", "--format=%H%x09%at")
    if listing is None:
        return None
    inside = [sha for sha, _, stamp in (line.partition("\t") for line in listing.splitlines()) if stamp.isdigit() and int(stamp) >= cut]
    if not inside:
        return []
    body = _git_text(
        root, "log", "-z", "--no-walk=unsorted", "--stdin", "--relative", "-M", "--numstat", "--format=%x1e%h%x09%at%x09%aN%x09%aE%x09%s",
        stdin="\n".join(inside) + "\n",
    )  # fmt: skip
    if body is None:
        return None
    # With -z every record ends in NUL and no path is quoted: a rename is a numstat entry with an empty path followed
    # by the old and the new name as records of their own. The first entry after a header carries the blank line git
    # prints between a commit's message and its diff.
    found: list[Change] = []
    current: Change | None = None
    names = _Names()
    for old, new in renames(root).items():  # an uncommitted move: lines count under the name the tree has now
        names.renamed(old, new)
    records = body.split("\0")
    i = 0
    while i < len(records):
        record = records[i].lstrip("\n")
        i += 1
        if record.startswith("\x1e"):
            sha, stamp, name, email, subject = (record[1:].split("\t", 4) + [""] * 5)[:5]
            person = None if is_ignored(name, email, ignore_authors) else identity(name, email)
            current = Change(sha, int(stamp) if stamp.isdigit() else 0, person, name, subject)
            found.append(current)
        elif record and current is not None:
            added, _, rest = record.partition("\t")
            deleted, _, path = rest.partition("\t")
            moved = int(added) + int(deleted) if added.isdigit() and deleted.isdigit() else 0
            if not path and i + 1 < len(records):  # a dead file's lines were still work: they count under its last name
                path = names.renamed(records[i], records[i + 1]) or records[i + 1]
                i += 2
            else:
                path = names.of(path) or path
            if path:
                current.files[path] = current.files.get(path, 0) + moved
    return found
