"""A self-contained, offline HTML view of the existing brief object. No analysis or scripts run in this view."""

from __future__ import annotations

import html
import json
import re

from . import brief, triage

STYLE = """
:root{color-scheme:light dark;--bg:#f8f8f6;--paper:#fff;--ink:#23242a;--body:#555763;--line:#dddde4;--accent:#5a46c2;--soft:#f1eef8;--block:#96313c;--warn:#805419}
@media(prefers-color-scheme:dark){:root{--bg:#15151a;--paper:#1e1e25;--ink:#ededf2;--body:#bdbdc9;--line:#3c3b49;--accent:#bdadff;--soft:#292534;--block:#f3a5af;--warn:#e6c28b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,sans-serif}a{color:var(--accent)}a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.wrap{width:min(1160px,calc(100% - 48px));margin:auto}.skip{position:absolute;left:16px;top:-80px}.skip:focus{top:16px;background:var(--paper);padding:12px}header{display:flex;justify-content:space-between;gap:24px;padding:24px 0;border-bottom:1px solid var(--line)}.brand{font-size:24px;font-weight:650;letter-spacing:-1px}.brand span{color:var(--accent)}nav{display:flex;flex-wrap:wrap;align-items:center;gap:20px;font-size:14px}h1,h2,h3,p{margin:0}h1{font:400 clamp(36px,5vw,58px)/1.1 Georgia,serif;letter-spacing:-.025em;margin:36px 0 14px}h2{font-size:21px;font-weight:550}h3{font-size:17px;font-weight:550}code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}code{font-size:.88em;overflow-wrap:anywhere}.scope{padding:16px 20px;border:1px solid var(--line);border-radius:5px;background:var(--soft);margin:24px 0}.muted,.hint{color:var(--body);font-size:14px}.stats{display:flex;flex-wrap:wrap;gap:12px 28px;margin:22px 0;font-size:15px}.stats b{font-size:22px;font-weight:550;margin-right:5px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start}.panel{background:var(--paper);border:1px solid var(--line);border-radius:7px;margin-bottom:24px;overflow:hidden}.panel-head{padding:20px 22px;border-bottom:1px solid var(--line)}.panel-head p{margin-top:6px}.inside{padding:20px 22px}.file,.finding{padding:18px 22px;border-bottom:1px solid var(--line)}.file:last-child,.finding:last-child{border-bottom:0}.file-head{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.file-head code{font-size:15px}.file p,.finding p{margin-top:9px;font-size:14px}.badge{font-size:12px;letter-spacing:.03em;text-transform:uppercase;font-weight:600}.block{color:var(--block)}.warn{color:var(--warn)}details{margin-top:14px}summary{cursor:pointer;color:var(--accent);font-size:14px}details p{margin:10px 0}.more{padding:16px 22px;margin:0;border-top:1px solid var(--line)}.more .file{padding-left:0;padding-right:0}ul{padding-left:22px;margin:12px 0}li{margin:8px 0;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--soft);border-radius:4px;padding:16px;font-size:13px;line-height:1.6}.status{padding:12px 0;border-bottom:1px solid var(--line);font-size:14px}.status:last-child{border:0}.status strong{font-weight:550}.notice{border-left:3px solid var(--warn);padding:12px 16px;background:var(--soft);margin-top:18px;font-size:14px}.full{padding:20px 22px}.full>summary{font-size:16px}footer{padding:8px 0 30px;color:var(--body);font-size:13px}.empty{padding:20px 22px;font-size:14px;color:var(--body)}
@media(max-width:720px){.wrap{width:calc(100% - 32px)}.grid{grid-template-columns:1fr;gap:0}header{align-items:start}nav{gap:10px 14px;justify-content:flex-end;max-width:230px}.panel-head,.inside,.file,.finding{padding:18px}.stats{gap:12px 20px}.scope{padding:14px}h1{margin-top:28px}.full,.more{padding:18px}}
@media print{body{background:white;color:black}.wrap{width:100%}header nav,.skip{display:none}.grid{display:block}.panel{break-inside:avoid}details:not([open])>summary:after{content:" (expand before printing to include the evidence)"}}
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _text(value: str) -> str:
    """Only backtick spans are markup; all repository-controlled text is escaped."""
    return "".join(f"<code>{_e(part)}</code>" if i % 2 else _e(part) for i, part in enumerate(re.split(r"`([^`]+)`", value)))


def _paths(paths: list[str]) -> str:
    return "<ul>" + "".join(f"<li><code>{_e(p)}</code></li>" for p in paths) + "</ul>"


def _panel(title: str, body: str, ident: str, hint: str = "") -> str:
    return f'<section class="panel" id="{ident}"><div class="panel-head"><h2>{title}</h2>' + (f'<p class="hint">{hint}</p>' if hint else "") + "</div>" + body + "</section>"


def _file(row: dict, attention: dict) -> str:
    owners = ", ".join(f"{o['name']} {o['share']:.0f}%" for o in row["owners"]) or "None recorded"
    extra = {"path": row["path"], "rank": row["rank"], "owners": row["owners"], "symbols": row.get("symbols"), "flags": row["flags"]}
    definitions = row.get("symbols") or {}
    named = ""
    if definitions.get("available"):
        for kind in ("added", "changed", "removed"):
            if definitions.get(kind):
                named += "<p>" + kind.capitalize() + " definitions: " + ", ".join("<code>" + _e(name) + "</code>" for name in definitions[kind]) + ".</p>"
        if definitions.get("module_level"):
            named += "<p>Also touches module-level code.</p>"
    else:
        named = "<p>Definition analysis unavailable: " + _e(definitions.get("reason", "no definition evidence")) + ".</p>"
    return (
        '<article class="file"><div class="file-head"><code>' + _e(row["path"]) + "</code>"
        + f'<span>+{row["added"]} −{row["deleted"]}</span></div>'
        + "<p>" + _e(triage._why(row, attention["window_days"])) + "</p>"
        + ("<p>" + _e("; ".join(row["flags"])) + "</p>" if row["flags"] else "")
        + "<details><summary>Why this file? Owners and changed definitions</summary>"
        + "<p>History at the base: " + _e(owners) + ".</p>"
        + named + "<details><summary>File evidence JSON</summary><pre>" + _e(json.dumps(extra, ensure_ascii=False, indent=2)) + "</pre></details></details></article>"
    )


def render(b: dict, *, example: bool = False) -> str:
    """Render the JSON-ready result without changing its facts or rereading the repository."""
    c, a, q, v, people = (b[k] for k in ("change", "attention", "consequences", "validation", "people"))
    all_files = b["triage"]["files"]
    shown = len(a["files"])
    files = "".join(_file(row, a) for row in a["files"])
    if len(all_files) > shown:
        files += f'<details class="more"><summary>{len(all_files) - shown} more changed files, in order ({len(all_files)} total)</summary>' + "".join(_file(row, a) for row in all_files[shown:]) + "</details>"
    if not all_files:
        files = '<p class="empty">No code changed, so there is nothing to rank. Other changed paths remain in the full evidence.</p>'
    files = _panel("Look first", files, "look-first", f"Showing {shown} of {a['total']} files. Recent activity, then change size; expand a file to inspect its evidence.")
    findings = ""
    for f in q["findings"]:
        findings += (
            '<article class="finding"><span class="badge ' + _e(f["severity"]) + '">' + _e(f["severity"]) + " · " + _e(f["kind"]) + "</span>"
            + "<h3>" + _text(f["title"]) + "</h3><p>" + _text(f["detail"]) + "</p>"
            + ("<p><strong>Next check.</strong> " + _text(f["action"]) + "</p>" if f["action"] else "")
            + "<details><summary>Files and finding evidence</summary>" + _paths(f["files"])
            + "<pre>" + _e(json.dumps(f, ensure_ascii=False, indent=2)) + "</pre></details></article>"
        )
    if not findings:
        skipped = b["meta"]["analysis"]["structure"] == "skipped"
        findings = '<p class="empty">' + ("Nothing was compared: no code changed." if skipped else "No structural findings in the analyzed code. This is not proof that the change is safe.") + "</p>"
    ripple = q["ripple"]
    findings += f'<div class="inside"><p class="hint">Code outside the change: {ripple["direct"]} direct dependents; {ripple["second"]} through one more step.</p>'
    for group in q["not_analysed"]:
        findings += "<div class='notice'>Not analysed: " + _e(group["language"]) + ". Dependents, candidate tests and structure are unknown." + _paths(group["files"]) + "</div>"
    findings += "</div>"
    findings = _panel("What it did to the structure", findings, "structure")
    held, cover = v.get("report"), v.get("coverage")
    candidates = b["triage"]["tests"]["paths"]
    tests = f'<div class="inside"><p class="hint">{v["candidates"]["count"]} candidate test files. Paths, not executions.</p>'
    test_rows = ["<li><code>" + _e(p) + "</code>" + (" — " + _e(held["ran"].get(p, "not in the report")) if held else "") + "</li>" for p in candidates]
    tests += "<ul>" + "".join(test_rows[:brief.LISTED]) + "</ul>"
    if len(test_rows) > brief.LISTED:
        tests += f'<details><summary>{len(test_rows) - brief.LISTED} more candidate test files ({len(test_rows)} total)</summary><ul>' + "".join(test_rows[brief.LISTED:]) + "</ul></details>"
    if v["ran"]:
        tests += "<h3>Host-recorded checks</h3><ul>" + "".join("<li>" + _e(line) + "</li>" for line in v["ran"]) + "</ul>"
    if held:
        tests += f'<div class="status"><strong>JUnit report:</strong> {held["passed"]} candidate files passed; {len(held["failed"])} failed; {held["skipped"]} skipped; {len(held["not_run"])} not in the report.</div>'
        tests += "<details><summary>Test-report sources, results and unmatched cases</summary><pre>" + _e(json.dumps(held, ensure_ascii=False, indent=2)) + "</pre></details>"
    if cover:
        tests += "<p>" + _text(brief._coverage_line(cover)) + "</p><details><summary>Changed-line coverage and unmeasured files</summary><pre>" + _e(json.dumps(cover, ensure_ascii=False, indent=2)) + "</pre></details>"
    if not v["ran"] and held is None and cover is None:
        tests += '<p class="notice">No check was recorded as run. Supply a host note with --ran, a JUnit report with --report, or a coverage report with --coverage.</p>'
    else:
        tests += '<p class="notice"><strong>Code snapshot association: unknown.</strong> The host supplied these results; this brief does not verify that they belong to the current code. Tessri did not run the checks.</p>'
    tests += "</div>"
    tests = _panel("Validation", tests, "validation")
    who = "<div class='inside'>"
    who += "<p>" + (_e(triage.people(people["reviewers"])) if people["reviewers"] else "Nobody other than the authors maintains the changed files, as far as history shows.") + "</p>"
    who += "<p class='hint'>" + _e(triage.CAVEAT) + "</p>"
    if line := triage.regulars_line(people):
        who += "<p class='hint'>" + _text(line) + "</p>"
    who += "</div>"
    who = _panel("Who can look", who, "people")
    opened = "<ul>" + "".join("<li>" + _text(item["text"]) + _paths(item["files"]) + "</li>" for item in b["open"]) + "</ul>" if b["open"] else "<p>Nothing this analysis can name. The diff and intent still need a person.</p>"
    opened = _panel("Open for a person", "<div class='inside'>" + opened + "</div>", "open")
    scope = "<code>" + _e(c["since"]) + "</code> · base <code>" + _e(c["base"][:9]) + "</code> · HEAD <code>" + _e(c["head"][:9]) + "</code>"
    if c["uncommitted"]:
        scope += f"<p>Includes {brief._many(len(c['uncommitted_files']), 'uncommitted file')}. HEAD does not identify their contents.</p>"
    scope += f"<p>{c['added']} added · {c['modified']} modified · {c.get('moved', 0)} moved · {c['deleted']} deleted code files; {c['other_files']} other files ({c['other_lines']} lines).</p>"
    scope += '<details><summary>Exact state and working-tree paths</summary><p>Base: <code>' + _e(c["base"]) + '</code><br>HEAD: <code>' + _e(c["head"]) + '</code></p>' + _paths(c["uncommitted_files"]) + '</details>'
    if c["commits"]:
        scope += "<details><summary>Commits, in the authors’ words</summary><ul>" + "".join("<li><code>" + _e(k["id"]) + "</code> " + _e(k["subject"]) + " (" + _e(k["author"]) + ")</li>" for k in c["commits"]) + "</ul></details>"
    notes = "<ul>" + "".join("<li>" + _text(n) + "</li>" for n in b["notes"]) + "</ul>"
    notes += '<p class="hint">The full evidence below retains all triage and check data, even when a list is shortened above. No scripts, network requests, or repository changes are made by this page.</p>'
    raw = _e(json.dumps(b, ensure_ascii=False, indent=2))
    example_note = '<p class="notice"><strong>Worked example.</strong> This is a generated teaching repository, not a production incident. The host check was run in that fixture.</p><p class="muted"><a href="../">Tessri home</a> · <a href="brief.json">Example JSON</a></p>' if example else ""
    counts = " · ".join(f"{q['counts'][severity]} {severity}" for severity in ("block", "warn", "info") if q["counts"][severity]) or "No findings"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        + "<title>Review brief: " + _e(b["repo"]["name"]) + "</title><style>" + STYLE + "</style></head><body>"
        + '<a class="skip" href="#main">Skip to content</a><div class="wrap"><header><div class="brand">tessri<span>.</span></div>'
        + '<nav aria-label="Review brief"><a href="#look-first">Look first</a><a href="#structure">Structure</a><a href="#validation">Validation</a><a href="#evidence">Full evidence</a></nav></header>'
        + '<main id="main"><h1>Review brief: ' + _e(b["repo"]["name"]) + '</h1><p class="muted">A change, with the context to review it.</p>' + example_note
        + '<div class="scope">' + scope + "</div>"
        + f'<div class="stats"><span><b>{c["code_files"]}</b> code files</span><span><b>{c["lines"]}</b> lines</span><span>{counts}</span></div>'
        + '<div class="grid"><div>' + files + who + "</div><div>" + findings + tests + "</div></div>" + opened
        + _panel("Read this with care", "<div class='inside'>" + notes + "</div>", "limits")
        + '<details class="panel full" id="evidence"><summary>Full evidence · JSON, including every triage and check result</summary><pre>' + raw + "</pre></details></main>"
        + '<footer>Tessri ' + _e(b["tool"]["version"]) + " · Generated " + _e(b["generated_at"]) + " · Facts and candidate tests are not a merge decision.</footer></div></body></html>\n"
    )
