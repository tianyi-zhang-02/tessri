"""Test, on a repository's own pull requests, the claim behind "who can look" in `tessri triage` and `tessri brief`:
that the people who maintain the changed files, the authors apart, are the people who review the change.

`collect` reads the merged pull requests of a repository on GitHub through the `gh` command, which must be installed
and signed in: newest first, those whose merge commit the local checkout holds, with their reviews, the reviewers
that were requested, and the git identities behind their commits. `score` is offline. For each pull request it moves
a detached worktree to the merge commit, runs the triage of the change against the commit's first parent with the
clock set to the merge time, so nothing from after the merge is read, and compares the names triage offers with the
people who reviewed. Two baselines are scored the same way from git alone (who committed to the changed files in the
year before; who committed most to the repository in the 90 days before) and one from the review data git does not
hold (who reviewed most often before that pull request).

    python tools/reviewer_match.py collect owner/name path/to/checkout --limit 300 --out pulls.json
    python tools/reviewer_match.py score pulls.json path/to/checkout
    python tools/reviewer_match.py score pulls.json path/to/checkout --format json --out reviewers.json

A method offers up to three people, the authors apart, and is judged on the pull requests where someone other than
the authors reviewed and the change touched a code file (triage ranks code files, so on a change of documents or
configs no method has anything to go on). Precision: offered people who reviewed. Recall: reviewers who were offered.
hit@1: the first name offered reviewed. Any hit: at least one offered name reviewed. Logins are matched to git names
through the commits' identities and the profiles' names; an offered name that matches no login is dropped from the
offer. Zero dependencies, like the tool; the checkout is never changed, the worktree lives in a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tessri import config, triage  # noqa: E402  (the package in this checkout)

K = 3  # names a method offers, like triage
STATES = ("APPROVED", "CHANGES_REQUESTED", "COMMENTED")  # a review in any of these states counts as having looked
MIN_PAST = 20  # review slots the gatekeeper baseline needs to have seen before it names anyone
WIDTH = 110
BOT = re.compile(r"\[bot\]$|^(?:copilot|github-actions|dependabot|coderabbitai|codecov|renovate|pre-commit-ci|svc)|[-_]ci$|nemo-ci", re.I)
NOREPLY = re.compile(r"^(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$")
METHODS = (
    ("tessri", "triage: active holders of the changed files"),
    ("recent", "committers to the changed files, last 365 days"),
    ("usual", "busiest committers repo-wide, last 90 days"),
    ("gatekeepers", "most frequent reviewers before this pull request"),
)


class ReviewerMatchError(ValueError):
    """The pull requests cannot be collected or scored as asked; one sentence for the person."""


def gh(path: str) -> list | dict:
    """One call of the GitHub API through `gh`, which holds the sign-in."""
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=300)
    except OSError as exc:
        raise ReviewerMatchError(f"gh is not available ({exc}); install the GitHub command line and sign in") from exc
    if out.returncode != 0:
        raise ReviewerMatchError(f"gh api {path}: {out.stderr.strip().splitlines()[-1] if out.stderr.strip() else 'failed'}")
    return json.loads(out.stdout)


def _git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=600)
    return res.stdout.strip() if res.returncode == 0 else ""


def _has(root: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").casefold())


# --- collect -------------------------------------------------------------------------------------------------------


def collect(repo: str, root: Path, limit: int = 300, base: str = "main", api: Callable[[str], list | dict] = gh, log=None) -> dict:
    """The merged pull requests of `repo` into `base`, newest first, that the checkout at `root` holds, with their
    reviews, requested reviewers and commit identities, as the dict `score` reads."""
    pulls: list[dict] = []
    seen: set[int] = set()
    page = 1
    while len(pulls) < limit and page <= 40:
        batch = api(f"repos/{repo}/pulls?state=closed&base={base}&sort=updated&direction=desc&per_page=100&page={page}")
        page += 1
        if not batch:
            break
        for pr in batch:
            sha = pr.get("merge_commit_sha")
            if pr["number"] in seen or not pr.get("merged_at") or not sha or not _has(root, sha):
                continue  # the listing is by update time, so a page can repeat a pull request another page already gave
            seen.add(pr["number"])
            parent = _git(root, "rev-parse", f"{sha}^1")
            if not parent:
                continue
            pulls.append({
                "number": pr["number"], "title": pr["title"], "author": pr["user"]["login"], "merged_at": pr["merged_at"], "merge": sha, "base": parent,
                "requested": [u["login"] for u in pr.get("requested_reviewers") or []],
            })
            if len(pulls) >= limit:
                break
        if log:
            log(f"page {page - 1}: {len(pulls)} pull requests in the local history so far")
    if not pulls:
        raise ReviewerMatchError(f"no merged pull request of {repo} into {base} has its merge commit in {root}; fetch the repository first")
    pulls.sort(key=lambda p: p["merged_at"], reverse=True)
    identities: dict[str, dict] = {}

    def learn(login: str | None, name: str | None = None, email: str | None = None) -> None:
        if not login:
            return
        ident = identities.setdefault(login, {"names": [], "emails": []})
        if name and name not in ident["names"]:
            ident["names"].append(name)
        if email and email not in ident["emails"]:
            ident["emails"].append(email)

    for i, pr in enumerate(pulls):
        reviews = api(f"repos/{repo}/pulls/{pr['number']}/reviews?per_page=100")
        pr["reviews"] = [{"login": r["user"]["login"], "state": r["state"], "at": r.get("submitted_at")} for r in reviews if r.get("user")]
        commits = api(f"repos/{repo}/pulls/{pr['number']}/commits?per_page=100")
        pr["commit_authors"] = []
        for c in commits:
            name, email = c["commit"]["author"]["name"], c["commit"]["author"]["email"]
            login = (c.get("author") or {}).get("login")
            pr["commit_authors"].append({"login": login, "name": name, "email": email})
            learn(login, name, email)
        if log and i % 25 == 0:
            log(f"{i + 1} of {len(pulls)} pull requests read")
    for login in sorted({r["login"] for pr in pulls for r in pr["reviews"]} | {pr["author"] for pr in pulls}):
        if identities.get(login, {}).get("names"):
            continue
        try:
            user = api(f"users/{login}")
        except ReviewerMatchError:
            continue
        learn(login, user.get("name") if isinstance(user, dict) else None)
    return {"repo": repo, "base": base, "collected": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pulls": pulls, "identities": identities}


def matcher(identities: dict) -> Callable[[str], str | None]:
    """A function from a git name to the login it belongs to: the login itself, the names seen on commits and
    profiles, and the local parts of the e-mail addresses, all compared without case or punctuation."""
    keys: dict[str, set[str]] = {}
    for login, ident in identities.items():
        ks = {norm(login)} | {norm(n) for n in ident.get("names", [])}
        for email in ident.get("emails", []):
            m = NOREPLY.match(email or "")
            ks.add(norm(m.group(1)) if m else norm((email or "").split("@")[0]))
        keys[login] = {k for k in ks if len(k) >= 3}

    def match(name: str) -> str | None:
        n = norm(name)
        return next((login for login, ks in keys.items() if n in ks), None)

    return match


# --- score ---------------------------------------------------------------------------------------------------------


def _top(counts: Counter, match: Callable[[str], str | None], authors: set[str], k: int) -> list[str]:
    out: list[str] = []
    for name, _ in counts.most_common(k * 4):
        login = match(name)
        if login and login not in authors and login not in out:
            out.append(login)
        if len(out) == k:
            break
    return out


def score_pull(wt: Path, cfg: config.Config, pr: dict, match: Callable[[str], str | None], k: int = K) -> dict:
    """One pull request: triage at its base with the clock at its merge, the two git baselines, and who reviewed."""
    now = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")).timestamp()
    authors = {pr["author"]} | {c["login"] for c in pr.get("commit_authors", []) if c.get("login")}
    actual = sorted({r["login"] for r in pr.get("reviews", []) if r["state"] in STATES and r["login"] not in authors and not BOT.search(r["login"])})
    requested = sorted({u for u in pr.get("requested", []) if u not in authors and not BOT.search(u)})
    t = triage.compute(wt, cfg, since=pr["base"], now=now)
    offered = [(r["name"], match(r["name"])) for r in t["reviewers"][:k]]
    changed = [f["path"] for f in t["files"]]
    busy = Counter(n for n in _git(wt, "log", "--format=%aN", f"--since={int(now) - 90 * 86400}", f"--until={int(now)}", pr["base"]).splitlines() if n and not BOT.search(n))
    touched: Counter = Counter()
    if changed:
        touched = Counter(n for n in _git(wt, "log", "--format=%aN", f"--since={int(now) - 365 * 86400}", f"--until={int(now)}", pr["base"], "--", *changed[:200]).splitlines() if n and not BOT.search(n))
    return {
        "number": pr["number"], "merged_at": pr["merged_at"], "files": len(changed), "lines": sum(f["lines"] for f in t["files"]),
        "actual": actual, "requested": requested, "authors": sorted(authors),
        "tessri": [login for _, login in offered if login], "tessri_names": [name for name, _ in offered], "unmatched": [name for name, login in offered if not login],
        "recent": _top(touched, match, authors, k), "usual": _top(busy, match, authors, k),
        "no_active_owner": sum(1 for f in t["files"] if f.get("ownership") == "no-active-owner"),
    }


def gatekeepers(rows: list[dict], k: int = K, min_past: int = MIN_PAST) -> None:
    """Fill each row's `gatekeepers`: the people who reviewed most often among the pull requests merged before it
    (rows are newest first), the authors apart, once that history holds `min_past` review slots."""
    for i, row in enumerate(rows):
        past = Counter(login for older in rows[i + 1 :] for login in older["actual"])
        row["gatekeepers"] = [] if sum(past.values()) < min_past else [login for login, _ in past.most_common(k * 4) if login not in set(row["authors"])][:k]


def metrics(rows: list[dict], key: str, truth: str = "actual", k: int = K) -> dict:
    judged = [r for r in rows if r[truth] and r["files"] > 0]
    offered = [r for r in judged if r[key]]
    p = rc = h1 = any_hit = 0.0
    for r in offered:
        s = r[key][:k]
        hit = [x for x in s if x in r[truth]]
        p += len(hit) / len(s)
        rc += len(hit) / len(r[truth])
        h1 += 1.0 if s[0] in r[truth] else 0.0
        any_hit += 1.0 if hit else 0.0
    n = len(offered)
    return {"method": key, "judged": len(judged), "offered": n, "precision": round(p / n, 3) if n else None, "recall": round(rc / n, 3) if n else None, "hit_at_1": round(h1 / n, 3) if n else None, "any_hit": round(any_hit / n, 3) if n else None}


def score(data: dict, root: Path, k: int = K, limit: int | None = None, log=None) -> dict:
    """Every pull request scored, the methods compared, and what the comparison rests on."""
    pulls = data["pulls"][:limit] if limit else data["pulls"]
    if not pulls:
        raise ReviewerMatchError("nothing to score: the collected file holds no pull request")
    match = matcher(data.get("identities", {}))
    rows: list[dict] = []
    errors: list[dict] = []
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="tessri-reviewers-") as tmp:
        wt = Path(tmp) / "worktree"
        made = subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", str(wt), pulls[0]["merge"]], capture_output=True, text=True)
        if made.returncode != 0:
            raise ReviewerMatchError(f"cannot make a worktree of {root}: {made.stderr.strip()}")
        try:
            cfg = config.load(wt)
            for i, pr in enumerate(pulls):
                moved = subprocess.run(["git", "-C", str(wt), "checkout", "-q", "--detach", pr["merge"]], capture_output=True, text=True)
                if moved.returncode != 0:
                    errors.append({"number": pr["number"], "error": moved.stderr.strip()[:200]})
                    continue
                try:
                    rows.append(score_pull(wt, cfg, pr, match, k))
                except (triage.TriageError, config.ConfigError, OSError) as exc:
                    errors.append({"number": pr["number"], "error": str(exc)[:200]})
                if log and i % 10 == 0:
                    log(f"{i + 1} of {len(pulls)} scored, {time.time() - started:.0f}s")
        finally:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)], capture_output=True)
            subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)
    gatekeepers(rows, k)
    judged = [r for r in rows if r["actual"] and r["files"] > 0]
    slots = Counter(login for r in judged for login in r["actual"])
    total = sum(slots.values())
    top3 = {login for login, _ in slots.most_common(3)}
    both = sum(1 for r in judged if set(r["tessri"][:k]) & set(r["actual"]) and set(r["recent"][:k]) & set(r["actual"]))
    tessri_only = sum(1 for r in judged if set(r["tessri"][:k]) & set(r["actual"]) and not set(r["recent"][:k]) & set(r["actual"]))
    recent_only = sum(1 for r in judged if set(r["recent"][:k]) & set(r["actual"]) and not set(r["tessri"][:k]) & set(r["actual"]))
    unmatched = Counter(n for r in rows for n in r["unmatched"])
    return {
        "repo": data["repo"], "base": data.get("base", "main"), "collected": data.get("collected"), "k": k,
        "pulls": {"count": len(pulls), "scored": len(rows), "errors": errors, "reviewed": sum(1 for r in rows if r["actual"]), "no_code": sum(1 for r in rows if r["files"] == 0), "judged": len(judged),
                  "first": min(p["merged_at"] for p in pulls)[:10], "last": max(p["merged_at"] for p in pulls)[:10],
                  "reviewers_per_pull": round(sum(len(r["actual"]) for r in rows) / len(rows), 2) if rows else None},
        "reviewers": {"distinct": len(slots), "top": [{"login": login, "share": round(n / total, 3)} for login, n in slots.most_common(5)] if total else [],
                      "only_top3_share": round(sum(1 for r in judged if set(r["actual"]) <= top3) / len(judged), 3) if judged else None},
        "methods": [dict(metrics(rows, key, "actual", k), label=label) for key, label in METHODS],
        "requested": [dict(metrics(rows, key, "requested", k), label=label) for key, label in METHODS[:3]],
        "overlap": {"both": both, "tessri_only": tessri_only, "recent_only": recent_only, "neither": len(judged) - both - tessri_only - recent_only},
        "unmatched": {"offers": sum(unmatched.values()), "names": len(unmatched), "most": [{"name": n, "offers": c} for n, c in unmatched.most_common(10)]},
        "rows": rows,
    }


# --- output --------------------------------------------------------------------------------------------------------


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _table(head: list[str], body: list[list[str]], right: set[int]) -> str:
    widths = [max(len(row[i]) for row in [head, *body]) for i in range(len(head))]
    lines = []
    for row in [head, *body]:
        cells = [c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(row)]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def text(result: dict) -> str:
    p, rv = result["pulls"], result["reviewers"]
    out = [
        f"Tessri reviewer match on {result['repo']} ({p['count']:,} merged pull requests, {p['first']} to {p['last']})",
        "",
        textwrap.fill(
            f"{p['scored']:,} scored; {p['reviewed']:,} had a reviewer other than the authors (bots and service accounts apart), "
            f"{p['reviewers_per_pull']} per pull request; {p['no_code']:,} changed no code file and are left out, so {p['judged']:,} are judged. "
            f"A method offers up to {result['k']} people, the authors apart, and is judged where it offers anyone.",
            WIDTH,
        ),
        "",
        _table(
            ["Method", "offered on", "precision", "recall", "hit@1", "any hit"],
            [[m["label"], f"{m['offered']} of {m['judged']}", _num(m["precision"]), _num(m["recall"]), _num(m["hit_at_1"]), _num(m["any_hit"])] for m in result["methods"]],
            {1, 2, 3, 4, 5},
        ),
    ]
    if rv["top"]:
        two = " and ".join(f"{t['share']:.0%}" for t in rv["top"][:2])
        out += ["", textwrap.fill(
            f"Who reviews: {rv['distinct']} people took a review slot; the two most frequent took {two} of the slots, "
            f"and {rv['only_top3_share']:.0%} of the judged pull requests were reviewed only by the three most frequent. "
            f"Where git names the people behind the changed files, triage and the plain committer count hit on different pull requests: "
            f"both {result['overlap']['both']}, triage only {result['overlap']['tessri_only']}, committers only {result['overlap']['recent_only']}, neither {result['overlap']['neither']}.",
            WIDTH,
        )]
    out += ["", "Against the reviewers GitHub had requested (not yet reviewed when read; a weaker truth):", "",
            _table(["Method", "offered on", "precision", "recall"], [[m["label"], f"{m['offered']} of {m['judged']}", _num(m["precision"]), _num(m["recall"])] for m in result["requested"]], {1, 2, 3})]
    un = result["unmatched"]
    if un["offers"]:
        out += ["", f"Of triage's offers, {un['offers']} ({un['names']} distinct name{'s' if un['names'] != 1 else ''}) matched no login and were dropped; the JSON names them."]
    if p["errors"]:
        out += ["", f"{len(p['errors'])} pull request{'s' if len(p['errors']) != 1 else ''} could not be scored: " + "; ".join(f"#{e['number']}: {e['error']}" for e in p["errors"][:3]) + "."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test `triage`'s \"who can look\" against who reviewed, on a repository's merged pull requests.")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="read the merged pull requests, reviews and identities through gh")
    c.add_argument("repo", help="owner/name on GitHub")
    c.add_argument("path", help="a checkout that holds the merge commits")
    c.add_argument("--limit", type=int, default=300, help="how many of the newest merged pull requests (default 300)")
    c.add_argument("--base", default="main", help="the branch the pull requests were merged into (default main)")
    c.add_argument("--out", required=True, help="where to write the collected JSON")
    s = sub.add_parser("score", help="score the collected pull requests offline")
    s.add_argument("pulls", help="the JSON `collect` wrote")
    s.add_argument("path", help="the same checkout")
    s.add_argument("--limit", type=int, help="score only the newest N")
    s.add_argument("--k", type=int, default=K, help=f"names a method offers (default {K}, like triage)")
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.add_argument("--out", help="write here instead of stdout")
    args = parser.parse_args(argv)
    log = lambda line: print(line, file=sys.stderr)  # noqa: E731
    try:
        if args.command == "collect":
            data = collect(args.repo, Path(args.path), args.limit, args.base, log=log)
            Path(args.out).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            print(f"{len(data['pulls'])} pull requests and {len(data['identities'])} identities written to {args.out}", file=sys.stderr)
            return 0
        data = json.loads(Path(args.pulls).read_text(encoding="utf-8"))
        result = score(data, Path(args.path), args.k, args.limit, log=log)
    except (ReviewerMatchError, config.ConfigError, OSError, ValueError) as exc:
        print(f"reviewer_match: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2) + "\n" if args.format == "json" else text(result)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
