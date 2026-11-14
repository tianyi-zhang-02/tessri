"""Text written into a repository by `tessri integration install`. Kept as strings so the tool works from a zipapp too.
The two workflows pin the Tessri that installed them, so `integration status` says `installed-outdated` after an
upgrade and `integration update` refreshes the pin."""

from . import __version__

CONFIG = """\
# Tessri configuration. Every option is optional; see `tessri scan --help`.

# A file touched within this many days is ACTIVE.
# active_days = 90

# A file untouched this long that few others use is DORMANT.
# dormant_days = 365

# Files that look unused but must stay: public API of a library, plugin entry
# points, anything loaded by name from outside the repository. Globs, `*` crosses `/`.
# keep = ["src/mypkg/api/*", "plugins/*"]

# Files to leave out of the analysis entirely.
# exclude = ["vendor/*", "**/generated/*"]

# Extra entry points: a module name or a file path.
# entry = ["mypkg.cli", "scripts/release.py"]

# Ownership: an author with no commit anywhere in the repository for this many days
# no longer counts as someone who maintains the code.
# owner_inactive_days = 180

# Review load: how much code changed in this many days, against the same number of days before.
# 0 turns it off.
# review_days = 30

# Commit authors that never own code, matched against name or email, ignoring case.
# Bots such as dependabot are ignored already. A .mailmap merges one person's addresses.
# ignore_authors = ["release-script*", "*@ci.example.com"]

# Agent hooks (`tessri integration install --agent claude-hooks` or `codex-hooks`): where the
# findings of `check` on the uncommitted work go when the agent stops. "inform" shows them to
# you; "block" hands them to the agent first, once, and to you after that.
# stop_hook = "inform"
"""

SKILL = """\
---
name: tessri
description: Inspect repository structure, static reachability, Git activity and ownership when planning a change, reviewing its impact, investigating unused code or prioritizing maintenance.
---

# Tessri

Tessri reports five things about a repository: how much code there is, how recently it
changed, whether anything still reaches it, who has been maintaining it, and how its modules depend on
each other. Its analysis queries only read the repository.

Pick the query by the task, and do not start every task with a full scan:

- about to edit a file or directory: `tessri impact <path>` for possible dependents, candidate tests and maintainers
- preparing or doing a review: `tessri triage --since <base>` for which changed files deserve a person first
- finishing a change: `tessri check --since <base>` for what it did to the structure
- handing a change to a person: `tessri brief --since <base> --ran "<check: result>"` for one page with both
- checking a claim about one file: `tessri why <path>` (`--format json` gives the same facts as data)
- getting to know a repository, or planning a cleanup: `tessri scan` and `tessri graph`

When Tessri is connected as an MCP server (`tessri mcp`), the same questions are the tools `tessri_scan`,
`tessri_why`, `tessri_impact`, `tessri_graph`, `tessri_triage`, `tessri_check` and `tessri_brief`; each returns the command's
JSON as structured content and its text as content, and `tessri_repos` lists the checkouts the server reads.

When the project's hooks are installed (`tessri integration install --agent claude-hooks` or `codex-hooks`),
what a code file can reach arrives by itself after you edit it, once per file, and what the uncommitted work
did to the structure when you stop; what arrives that way needs no command. Without them, ask with the
commands above.

## Run it

For a repository overview:

```bash
tessri scan . --format json
```

The JSON goes to stdout; add `--out <file>` only when a task needs the report as a file. If `tessri` is not on
PATH, try `python3 -m tessri ...`; if that fails too, the capability is unavailable: say so and follow the
project's policy, and do not install or download anything to make a routine query work.
Use `--format json` for structured query results; default text/Markdown is for reading. `scan` also supports
`--format html --out report.html` for a self-contained overview with the module graph and an impact explorer.

Select the intended repository root with `--repo <root>` (`scan` and `graph` also take it as their first
argument). Before combining saved reports, check `meta.repo`, `meta.git` and, for change queries,
`meta.change`: HEAD, the revision used for history and the comparison base can differ. Missing or skipped
analysis is unavailable evidence, not an empty success.

For a scan, read `summary` (sizes, status counts, orphan share), `cleanup.orphan_files`,
`cleanup.test_only_files`, then `hotspots` and `directories` for where change is concentrated,
and `ownership` for who maintains what.

## Dependencies and blast radius

```bash
tessri graph . --format json
tessri impact <file-or-directory> --format json
```

`graph` rolls the import graph up into modules (directories, split by size; `--module-depth N` fixes the
depth). Read `cycles` for areas needing joint context; each lists heuristic candidates to cut or invert
(`cut`, with an example reference to inspect), not an approved architecture change.
`modules[].used_by` is how many modules depend on one: a change in a module with a high `used_by` needs
more context. `--level file` gives file pairs; `--format mermaid` or `dot` draws the modules. This legacy graph
excludes Python parent-package and inferred edges, while JS/TS can include resolved string/dynamic references.
Do not assume its edges match either impact policy.

`impact` follows relationships backwards. Its default `all` policy includes recognized imports, Python parent
packages, supported dynamic patterns, string references and unclassified plugin edges. Read `edges.policy` and
`edges.hops` with the counts. `edges.imports_only` gives the narrower code/test counts at the same hop limit;
`edges.references` shows counted, capped examples of inferred or unknown edges. These describe the frontier
visited, not every such edge in the repository.

When a review question needs the import-based view, use `tessri impact <path> --edges imports --format json`.
It keeps recognized dependency syntax and Python parent packages: importing `a.b.c` can run `a/__init__.py`.
It excludes string, computed/glob and unknown edges; `edges.excluded` and `edges.unclassified` disclose those
encountered. Evidence labels describe syntax, not execution: Python literal `import_module("pkg.mod")` currently
counts as a string, while JS literal `import("./x")` is recognized dependency syntax. Keep the broad evidence
available when narrowing; fewer dependents do not establish that other files are unaffected.
If an older CLI lacks the flag or evidence fields, state that limitation and use the available broad facts;
do not label them import-only or install another version to complete a routine query.

`dependents.by_distance` counts selected edges; `--hops 1` keeps one-step dependents. `depends_on` is a separate
one-step forward summary, not the reverse walk. `owners` supplies maintenance history for the project's review
process. `tests.paths` and triage's `tests.nearest` are candidate paths, not commands or execution records: map
them to the project's test runner and retain its required checks. Empty, shortened or narrowed lists do not
justify skipping other tests. Record actual test results separately. Runtime wiring and external consumers
can remain invisible under either policy.

## Triage a change

```bash
tessri triage --since <base> --format json     # a branch against its base; without --since, against the default branch
```

Run it before you open a change and before you review one. `files` is the changed code, most active first: files
that were committed to most in the last 90 days, then by lines changed. Fix and revert history (`fixes_90`),
`dependents`, `owners` and `flags` are context shown beside the order, not part of it. `ripple` is code outside the
change that imports the changed files, `tests.nearest` are candidate tests, `reviewers` are the people who maintain the
files other than the authors, and `nobody_else_can_look` lists files only the author maintains. A flag
`no active owner` means nobody who maintains the file has committed lately: say so where the change is described, so
a person can decide who looks, and do not pick a reviewer from its last maintainers; whether that pauses the work is
the team's policy, not the tool's. History is read up to the base, so the change's own commits do not count. It is a
prompt about where to look, not a verdict.

## Check a change's structure

```bash
tessri check --since <base> --format json --fail-on never     # without --since, against the default branch
```

Run it when a task is done and before the change is opened. It compares the base of the change with the working
tree and lists what the change did to the structure, `findings` ordered by `severity`. With `--fail-on never` the
exit code stays 0 and the findings are yours to read; `--fail-on block` exits 1 on certain breakage and is for
projects that have explicitly turned that gate on, not a default. `block` flags a static reference to a deleted file:
`dangling-import` means a file the change deleted is still imported by files it did not touch, so restore it or
update the importers. `warn` needs a decision: `new-cycle` and `cycle-grew` name the new dependency that closed the
loop, `new-orphan` is a new file nothing reaches (`how: stranded` is a file the change cut the last link to, with
`was_reached_from` and the kind of each link), `dangling-reference` is a deleted or moved file that an untouched file
still names in a string or a dynamic import (a guess that it is loaded at run time: check the name, and update it or
restore the file), and `no-active-owner` is changed code nobody active maintains (`needs_human`: a person decides who
looks at it; do not pick a reviewer from its last maintainers, and do not stop on your own unless the team asks for
that). `info` is the rest. Findings are bounded by static analysis and its language coverage; a clean result is not proof.

## Hand a change over

```bash
tessri brief --since <base> --ran "<command>: <result, exit code>"     # one page for the person; --format json for the data
```

Run it when the change is ready for a person. It is triage and check from one analysis, in one page: the base,
HEAD, the commits on the way in their authors' words and the uncommitted files in scope; the changed files to look
at first with the reasons; the findings; the candidate tests kept apart from the checks that ran; who can look;
and what needs a person. Every shortened list carries its count, and the JSON holds the whole `triage` and `check`
objects, so nothing is filtered away. Record what you actually ran with `--ran`, one per check, with its result and
exit code, verbatim; without it the page says that no check was recorded, and it never infers an execution from the
candidate tests. Put the page in the change's description, or hand the JSON to the reviewer's tools; it is a reading
aid, not a verdict, and the diff is still theirs to read.

## Ownership

`ownership` is inferred from git: each commit credits its author with the files it touched, recent
commits weighing more, so an owner is whoever has maintained a file lately. It says who has been
changing the code, not who is accountable, and git cannot tell who reviewed.

- `directories[].owners` lists the people behind each directory with their share and `idle_days`
  (days since their last commit anywhere in the repository). `ownership` is `owned`,
  `no-active-owner` (the people still active hold under 20% of the maintenance) or `unknown`.
- `ownership.needs_owner_files` is live code nobody active maintains: name it in the change description so a
  person can assign it, and do not pick a reviewer from it; a missing owner is a reason for care, not a rule to
  stop. `ownership.codeowners` compares CODEOWNERS with the commit history (`uncovered_files`, `differing_files`).
- Orphan rows carry `owner` and `owner_idle_days`: that is who to ask before deleting. An owner who
  is gone is a reason to be careful, not permission to delete.
- To find who to ask about a path, use `tessri why <path>`: its `owners:` line lists who maintains it
  and marks anyone who has gone silent.
- Authors are matched by name; a `.mailmap` fixes merged or split people. Bots are ignored.

## Review load

`review` counts the lines that changed in code files over the last `review_days` days (30) against the days before,
per area (a directory, split by size). It measures how much review the changes ask for, not who reviewed: git
cannot see that.

- `areas[]` has `lines`, `previous_lines`, `commits`, `authors`, `outside_share` (the share of the people's lines
  written by someone who is not among the area's owners) and `ownership`. Read `outside_share` with `owners`:
  where ownership is spread thin, most changes are by "outsiders".
- `unowned` is the lines that landed where nobody active maintains the code. Raise it with a human; do not pick a
  reviewer there.
- `reviewers[]` are the people who maintain the areas others changed, by `inbound_lines`; `active: false` means
  they have gone quiet. Use it to decide whom to ask or tell, not as an assignment.
- `largest_changes[]` are the biggest single commits: where to start when review time is short. Commits touching
  `totals.bulk.threshold` or more files are reported apart under `totals.bulk`.

## Statuses

- ACTIVE: touched in the last `active_days` (default 90).
- STABLE: not touched recently, but other code depends on it. Normal; leave it alone.
- DORMANT: untouched for `dormant_days` (default 365) and barely used.
- ORPHAN: no entry point, test or config reaches it. A cleanup candidate, not a verdict.

## Cleanup workflow

1. Start with orphan files whose `confidence` is `high`. `medium` and `low` carry a reason in
   `notes` (recently modified, mentioned in docs, lives under `scripts/`); show those to a human first.
2. For each candidate run `tessri why <path>`. It shows who depends on the file, what config names
   it, and what else would be stranded by deleting it.
3. Search the repository yourself for the module name and its public symbols: a static scan can miss string
   lookups, registries and entry points, and cannot see consumers outside this repository.
4. If it is really unused, delete it in a small change (one cluster of related files per change)
   and run the tests. If it is intentionally kept, add it to `keep` in `.tessri.toml` with a comment.
5. For `test_only_files`, ask whether production code lost its caller. Do not delete tests to make
   the number go down.

## Do not

- Delete anything from a single scan without step 2 and step 3.
- Treat DORMANT or low activity as proof that code is unused. Reachability supplies cleanup candidates within its coverage.
- Remove files a library exports to its users; list them under `keep` instead.
"""

AGENTS_BLOCK = """\
## Repository health (Tessri)

Choose repository evidence for the task: `tessri impact <path>` for a file or directory change,
`tessri triage --since <base>` for review attention, `tessri check --since <base>` for structural effects,
`tessri brief --since <base> --ran "<check: result>"` for the one page that hands a change to a person,
and `tessri scan . --format json` with `tessri graph` for orientation or cleanup. Use the project's base
and gate policy; a full scan is not required for every edit.

Impact's default includes imports, parent packages and inferred references. Its `edges` data explains the
sources and compares import-only counts; use `--edges imports` when that narrower view answers the question.
It retains Python parent packages, but excludes string, dynamic and unknown evidence. Keep the broad evidence
and analysis limits visible. Candidate tests are paths to map to the project's runner, not execution records
or a complete test plan; retain required checks and report what actually ran. Maintenance history suggests
review context, not an assignment.

Before deleting a cleanup candidate, use `tessri why <path>` and a repository-wide search. Static analysis
can miss runtime wiring and external consumers; activity alone does not establish disuse. Files intentionally
kept can go under `keep` in `.tessri.toml`. Delete in small changes and run the project's tests.
"""

# The skill as Copilot's path-scoped instructions: the same text under the frontmatter that file format wants.
COPILOT_INSTRUCTIONS = '---\napplyTo: "**"\n---\n' + SKILL.split("---\n", 2)[2]

# One entry each in the MCP configuration files hosts read from a project; the receipt records the entry, not the file.
MCP_SERVER = {"command": "tessri", "args": ["mcp"]}  # `.mcp.json`, key mcpServers.tessri
VSCODE_SERVER = {"type": "stdio", "command": "tessri", "args": ["mcp"]}  # `.vscode/mcp.json`, key servers.tessri
# Copilot's coding agent takes its servers from the repository's settings page; this is the JSON to paste there.
COPILOT_AGENT_SERVERS = {"mcpServers": {"tessri": {"command": "tessri", "args": ["mcp"], "tools": ["*"]}}}
CODEX_MCP_COMMAND = "codex mcp add tessri -- tessri mcp"  # Codex keeps MCP servers in the user's configuration, not the project's

# The lifecycle hooks Claude Code (`.claude/settings.json`) and Codex (`.codex/hooks.json`) run. Both read this shape:
# one matcher group per event, each running `tessri hook`, which answers with the host's JSON or with nothing.
HOOKS = {
    "PostToolUse": {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "tessri hook", "timeout": 60}]},
    "Stop": {"hooks": [{"type": "command", "command": "tessri hook", "timeout": 120}]},
}

REPORT_WORKFLOW = """\
# Tessri's weekly report: the scan of the whole repository, as JSON and as one HTML page, kept as a workflow artifact
# and summarised on the run. Installed by `tessri integration install --agent report`.
name: tessri report

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: read

jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0 # activity and ownership need the whole history
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install tessri==__VERSION__
      - name: Scan
        run: |
          tessri scan . --format json --out tessri-report.json
          tessri scan . --format html --out tessri-report.html
          tessri scan . | tee -a "$GITHUB_STEP_SUMMARY" > /dev/null
      - uses: actions/upload-artifact@v4
        with:
          name: tessri-report
          path: |
            tessri-report.json
            tessri-report.html
""".replace("__VERSION__", __version__)

REVIEW_WORKFLOW = """\
# Tessri's review brief on every pull request: the page that hands the change over, as one comment that is updated in
# place on every push (from a fork, whose token cannot comment, the page is in the run's summary instead), and the
# structural findings as a SARIF file kept with the page as an artifact. The base is the pull request's own, never an
# assumed branch name. Installed by `tessri integration install --agent review`; the file is yours once edited.
name: tessri review

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write # the comment

concurrency:
  group: tessri-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  brief:
    runs-on: ubuntu-latest
    env:
      BASE: ${{ github.base_ref }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }} # the branch as pushed, not the merge commit the event carries
          fetch-depth: 0 # the base, and the history up to it
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install tessri==__VERSION__
      - name: Brief
        run: |
          tessri brief --since "origin/$BASE" --out tessri-brief.md
          cat tessri-brief.md >> "$GITHUB_STEP_SUMMARY"
      - name: Comment
        if: github.event.pull_request.head.repo.full_name == github.repository # a fork's token cannot comment
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          NUMBER: ${{ github.event.pull_request.number }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          marker='<!-- tessri:review -->'
          {
            printf '%s\\n' "$marker"
            cat tessri-brief.md
            printf '\\n_`tessri brief --since origin/%s` at %s, by [this run](%s); updated on every push._\\n' "$BASE" "${HEAD_SHA:0:9}" "$RUN_URL"
          } > tessri-comment.md
          existing=$(gh api "repos/$REPO/issues/$NUMBER/comments" --paginate --jq ".[] | select(.body | startswith(\\"$marker\\")) | .id" | head -n 1)
          if [ -n "$existing" ]; then
            gh api --method PATCH "repos/$REPO/issues/comments/$existing" -F body=@tessri-comment.md --silent
          else
            gh api --method POST "repos/$REPO/issues/$NUMBER/comments" -F body=@tessri-comment.md --silent
          fi
      - name: Check
        # --fail-on block fails the job when a deleted file is still imported; turning that gate on is the team's choice
        run: tessri check --since "origin/$BASE" --format sarif --locationless omit --fail-on never --out tessri-check.sarif
      - uses: actions/upload-artifact@v4
        with:
          name: tessri-review
          path: |
            tessri-brief.md
            tessri-check.sarif
      # For the findings as code-scanning alerts, on a repository where code scanning is on: add
      # `security-events: write` to the permissions above and this step.
      # - uses: github/codeql-action/upload-sarif@v3
      #   with:
      #     sarif_file: tessri-check.sarif
      #     category: tessri
""".replace("__VERSION__", __version__)
