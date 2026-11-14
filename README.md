# tessri.

**Keep code understandable.**

Agents write more of the code; people still have to stand behind it. Tessri reads a codebase and its git history,
offline and with nothing else installed, and tells the person a change is handed to where to look first, who is
able to look, what the change did to the structure and what nobody maintains, with the evidence for every claim.

- Hand a change over on one page: the files to look at first and why, who can look, what it did to the structure,
  the candidate tests kept apart from what actually ran, and what needs a person. On every pull request, if you want.
- See what a change can reach, the tests that reach it, and who is able to review it.
- See how the system fits together: the modules, the cycles, and the few dependencies that would break them.
- Find what nothing reaches and what nobody maintains.
- Check what a change did to the structure, as Markdown, JSON or SARIF, with an exit code for CI.

What the analysis cannot see, it says it cannot see. See it on this repository, rebuilt on every push to `main`:
[the brief of the latest change](https://tianyi-zhang-02.github.io/tessri/demo/) and
[the HTML report](https://tianyi-zhang-02.github.io/tessri/demo/report.html) with the module graph and the
impact explorer.

## Install

```bash
pip install tessri
```

Python 3.11 or newer, no dependencies. To run it once without installing: `uvx tessri scan .`

## The hand-off

A change is done, by an agent or by a person. `tessri brief --since <base>` is the page the reviewer gets; this one
is from [a pull request of this repository](https://github.com/tianyi-zhang-02/tessri/pull/13), where the `review`
workflow posted it as a comment, shortened here to the first sections:

```text
`origin/release-0.3.0` (base 922381dac) to HEAD 788f979b5. 6 code files changed (0 added, 6 modified, 0 deleted), **186** lines; 5 other files (122 lines of config, docs and the like).

1 commit on the way, by Tianyi Zhang, in their words:

- `788f979b5` The review brief on every pull request: `tessri integration install --agent review` (Tianyi Zhang)

## Look first

| # | File | Why | This change | Owners | Flags |
|---:|---|---|---|---|---|
| 1 | `tessri/cli.py` | 15 commits in 90 days | +2 -2 | Tianyi Zhang 100% | - |
| 2 | `tessri/templates.py` | 12 commits in 90 days | +81 -3 | Tianyi Zhang 100% | - |
| 3 | `tests/test_integration.py` | 5 commits in 90 days | +83 -1 | Tianyi Zhang 100% | test file |
| 4 | `tessri/integration.py` | 5 commits in 90 days | +3 -2 | Tianyi Zhang 100% | - |

Nobody other than the authors maintains the changed files, as far as history shows.

## What it did to the structure

No structural findings: the change adds no orphan, cycle, dangling import or unowned code that this analysis can see.

Code outside the change that imports it: **1 file** directly, 0 files through one more step (by area: `tessri` 1).

## Validation

Candidate tests, nearest first: `tests/test_brief.py`, `tests/test_htmlreport.py`, `tests/test_integration.py`, `tests/test_mcp.py`, `tests/test_meta.py` and 3 more (15 in all). They reach the changed files; they are paths, not results.

Checks the host ran: none recorded. Record each with `--ran "<command>: <result, exit code>"`.
```

The page goes on with what is open for a person and what to read with care; the JSON carries the whole `triage`
and `check` objects, so a list shortened on the page hides nothing there.

## A complete example

What can a change to one file affect? On this repository:

```text
$ tessri impact tessri/graph.py
Changing tessri/graph.py  (1 file, 110 code lines) can affect:

- **14 code files** in **1 module** (40.0% of the code), 1 of them directly (one followed edge away)
- **20 test files** reaching it (candidates to run, not runs), 0 directly
- code files by number of followed edges away: 1: 1, 2: 11, 3: 2
- edges followed, any number of steps: recognized dependency syntax, package files, and 0 references found in strings, dynamic loading or unclassified evidence; syntax and package files alone reach 14 code files and 20 test files

| Affected module | Files | Direct | Owners | State |
|---|---:|---:|---|---|
| `tessri` | 14 | 1 | Tianyi Zhang 100% | owned |

People who maintain the affected code (tell them, or ask them to review): Tianyi Zhang 100%

Tests that reach it, nearest first: `tests/test_htmlreport.py`, `tests/test_javascript.py`, `tests/test_markup.py`, `tests/test_meta.py`, `tests/test_modules.py`, `tests/test_moves.py`, `tests/test_ownership.py`, `tests/test_provenance.py`, `tests/test_renames.py`, `tests/test_resolve.py` and 10 more

It depends on: `tessri` (2), `tessri/analyzers` (1)

Static analysis of this repository under the selected edge policy and hop limit: registries, dependency injection and consumers outside the repository are not counted, and a file outside this set is not shown to be unaffected.
```

That's it. `tessri why tessri/graph.py` shows the evidence behind any line of it, and `--edges imports` keeps to
the recognized imports and leaves the string references at the frontier.

## How does it work?

Tessri lists the files, parses Python with Python's own parser and JavaScript/TypeScript with its own scanner,
builds the import graph, reads who changed what from git, and answers every question from that one picture. No
model, no network, no service, and it never edits your code. The order `triage` puts files in was backtested on
real history, and the composite risk score we tried did not beat its parts, so there is none.

## Getting started

1. `tessri scan .` in any repository, or `tessri scan . --format html --out report.html` for one page to open.
2. `tessri impact <path>` before a change, `tessri triage` to review one, `tessri check` when it is done, and
   `tessri brief` to hand it over on one page; without `--since`, a branch is judged against the default branch.
3. `tessri integration install --agent claude` (or `codex`, `agents`, `copilot`) installs the agent's
   instructions with a receipt, `--agent mcp` points a host at `tessri mcp`, the same questions as MCP tools,
   `--agent config` writes a starter `.tessri.toml`, `--agent report` a weekly report workflow and
   `--agent review` the brief as a comment on every pull request; `tessri integration remove` takes it all out again.

## Read more

- [Guide](docs/guide/README.md): every question Tessri answers, one page each, with real output, and
  [which command, when](docs/guide/when.md).
- [Demo](https://tianyi-zhang-02.github.io/tessri/demo/): Tessri on itself, rebuilt on every push.
- [Integration](docs/guide/integration.md): skills, AGENTS.md and CI, with copyable recipes in
  [workflow-recipes.md](docs/workflow-recipes.md); [MCP](docs/guide/mcp.md): the questions as tools for any agent
  that speaks the protocol.
- [Configuration](docs/guide/configuration.md), [JSON output](docs/guide/json.md),
  [Architecture](docs/guide/architecture.md), [Limits](docs/guide/limits.md).
- [Changelog](CHANGELOG.md). Tessri was called repolife until 0.2.0;
  [what to rename](docs/guide/formerly-repolife.md) when upgrading from the old name.

## Development

```bash
python3 -m unittest discover -s tests
```

The JavaScript scanner is checked against the TypeScript compiler rather than trusted. Given any directory of real
code (a `node_modules` works) and an installed `typescript` package, this compares the module specifiers both find
and lists every disagreement (needs `node`):

```bash
python3 tools/diff_js_scanner.py path/to/node_modules --typescript path/to/node_modules/typescript --sample 5000
```

The site is built from this README and `docs/guide/` by a script with no dependencies either; `site/` holds the
landing page, the stylesheet and the icon, and `.github/workflows/site.yml` deploys it to GitHub Pages:

```bash
python3 tools/build_site.py --out _site --demo && python3 -m http.server --directory _site
```

`--demo` adds the pages that run Tessri on this checkout: the HTML report, and the brief of the latest commit
against its first parent.

## License

MIT
