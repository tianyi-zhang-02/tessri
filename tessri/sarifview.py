"""`tessri check --format sarif`: the change check as a SARIF 2.1.0 log, for tools that already read that format.

This is a rendering of the finished check result, nothing more: one finding becomes one result in the same order,
with the whole finding kept in a namespaced property bag, so the aggregate meaning of a finding ("4 files nothing
reaches") is not split into four look-alike alerts. The evidence is file-level, so locations name files and never a
line; a finding without a usable file has no location rather than an invented one. Nothing is read from the
repository: paths come from the check result, and a path that is deleted, absolute or climbs out of the root is
left out of the locations (it stays in the properties).

Some consumers refuse a result without a location (GitHub code scanning rejects the whole log). `locationless="omit"`
takes those results out of `results` for such a consumer, but only on request: the default keeps them, and an omitted
finding is not dropped from the document, it moves whole into the run's `properties["tessri/locationless"]`, where
the count of location-free findings is recorded either way. The gate (`--fail-on`) counts findings, not results, so
omitting changes what a consumer displays and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from . import __version__

SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
VERSION = "2.1.0"
ROOT_ID = "TESSRI_ROOT"  # the uriBaseId every location refers to; originalUriBaseIds says which directory it is
INFORMATIONAL = ("new-dependency", "orphan-resolved", "cycle-resolved")  # observations, not failures: kind informational, level none
LEVEL = {"block": "error", "warn": "warning", "info": "note"}
LOCATIONLESS = ("keep", "omit")  # what becomes of a finding with no usable file: a result without a location, or a property entry

# One descriptor per finding kind. Written for any repository: no path, count or commit of a particular run.
RULES = (
    ("new-orphan", "Files the change left unreachable", "New files that no entry point, test or config reference reaches, or files the change cut the last way to reach. As far as the static analysis can tell, they are dead."),
    ("dangling-import", "A deleted file is still imported", "The change deleted a file that files it did not touch still import. Restore the file or update the importers."),
    ("dangling-reference", "A deleted file is still named", "The change deleted or moved a file that files it did not touch still name: a config or a script (wiring that now points at nothing), a string or a dynamic import in code (a guess that the file is loaded at run time: check it), or only documentation (then a note). Update the name in the same change or restore the file."),
    ("new-cycle", "A new dependency cycle between modules", "The change made a set of modules depend on each other, so they can no longer be understood or released alone. The finding names the dependency that closed the loop."),
    ("cycle-grew", "An existing dependency cycle grew", "The change drew more modules into a cycle that already existed."),
    ("new-dependency", "New dependencies between modules", "Modules that now import modules they did not import before. An observation to read, not a failure."),
    ("no-active-owner", "Changed code nobody active maintains", "The change touches files whose maintainers have all gone quiet. A person decides who looks; do not pick a reviewer from the file's last maintainers."),
    ("orphan-resolved", "Orphan files resolved", "Files that nothing reached before the change are now reached or removed. An observation, not proof that no orphan remains."),
    ("cycle-resolved", "A dependency cycle resolved", "Modules that depended on each other before the change no longer do. An observation, not proof that no cycle remains."),
)
RULE_INDEX = {kind: i for i, (kind, _, _) in enumerate(RULES)}


_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")  # C:/... or C:\...: a Windows drive, not a relative name


def _safe(rel: str) -> bool:
    """A root-relative posix path the report may name: nothing absolute, nothing that climbs out, no Windows drive.
    On POSIX a literal backslash or colon is part of a file name (`a:valid.py` is a legitimate relative path, encoded
    as `a%3Avalid.py`), so only a drive letter followed by a separator counts as absolute."""
    if not rel or "\x00" in rel or rel.startswith("/") or _DRIVE.match(rel):
        return False
    return ".." not in PurePosixPath(rel).parts


def _location(rel: str) -> dict:
    return {"physicalLocation": {"artifactLocation": {"uri": quote(rel, safe="/"), "uriBaseId": ROOT_ID}}}


def _message(f: dict) -> str:
    text = f"{f['title']}. {f['detail']}".rstrip()
    if f.get("action"):
        text += f" Do: {f['action']}"
    if f.get("needs_human"):
        text += " A person has to decide this."
    return text


def _result(f: dict, deleted: set[str]) -> dict:
    kind = f["kind"]
    informational = kind in INFORMATIONAL
    out = {
        "ruleId": f"tessri/{kind}",
        "ruleIndex": RULE_INDEX[kind],
        "kind": "informational" if informational else "fail",
        "level": "none" if informational else LEVEL[f["severity"]],
        "message": {"text": _message(f)},
    }
    usable = []
    for rel in f.get("files", []):
        if rel not in usable and rel not in deleted and _safe(rel):
            usable.append(rel)
    if usable:
        out["locations"] = [_location(usable[0])]
        if len(usable) > 1:
            out["relatedLocations"] = [{"id": i, "message": {"text": "also part of this finding"}, **_location(rel)} for i, rel in enumerate(usable[1:], 1)]
    out["properties"] = {"tessri/finding": f}
    return out


def sarif(result: dict, root: Path, locationless: str = "keep") -> dict:
    """The SARIF log for one `since.check` result analysed at `root` (the directory the paths are relative to).

    `locationless` is "keep" (every finding is a result, with or without a location) or "omit" (findings without a
    location leave `results` and are kept whole under `run.properties["tessri/locationless"]["omitted"]`)."""
    if locationless not in LOCATIONLESS:
        raise ValueError(f"locationless must be one of {', '.join(LOCATIONLESS)}, not {locationless!r}")
    deleted = {row["path"] for row in result.get("changed_files", []) if row.get("change") == "deleted"}
    results = [_result(f, deleted) for f in result.get("findings", [])]
    without = [r for r in results if "locations" not in r]
    if locationless == "omit":
        results = [r for r in results if "locations" in r]
    run = {
        "tool": {
            "driver": {
                "name": "tessri",
                "version": __version__,
                "informationUri": "https://github.com/tianyi-zhang-02/tessri",
                "rules": [
                    {
                        "id": f"tessri/{kind}",
                        "shortDescription": {"text": short},
                        "fullDescription": {"text": full},
                        "defaultConfiguration": {"level": "none" if kind in INFORMATIONAL else {"dangling-import": "error", "new-dependency": "note"}.get(kind, "warning")},
                    }
                    for kind, short, full in RULES
                ],
            }
        },
        "originalUriBaseIds": {ROOT_ID: {"uri": Path(root).resolve().as_uri() + "/"}},
        "results": results,
        "properties": {
            "tessri/check": {key: result.get(key) for key in ("schema_version", "kind", "meta", "change", "summary", "notes")},
            "tessri/locationless": {
                "policy": locationless,
                "count": len(without),
                "omitted": [r["properties"]["tessri/finding"] for r in without] if locationless == "omit" else [],
            },
        },
    }
    return {"$schema": SCHEMA, "version": VERSION, "runs": [run]}
