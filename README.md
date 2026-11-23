# tessri.

[![Tests](https://github.com/tianyi-zhang-02/tessri/actions/workflows/tests.yml/badge.svg)](https://github.com/tianyi-zhang-02/tessri/actions/workflows/tests.yml) ![Python 3.11 or newer](https://img.shields.io/badge/python-3.11%2B-5a46c2) ![No dependencies](https://img.shields.io/badge/dependencies-none-5a46c2) [![MIT](https://img.shields.io/badge/license-MIT-5a46c2)](LICENSE)

**Keep code understandable.**

See where to look first, what a change reaches, and what still needs a person. Tessri reads code and git,
offline, and puts the evidence on one review brief.

## Try a complete review

A small teaching repository has a refactor, two passing billing tests, and an unchanged reporting file that still
imports the deleted helper. The site and this example use the same generated brief:

```text
demo-brief: 8 code files changed, 22 lines; 1 block, 2 warn, 1 info.

block: util/money.py was deleted but is still imported.
       reports/summary.py is unchanged and still imports it.
Next:  restore the module, or update the importer in this change.

Host recorded: 2 billing tests passed (exit 0).
Association with the current code snapshot: unknown.
```

This is a worked example, not a production incident. From a Tessri checkout, reproduce it with
`python tools/review_example.py --out /tmp/tessri-example`; the generator runs the two tests, then writes
`index.html`, `brief.json` and `brief.md`. Use a new or empty output directory.
[Explore the worked review](https://tianyi-zhang-02.github.io/tessri/example/).

For a change in your own repository:

```bash
tessri review --since main
tessri review --since main --out /tmp/tessri-review.html
```

The first command opens a local source and evidence workbench; the second exports one offline snapshot.
Follow a finding into unchanged code, compare working-tree and base source, and copy its context back to your
agent. The live session marks older results and refreshes explicitly. Candidate tests stay separate from supplied
results, whose association with the code snapshot remains unknown. Use `--since HEAD` for uncommitted work.
See the [review guide](docs/guide/review.md) for Codex, Claude Code and Copilot setup. This command is unreleased;
run it from this source checkout until the next package release.

| Your task | Start here |
|---|---|
| Take over a change | [Review brief](docs/guide/brief.md): what to read, why, and what still needs a person |
| Follow what it reaches | [Impact](docs/guide/impact.md): dependents and candidate tests, with evidence types |
| Check the consequences | [Check](docs/guide/check.md): introduced structural findings and an optional CI exit code |

[Understand the modules](docs/guide/graph.md), [find what nothing reaches](docs/guide/scan.md), or
[see who maintains it](docs/guide/ownership.md). What static analysis cannot see stays explicit in
[the limits](docs/guide/limits.md). There is no composite risk score.

## Install

```bash
pip install tessri
```

Python 3.11 or newer, no dependencies. To run it once without installing: `uvx tessri scan .`

## In an agent's loop

The same questions, where the agent and the reviewer already are. Each line installs with a receipt and
`tessri integration remove` takes it out again; the [integration](docs/guide/integration.md) page has every option.

![Six stations of a change in a loop: arriving in a project with scan, graph and why; before a change, impact; while the agent edits, hooks give impact after each edit and check when it stops; review with triage; done with check; hand over with brief as a pull request comment.](docs/guide/figures/loop.svg)

| Where | Install | What it gives |
|---|---|---|
| Any MCP host | `tessri integration install --agent mcp`; `cursor`, `gemini`, `junie`, `roo`, `kiro`, `warp`, `factory` or `vscode` for the file that host reads | the questions as tools (`tessri_impact`, `tessri_triage`, `tessri_check`, `tessri_brief`, `tessri_why`, `tessri_scan`, `tessri_graph`), served by `tessri mcp`; see [MCP](docs/guide/mcp.md) |
| Claude Code, Codex | `--agent claude-hooks`, `--agent codex-hooks` | after each edit, what the edited file reaches; when the agent stops, what the uncommitted work did to the structure; see [hooks](docs/guide/hooks.md) |
| Skills and instructions | `--agent claude`, `codex`, `agents`, `copilot` | when to ask which question, as the agent's own instructions |
| Every pull request | `--agent review` | the brief below, posted as a comment |
| A weekly look | `--agent report` | the HTML report of the repository, on a schedule |

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

Checks the host ran: none recorded. Record each with `--ran "<command>: <result, exit code>"`, or hand over a test report with `--report` or a coverage report with `--coverage`.
```

The page goes on with what is open for a person and what to read with care; the JSON carries the whole `triage`
and `check` objects, so a list shortened on the page hides nothing there.

## A complete example

What can a change to one file affect? On this repository:

```text
$ tessri impact tessri/graph.py
Changing tessri/graph.py  (1 file, 113 code lines) can affect:

- **23 code files** in **2 modules** (47.9% of the code), 1 of them directly (one followed edge away)
- **30 test files** reaching it (candidates to run, not runs), 1 directly
- code files by number of followed edges away: 1: 1, 2: 14, 3: 8
- edges followed, any number of steps: recognized dependency syntax, package files, and 3 references found in strings, dynamic loading or unclassified evidence (for example `tests/test_site.py` → `tessri/cli.py`, string); syntax and package files alone reach 23 code files and 30 test files

| Affected module | Files | Direct | Owners | State |
|---|---:|---:|---|---|
| `tessri` | 18 | 1 | Tianyi Zhang 100% | owned |
| `tools` | 5 | 0 | Tianyi Zhang 100% | owned |

People who maintain the affected code (tell them, or ask them to review): Tianyi Zhang 100%

Tests that reach it, nearest first: `tests/test_site.py`, `tests/test_cache.py`, `tests/test_htmlreport.py`, `tests/test_javascript.py`, `tests/test_markup.py`, `tests/test_meta.py`, `tests/test_modules.py`, `tests/test_moves.py`, `tests/test_ownership.py`, `tests/test_provenance.py` and 20 more

It depends on: `tessri` (2), `tessri/analyzers` (1)

Static analysis of this repository under the selected edge policy and hop limit: registries, dependency injection and consumers outside the repository are not counted, and a file outside this set is not shown to be unaffected.
```

That's it. `tessri why tessri/graph.py` shows the evidence behind any line of it, and `--edges imports` keeps to
the recognized imports and leaves the string references at the frontier.

## How does it work?

![One pass over the files and the history: inventory, the analyzers for Python and JavaScript with the names found in configs and docs, and the graph go into one analysis; gitlog and ownership join it; scan, why, graph, impact, triage, check and brief are views of that one picture.](docs/guide/figures/pipeline.svg)

Tessri lists the files, parses Python with Python's own parser and JavaScript/TypeScript with its own scanner,
builds the import graph, reads who changed what from git, and answers every question from that one picture. No
model, no network, no service, and it never edits your code. What it read from each file it keeps in your cache
directory, keyed by the file's content, so the next run parses only what changed and answers the same. The order `triage` puts files in was
[backtested on real history](docs/guide/backtest.md), and the composite risk score we tried did not beat its parts,
so there is none.

## Getting started

`tessri scan .` in any repository, or `tessri scan . --format html --out report.html` for one page to open. Then, by
the question; without `--since`, a branch is judged against the default branch.

| The question | The command | Read |
|---|---|---|
| What can a change to this file affect, which tests reach it, who maintains that? | `tessri impact <path>` | [impact](docs/guide/impact.md) |
| Which of the changed files deserve a person first? | `tessri triage --since <base>` | [triage](docs/guide/triage.md) |
| What did the change do to the structure? | `tessri check --since <base>` | [check](docs/guide/check.md) |
| Hand the change over, on one page | `tessri brief --since <base>` | [brief](docs/guide/brief.md) |
| What is the evidence behind what it said about this file? | `tessri why <path>` | [scan](docs/guide/scan.md) |
| How do the modules depend on each other? | `tessri graph .` | [graph](docs/guide/graph.md) |
| What does nothing reach, and what does nobody maintain? | `tessri scan .` | [scan](docs/guide/scan.md), [ownership](docs/guide/ownership.md) |

[Which command, when](docs/guide/when.md) has the rest, and `tessri integration install --agent config` writes a
starter `.tessri.toml` with every option commented out.

## Read more

- [Guide](docs/guide/README.md): every question Tessri answers, one page each, with real output, and
  [which command, when](docs/guide/when.md).
- [Demo](https://tianyi-zhang-02.github.io/tessri/demo/): Tessri on itself, rebuilt on every push.
- [Blog](https://tianyi-zhang-02.github.io/tessri/blog/): notes from building it, with the drawings: how the numbers were
  tested, what the pages are for, how the code is put together.
- [Integration](docs/guide/integration.md): skills, AGENTS.md, [hooks](docs/guide/hooks.md) and CI, with copyable recipes in
  [workflow-recipes.md](docs/workflow-recipes.md); [MCP](docs/guide/mcp.md): the questions as tools for any agent
  that speaks the protocol.
- [Configuration](docs/guide/configuration.md), [JSON output](docs/guide/json.md),
  [Architecture](docs/guide/architecture.md), [Limits](docs/guide/limits.md).
- [Changelog](CHANGELOG.md). Tessri was called repolife until 0.2.0;
  [what to rename](docs/guide/formerly-repolife.md) when upgrading from the old name.
- [Contributing](CONTRIBUTING.md): what the code keeps, where things live, and how to tell us what Tessri got wrong.

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
landing page, the stylesheet, the type and the icons with their notices, and the mark's shader, and
`.github/workflows/site.yml` deploys it to GitHub Pages:

```bash
python3 tools/build_site.py --out _site --demo && python3 -m http.server --directory _site
```

`--demo` adds the pages that run Tessri on this checkout: the HTML report, and the brief of the latest commit
against its first parent.

The order `triage` uses and the import graph's claim to predict what changes together are tested on history, not
assumed. The test runs on any repository, and [the backtest](docs/guide/backtest.md) in the guide is its output on three:

```bash
python3 tools/backtest.py path/to/repository --months 12
```

The warning `check` gives about a name a deletion left behind is tried the same way, on every deletion in a
repository's history, with what later commits did about each name:

```bash
python3 tools/deletions.py path/to/repository --days 365
```

The brief's *who can look* is held against who actually reviewed, on a repository's own pull requests through the
GitHub command line, and [the reviewer match](docs/guide/reviewer-match.md) in the guide is its output on two, and the
third repository on which it had nothing to judge:

```bash
python3 tools/reviewer_match.py collect owner/name path/to/checkout --out pulls.json && python3 tools/reviewer_match.py score pulls.json path/to/checkout
```

A release is a tag. Bump `version` in `pyproject.toml` and `tessri/__init__.py`, head the changelog section with the
version and the day, then `git tag v0.4.0 && git push origin v0.4.0`: `.github/workflows/release.yml` checks that the
tag is the version the code states, builds the sdist and the wheel, installs the wheel on 3.11 and 3.12 and runs it,
publishes to PyPI through trusted publishing (nothing secret in the repository; once, on PyPI, the project's trusted
publisher is set to this repository's `release.yml` with environment `pypi`), and creates the GitHub release with the
changelog section and the files.

## License

MIT
