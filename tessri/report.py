"""Build the JSON report. This dict is the tool's public interface: see SCHEMA_VERSION in model.py."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from . import __version__, meta, review
from .analyze import Analysis
from .model import SCHEMA_VERSION, STATUSES
from .ownership import LISTED_OWNERS, UNKNOWN, UNOWNED, bus_factor, owner_rows, rollup

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _dir_key(path: str, depth: int) -> str:
    return "/".join(path.split("/")[:-1][:depth]) or "."


def _ownership_section(a: Analysis, code_recs: list) -> dict:
    """Who maintains the code, who is gone, and what CODEOWNERS says. Names only: emails never leave the tool."""
    own = a.ownership
    if own is None:
        return {"available": False}
    top = a.cfg.top
    live = [r for r in code_recs if r.code > 0]
    area = rollup(own, ((r.path, r.code) for r in live))
    unowned = [r for r in live if r.ownership == UNOWNED]
    unowned_code = sum(r.code for r in unowned)
    needs = sorted((r for r in unowned if r.status != "ORPHAN"), key=lambda r: (-r.code, r.path))
    ranked = sorted(area.lines.items(), key=lambda kv: (-kv[1], own.authors[kv[0]].name))
    section: dict = {
        "available": True,
        "inactive_days": own.inactive_days,
        "authors": {"total": len(own.authors), "active": sum(own.is_active(who) for who in own.authors)},
        "bus_factor": bus_factor(area),
        "no_active_owner": {"files": len(unowned), "code": unowned_code, "share": _pct(unowned_code, area.code)},
        "unattributed": {"files": sum(r.ownership == UNKNOWN for r in live), "code": area.unattributed},
        "top_authors": [
            {
                "name": own.authors[who].name,
                "code": round(lines),
                "share": _pct(round(lines), area.code),
                "last_commit": _day(own.authors[who].last),
                "idle_days": own.idle_days(who),
                "active": own.is_active(who),
            }
            for who, lines in ranked[:top]
        ],
        "needs_owner_files": [
            {"path": r.path, "code": r.code, "status": r.status, "last_commit": r.last_commit, "last_owner": r.owner, "owner_idle_days": r.owner_idle_days}
            for r in needs[:top]
        ],
        "codeowners": None,
    }
    if own.codeowners:
        uncovered = [r for r in live if not r.declared_owners]
        differs = sorted((r for r in live if r.declared_match is False), key=lambda r: (-r.code, r.path))
        section["codeowners"] = {
            "file": own.codeowners,
            "rules": own.rules,
            "uncovered": {"files": len(uncovered), "code": sum(r.code for r in uncovered), "share": _pct(sum(r.code for r in uncovered), sum(r.code for r in live))},
            "differs": {"files": len(differs), "code": sum(r.code for r in differs)},
            "uncovered_files": [{"path": r.path, "code": r.code, "owner": r.owner} for r in sorted(uncovered, key=lambda r: (-r.code, r.path))[:top]],
            "differing_files": [{"path": r.path, "code": r.code, "declared": (r.declared_owners or [])[:LISTED_OWNERS], "observed": r.owner} for r in differs[:top]],
        }
    return section


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def build_report(a: Analysis, full: bool = False) -> dict:
    recs = list(a.records.values())
    code_recs = [r for r in recs if r.kind == "code"]
    top = a.cfg.top

    languages: dict[tuple[str, str], dict] = {}
    for r in recs:
        row = languages.setdefault(
            (r.language, r.kind),
            {"language": r.language, "kind": r.kind, "files": 0, "code": 0, "comment": 0, "blank": 0, "reachability": r.analyzer},
        )
        row["files"] += 1
        row["code"] += r.code
        row["comment"] += r.comment
        row["blank"] += r.blank

    by_status = {s: {"files": 0, "code": 0} for s in STATUSES}
    for r in code_recs:
        if r.status:
            slot = by_status.setdefault(r.status, {"files": 0, "code": 0})
            slot["files"] += 1
            slot["code"] += r.code

    analyzed_code = sum(r.code for r in code_recs if r.reachability is not None and not r.is_test)
    orphans = [r for r in code_recs if r.status == "ORPHAN"]
    test_only = [r for r in code_recs if r.reachability == "test" and not r.is_test]

    directories: dict[str, dict] = {}
    dir_files: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in code_recs:
        key = _dir_key(r.path, a.cfg.depth)
        row = directories.setdefault(key, {"path": key, "files": 0, "code": 0, **{s.lower(): 0 for s in STATUSES}})
        row["files"] += 1
        row["code"] += r.code
        if r.status in STATUSES:
            row[r.status.lower()] += r.code
        dir_files[key].append((r.path, r.code))
    if a.ownership is not None:
        for key, row in directories.items():
            area = rollup(a.ownership, dir_files[key])
            row["owners"] = owner_rows(area.owners)
            row["contributors"] = sum(lines * 100 >= area.code for lines in area.lines.values())  # people with at least 1% of the code
            row["ownership"] = area.state
            row["no_active_owner_code"] = sum(c for p, c in dir_files[key] if a.records[p].ownership == UNOWNED)

    unanalyzed = defaultdict(lambda: {"files": 0, "code": 0})
    for r in code_recs:
        if r.analyzer is None and r.language != "Python stub":
            unanalyzed[r.language]["files"] += 1
            unanalyzed[r.language]["code"] += r.code

    roots = Counter(why.split(":")[0] for r in recs for why in r.roots)

    caveats = [
        "Reachability is static. Dynamic dispatch, plugin discovery and consumers outside this repository are invisible: "
        "treat ORPHAN as a candidate, and run `tessri why <file>` before deleting anything.",
        "If this repository is a library, public modules that nothing inside it imports look orphaned. "
        "List them under `keep` in .tessri.toml.",
    ]
    if a.activity is None:
        caveats.append("No git history was available, so activity statuses are UNKNOWN.")
    else:
        if a.activity.shallow:
            caveats.append("The git clone is shallow: activity and ownership cover only the fetched history.")
        caveats.append(
            "Ownership is inferred from git commit authors (recent commits weigh more; `.mailmap` merges identities). "
            f"It shows who has been changing the code, not who is accountable, and an owner counts as gone after {a.cfg.owner_inactive_days} days without a commit anywhere in the repository."
        )
    if unanalyzed:
        caveats.append("No reachability analyzer for: " + ", ".join(sorted(unanalyzed)) + ". Those files only get volume and activity.")
    if a.graph.ambiguous:
        shared = sorted(a.graph.ambiguous.items(), key=lambda kv: (-kv[1], kv[0]))
        listed = ", ".join(f"`{name}` ({n})" for name, n in shared[:5]) + (f" and {len(shared) - 5} more" if len(shared) > 5 else "")
        caveats.append(
            f"{len(shared)} name{'s' if len(shared) != 1 else ''} in configs, scripts or code fit{'s' if len(shared) == 1 else ''} several files each and "
            f"so name{'s' if len(shared) == 1 else ''} none of them: {listed}. Give such a reference a directory, or list the files under `entry`."
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "tessri", "version": __version__},
        "generated_at": datetime.fromtimestamp(a.now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {"name": a.root.name},
        "kind": "scan",
        "meta": meta.of(a),
        "git": {
            "available": a.activity is not None,
            "head": a.activity.head if a.activity else None,
            "shallow": a.activity.shallow if a.activity else None,
            "commits": a.activity.commits if a.activity else None,
        },
        "settings": {
            "active_days": a.cfg.active_days,
            "dormant_days": a.cfg.dormant_days,
            "owner_inactive_days": a.cfg.owner_inactive_days,
            "review_days": a.cfg.review_days,
            "ignore_authors": a.cfg.ignore_authors,
            "keep": a.cfg.keep,
            "exclude": a.cfg.exclude,
            "entry": a.cfg.entry,
        },
        "summary": {
            "files": len(recs),
            "code_lines": sum(r.code for r in code_recs),
            "by_status": by_status,
            "orphans": {"files": len(orphans), "code": sum(r.code for r in orphans), "share_of_analyzed": _pct(sum(r.code for r in orphans), analyzed_code)},
            "test_only": {"files": len(test_only), "code": sum(r.code for r in test_only)},
            "reachability_coverage": {
                "analyzers": a.analyzers,
                "analyzed_code": analyzed_code,
                "share_of_code": _pct(analyzed_code, sum(r.code for r in code_recs if not r.is_test)),
            },
        },
        "languages": sorted(languages.values(), key=lambda row: -row["code"]),
        "directories": sorted(directories.values(), key=lambda row: -row["code"]),
        "ownership": _ownership_section(a, code_recs),
        "review": review.section(a),
        "largest_files": [
            {"path": r.path, "language": r.language, "code": r.code, "status": r.status}
            for r in sorted(code_recs, key=lambda r: -r.code)[:top]
        ],
        "hotspots": [
            {"path": r.path, "commits_year": r.commits_year, "authors_year": r.authors_year, "fixes_year": r.fixes_year, "code": r.code, "last_commit": r.last_commit, "status": r.status, "owner": r.owner}
            for r in sorted((r for r in code_recs if r.commits_year), key=lambda r: (-r.commits_year, -r.code))[:top]
        ],
        "cleanup": {
            "orphan_files": [
                {
                    "path": r.path,
                    "language": r.language,
                    "code": r.code,
                    "confidence": r.confidence,
                    "last_commit": r.last_commit,
                    "commits_year": r.commits_year,
                    "owner": r.owner,
                    "owner_idle_days": r.owner_idle_days,
                    "notes": r.notes,
                }
                for r in sorted(orphans, key=lambda r: (_CONFIDENCE_RANK.get(r.confidence or "low", 2), -r.code, r.path))
            ],
            "test_only_files": [
                {"path": r.path, "code": r.code, "last_commit": r.last_commit}
                for r in sorted(test_only, key=lambda r: (-r.code, r.path))
            ],
        },
        "analysis": {
            "roots": dict(sorted(roots.items())),
            "unanalyzed_languages": {k: v for k, v in sorted(unanalyzed.items())},
            "unparsed_files": a.unparsed,
            "skipped": a.skipped,
        },
        "caveats": caveats,
    }
    if full:
        report["files"] = [asdict(r) for r in sorted(recs, key=lambda r: r.path)]
    return report
