# tessri.

**Keep code understandable.**

Tessri reads a codebase and its git history, offline and with nothing else installed, and lets you:

- See how the system fits together: the modules, the cycles, and the few dependencies that would break them.
- See what a change can reach, the tests that reach it, and who is able to review it.
- Find what nothing reaches and what nobody maintains.
- Check what a change did to the structure, as Markdown, JSON or SARIF, with an exit code for CI.

Every claim can be traced to its evidence, and what the analysis cannot see it says it cannot see.

## Install

```bash
pip install tessri
```

Python 3.11 or newer, no dependencies. To run it once without installing: `uvx tessri scan .`

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

- [Guide](docs/guide/README.md): every question Tessri answers, one page each, with real output.
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
python3 tools/build_site.py --out _site && python3 -m http.server --directory _site
```

A release is a tag. Bump `version` in `pyproject.toml` and `tessri/__init__.py`, head the changelog section with the
version and the day, then `git tag v0.3.0 && git push origin v0.3.0`: `.github/workflows/release.yml` checks that the
tag is the version the code states, builds the sdist and the wheel, installs the wheel on 3.11 and 3.12 and runs it,
publishes to PyPI through trusted publishing (nothing secret in the repository; once, on PyPI, the project's trusted
publisher is set to this repository's `release.yml` with environment `pypi`), and creates the GitHub release with the
changelog section and the files.

## License

MIT
