# Hand a change over: the review brief

`tessri brief --since <base>` is one page for the person a change is handed to: triage and check from one analysis,
with the exact state the evidence describes, the candidate tests kept apart from the checks that actually ran, and
what needs a person.

```bash
tessri brief --since main                                                        # a branch against main, plus uncommitted work
tessri brief                                                                     # the same against the default branch (origin/HEAD, else main or master)
tessri brief --since main --ran "python -m pytest tests/test_x.py: 12 passed (exit 0)"   # record what you ran, one --ran per check
tessri brief --since main --format json                                          # the sections as data, with the whole triage and check objects
tessri brief --since main --out brief.md                                         # a file to paste into the change's description
```

A review starts with context nobody wrote down: which base the branch is judged against, whether uncommitted work is
in scope, what the commits say, which files deserve attention first, what the change did to the structure, which tests
reach it and which checks actually ran. [`triage`](triage.md) and [`check`](check.md) answer the middle of that. The
brief puts them on one page with the rest, from one analysis of the base and one of the working tree (so it costs
what `check` costs), and follows the sections the [review brief design](../design/review-brief.md) asked for. It
aims to stay under 800 words: every list it shortens carries its count, and the JSON holds the whole `triage` and
`check` objects, so the page selects for reading and filters nothing away.

```text
$ tessri brief --since main --ran "python -m pytest tests/test_invoices.py: 2 passed (exit 0)"
# Review brief: demo-brief

`main` (base 6081a02cb) to the working tree: HEAD 9ef0fcdb0 plus 1 uncommitted file (`tests/test_invoices.py`). 8 code files changed (1 added, 5 modified, 2 deleted), **21** lines; 1 other file (2 lines of config, docs and the like).

2 commits on the way, by Carol Chen, Dana Doe, in their words:

- `9ef0fcdb0` feat: gross (Carol Chen)
- `948b93b78` refactor: fold money into invoices (Carol Chen)

## Look first

| # | File | Why | This change | Owners | Flags |
|---:|---|---|---|---|---|
| 1 | `billing/tax.py` | 2 commits in 90 days, 1 of them fixes or reverts | +4 -0 | Alice Adams 100% | author is not among the owners |
| 2 | `billing/invoices.py` | quiet since 2025-10-02 | +3 -2 | Alice Adams 100% | author is not among the owners |
| 3 | `tests/test_invoices.py` | quiet since 2025-10-02 | +4 -0 | Alice Adams 100% | author is not among the owners; test file |
| 4 | `billing/helpers.py` | new file | +2 -0 | - | new file; orphan: nothing reaches it |
| 5 | `legacy/rates.py` | quiet since 2026-01-10 | +1 -1 | Bob Brown 100% (silent 300d) | no active owner; author is not among the owners |
| 6 | `svc/main.go` | quiet since 2025-10-02 | +1 -1 | Alice Adams 100% | author is not among the owners |
| 7 | `util/money.py` | quiet since 2025-10-02 | +0 -2 | - | deleted |
| 8 | `util/__init__.py` | quiet since 2025-10-02 | +0 -0 | - | deleted |

Who can look, other than the authors: Alice Adams (4 files). Git cannot see who reviewed; these are the people who maintain the changed files.

## What it did to the structure

**1 block, 2 warn.**

- **block**: `util/money.py` was deleted but is still imported (`reports/summary.py`). Do: Restore the file, or update every importer in the same change.
- **warn**: 1 new file that nothing reaches (`billing/helpers.py`). Do: Import them from where they are meant to be used, add a test that does, or drop them. `tessri why <file>` shows the evidence.
- **warn**: 1 changed file nobody active maintains (`legacy/rates.py`). Do: Have a human who knows the code look before merging, or assign an owner; the last maintainers are listed with `tessri why <file>`.

Code outside the change that imports it: **1 file** directly, 0 files through one more step (by area: `.` 1).

Not analysed: `svc/main.go` (Go, no analyzer), so dependents, candidate tests and structure are unknown for it.

## Validation

Candidate tests, nearest first: `tests/test_invoices.py`. They reach the changed files; they are paths, not results.

Checks the host ran, as recorded:

- python -m pytest tests/test_invoices.py: 2 passed (exit 0)

## Open for a person

- 1 changed file nobody active maintains: Have a human who knows the code look before merging, or assign an owner; the last maintainers are listed with `tessri why <file>`.
- Only the author maintains `legacy/rates.py`: a second reader has to come from outside the file's history.
- `svc/main.go`: no analyzer covers Go, so dependents, candidate tests and structure are unknown for this file.

## Read this with care

- This page selects from `tessri triage` and `tessri check`, run from one analysis of the base and one of the working tree; the JSON carries both objects whole, so a list shortened here hides nothing there.
- Files are ordered by how many commits touched them in the last 90 days, then by how much this change touches; in a backtest on one repository that predicted later fixes better than the size of the change alone. It says where trouble tends to be, not that this change is wrong, and a new file has no history, so it sorts by its size.
- Dependents, candidate tests and findings rest on what the analyzers see between files of this repository, static imports above all; a name in a string or a dynamic import is a guess, and the one finding that rests on it, `dangling-reference`, says so. Runtime wiring, registries and consumers outside the repository are invisible, and no finding is proof that the rest is fine.
- History is read up to the base, so the change's own commits do not count as activity and its authors do not count as owners. The commit subjects are the authors' words; the intent behind a change is not inferred from the files it touches.
- Candidate tests are paths that reach the change, never executions; only what `--ran` records was run.
```

**What is on the page.** The first paragraph is the scope: `since`, the base it resolves to, HEAD, and when there is
uncommitted work, the files it is in, because a commit id does not identify uncommitted contents; then the counts, and
the commits on the way with their authors and subjects, which are the authors' words, never an intent inferred from
the files. *Look first* is triage's order (commits in the last 90 days, then the size of the change) with its reasons,
owners and flags, and who other than the authors maintains the changed files. *What it did to the structure* is
check's findings, most serious first, each with its first files and what to do, then the code outside the change that
imports it, and the changed files no analyzer covers, named rather than dropped. *Validation* keeps two things apart:
the candidate tests, which are paths that reach the changed files, and the checks the host ran, which are only what
`--ran` recorded. *Open for a person* collects what the analysis cannot settle: findings that need a decision (changed
code nobody active maintains), files only the author maintains, files in a language without an analyzer, and the
absence of any recorded check.

**What ran is the host's to say.** Tessri runs no tests and reads no CI. `--ran` records one line per check,
verbatim, with whatever the host wants a reviewer to see (the command, the result, the exit code); the MCP tool takes
the same as `ran`, an array of strings. Without it the page says that no check was recorded. A candidate test is never
promoted to an execution, and a historical passing suite is not a current result.

**What it does not do.** It writes no review questions: those are the reviewer's, and the
[hand-curated sample](../examples/review-brief-f8d4219.md) shows what a person adds to the facts. It infers no
architectural intent and computes no composite score; a new file has no history, so it sorts by its size, which is
why the page says so. Everything structural rests on static imports between files of this repository, with the
[limits](limits.md) that implies.

`--format json` prints `kind: "brief"`: `change` (`since`, the full `base` and `head`, `uncommitted`,
`uncommitted_files`, `authors`, `commits` as `id`, `author`, `subject`, and the counts), `attention` (the first
`--limit` rows of triage's `files`, `shown`, `total`), `consequences` (`counts`, `findings`, `ripple`, `by_area`,
`modules_touched`, `not_analysed` as `language` and `files`), `validation` (`candidates` with `count` and `nearest`,
`ran`), `people` (`reviewers`, `nobody_else_can_look`, `no_active_owner`), `open` (each with `kind`, `text`, `files`;
the kinds are the finding kinds that need a person, `only-the-author`, `not-analysed` and `no-checks-recorded`), then
`triage` and `check` whole, and `notes`. `meta` is the [shared block](json.md) with `meta.change` and `meta.analysis`,
which says `skipped` with reason `no-code-changes` when there was nothing to compare. A bad base, or a directory that
is not a git repository, exits 2 with the sentence on standard error and nothing on standard output; the brief has no
gate, that is `check --fail-on`. The [MCP server](mcp.md) serves the same page and object as `tessri_brief`.

On every pull request, whoever or whatever wrote it: `tessri integration install --agent review` installs a
workflow that posts this page as one comment on the pull request, updated in place on every push, with the pull
request's own base ([integration](integration.md)).
