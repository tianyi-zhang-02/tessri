"""Files that usually change with the changed files, and are not in this change.

A reviewer's first question about a change is often what it forgot: the test beside the module, the changelog, the
schema the migration always comes with. History says what usually comes with a file: for each changed code file, the
commits that touched it in the last year (up to the base of the change, under the name each file has now, bulk commits
and merges apart), and the other files in those commits. A *companion* is a file in at least half of them, three at
least, that still exists and that this change leaves untouched. It is a prompt to check whether the file should have
changed too, not a rule that it must: a companion can be a file the author rightly left alone.
"""

from __future__ import annotations

from collections.abc import Container, Sequence
from pathlib import Path

from . import gitlog

MIN_TOGETHER = 3  # commits a companion shares with the changed file, at least
MIN_SHARE = 0.5  # of the changed file's commits in the window
LISTED = 3  # companions per changed file; the JSON holds them all
NAMED = 6  # companions a sentence names


def compute(root: Path, base: str, now: float, rows: Sequence[dict], touched: Container[str], present: Container[str]) -> list[dict]:
    """Adds `companions` to each row (`commits` in the window and `usually_with`: the companions this change leaves
    untouched, surest first) and returns them grouped by companion for the page, surest first."""
    found = gitlog.co_changes(root, base, [r["path"] for r in rows], now)
    if found is None:
        for r in rows:
            r["companions"] = {"available": False, "reason": "git could not read the history of the changed files", "commits": 0, "usually_with": []}
        return []
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        co = found.get(r["path"], gitlog.CoChange())
        usual = [
            {"path": other, "together": k}
            for other, k in co.together.items()
            if k >= MIN_TOGETHER and k >= MIN_SHARE * co.commits and other not in touched and other in present
        ]
        usual.sort(key=lambda c: (-c["together"], c["path"]))
        r["companions"] = {"available": True, "commits": co.commits, "window_days": gitlog.COMPANION_DAYS, "usually_with": usual}
        for c in usual:
            grouped.setdefault(c["path"], []).append({"path": r["path"], "together": c["together"], "of": co.commits})
    out = [{"path": path, "with": sorted(pairs, key=lambda w: (-w["together"] / w["of"], -w["together"], w["path"]))} for path, pairs in grouped.items()]
    out.sort(key=lambda g: (-max(w["together"] / w["of"] for w in g["with"]), -max(w["together"] for w in g["with"]), g["path"]))
    return out


def _with(pairs: Sequence[dict], limit: int = 2) -> str:
    shown = "; ".join(f"`{w['path']}` {w['together']} of {w['of']}" for w in pairs[:limit])
    return shown + (f"; and {len(pairs) - limit} more" if len(pairs) > limit else "")


def line(grouped: Sequence[dict], limit: int = NAMED) -> str | None:
    """One Markdown paragraph naming the companions this change leaves untouched, surest first; None when there are none."""
    if not grouped:
        return None
    named = ", ".join(f"`{g['path']}` (with {_with(g['with'])} commits)" for g in grouped[:limit])
    more = f" and {len(grouped) - limit} more under `companions`" if len(grouped) > limit else ""
    return f"Usually changed together, not in this change: {named}{more}. Half or more of a changed file's commits in the last {gitlog.COMPANION_DAYS} days, up to the base; a prompt to check, not a rule."


def open_items(grouped: Sequence[dict], limit: int = NAMED) -> list[dict]:
    """What a person has to settle: the companions this change leaves untouched."""
    if not grouped:
        return []
    one = len(grouped) == 1
    named = ", ".join(f"`{g['path']}`" for g in grouped[:limit]) + (f" and {len(grouped) - limit} more" if len(grouped) > limit else "")
    first = grouped[0]
    sample = f" (`{first['path']}` changed with `{first['with'][0]['path']}` in {first['with'][0]['together']} of its last {first['with'][0]['of']} commits)"
    return [{
        "kind": "companions-untouched",
        "text": f"{named} usually {'changes' if one else 'change'} with the changed files{sample} but {'is' if one else 'are'} not in this change: check whether {'it' if one else 'they'} should be.",
        "files": [g["path"] for g in grouped],
    }]
