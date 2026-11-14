# Check what a change did to the structure

`tessri check --since <base>` compares a branch with its base and reports what the change did to the structure, with
an exit code for CI and SARIF for tools that read it.

```bash
tessri check --since main                  # a branch, judged from where it parted from main, plus uncommitted work
tessri check                               # the same against the default branch: origin/HEAD, else origin/main, origin/master, main or master
tessri check --since HEAD                  # only uncommitted work
tessri check --since main --fail-on block  # exit 1 when something is certain to break
tessri check --since main --format sarif --out check.sarif   # the same findings for tools that read SARIF
```

`scan` describes a repository as it is; `check` says what a change did to it. It reads the base of the change straight
from git objects into a scratch directory (the repository is not touched), analyses it and the working tree with the
same settings, and compares them. Triage says which files to look at first; this says what the change did to the
structure. They answer different questions and work together.

| Finding | Severity | What it means |
|---|---|---|
| `dangling-import` | block | a file the change deleted or moved is still imported by a file the change did not touch |
| `dangling-reference` | warn | a file the change deleted or moved is still named by a file the change did not touch: in a config or a script (wiring that now points at nothing), in a string or a dynamic import (a guess that the file is loaded at run time, so a person decides), or in documentation (then only `info`; a changelog or release notes are left alone, since they name deleted files on purpose) |
| `new-cycle`, `cycle-grew` | warn | modules that were not in a loop now are, or a cycle absorbed more modules; the new dependency that closed it is named |
| `new-orphan` | warn | a new file nothing reaches, or a file the change cut the last link to (`stranded`, with what used to reach it and how: an import, a config, or a name in a string); under `scripts/`, `examples/` and the like it is only a note, since those are run by hand |
| `no-active-owner` | warn | changed code nobody active maintains. History is read up to the base, so the author's own commits do not make them the owner |
| `new-dependency`, `orphan-resolved`, `cycle-resolved` | info | the other differences, the good ones too |

```text
$ tessri check --since main
# Change check: demo-check

`main` (9a0025443) to d6d893879: 4 files changed, 4 of them code (2 added, 1 modified, 1 deleted), **11** lines.

**1 block, 3 warn, 1 info.**

- **block**: `util/money.py` was deleted but is still imported
  Untouched by this change, still importing it: `billing/invoices.py`
  Do: Restore the file, or update every importer in the same change.
- **warn**: Modules `billing`, `util` now depend on each other
  Because of the new dependency `util` → `billing`, 1 import (for example `util/tax.py` imports `billing/invoices.py`).
- **warn**: 2 new files that nothing reaches
  Files: `billing/helpers.py`, `util/tax.py`
- **warn**: 1 changed file nobody active maintains
  Files: `legacy/rates.py`
  Do: Have a human who knows the code look before merging, or assign an owner. A person has to decide this.
```

`--fail-on block` exits 1 for `dangling-import` only; `--fail-on warn` also for the warnings; the default never fails.
`--format json` gives the same findings with their evidence (`orphans`, `cycles`, `dependencies`, `dangling_imports`,
`dangling_references`, `unowned`, `changed_files`; `kind` is `change-check`) for an agent to act on.

`--format sarif` writes the same check as a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html)
log, for editors and services that already read that format. It is a rendering, not a second analysis: one finding
becomes one result, in the same order, under a fixed rule per kind (`tessri/dangling-import`, `tessri/new-orphan`,
…); `block`, `warn` and `info` become `error`, `warning` and `note`, and the observations (`new-dependency`,
`orphan-resolved`, `cycle-resolved`) are `kind: informational` with `level: none` rather than failures. The whole
finding, `files` and `needs_human` included, sits in the result's `properties["tessri/finding"]`, and the check's
`meta`, `change`, `summary` and `notes` in the run's `properties["tessri/check"]`, so the identity of the comparison
travels with the file. The evidence is file-level, so a location names a file and never a line: the first path of a
finding that still exists and stays inside the analysed root is the primary location, the others are related
locations, and a finding with no usable path has no location at all rather than an invented one. Paths are URI-encoded
relative to `originalUriBaseIds.TESSRI_ROOT`, the directory that was analysed. Nothing is uploaded or configured, and
no fingerprints are generated. Two limits to know before wiring it anywhere. First, GitHub code scanning rejects a
whole log that contains a result without a location (observed on a real upload, 2026-11-01), and `new-dependency`,
`cycle-resolved` and a cycle finding with no example file have none. For that consumer add `--locationless omit`: those
findings leave `results` and move whole into the run's `properties["tessri/locationless"].omitted`, which also
records their `count` and the `policy` in force, so nothing is dropped and nothing gets an invented location. The
default `keep` leaves them in `results`, and `--fail-on` counts findings, not displayed results, so the exit code is the
same under both. Second, a check compares one change with one base, so feeding it into a persistent alert category can
make an old repository-wide problem look fixed when a later change simply did not touch it. `--fail-on` keeps its
meaning: with `block` the exit code is 1 and the document is still complete. Copyable shell and Python recipes for CI
artifacts, test selection and gates are in [docs/workflow-recipes.md](../workflow-recipes.md).

How much the warning about a name left behind is worth was tried on a year of one repository's history with
`tools/deletions.py`, which replays every change that deleted or moved a code file through `check` and follows each
name it left behind through the later commits. Of 23 such changes, four left a name. A test-suite script still ran a
deleted example (fixed the same day); a functional-test script still imports a module that was moved, and a design
document still names a worker's old module path (both still do); and an actor registry's string named a worker module
whose package `__init__.py` the change deleted while the module stayed, so the name still resolves and the `__init__.py`
run on the way only counted as named: a false alarm, listed under limits. Two other false alarms the
same trial showed, a module turned into a package and `setup.py` read as a dotted name, are gone. Four names on one
repository is a small number, so run it on yours:

```bash
python3 tools/deletions.py path/to/repository --days 365
```

Only what static imports show is compared, apart from `dangling-reference`, which reads the names of files in configs,
strings and documentation and says so; a clean result is not proof that nothing else depends on the change, and a
`block` is certain only for importers the change left untouched. Both sides are cut into modules the same way, so a
file added or removed cannot move a boundary and create a dependency that is not there. A file git sees as moved (its
default similarity threshold) is one file under its new name on both sides: the summary counts it under `moved`, its
row carries the old path as `from`, its lines are the edits made on the way, and a renamed package keeps its cycles,
dependencies and orphans instead of reporting them gone and new again. A moved file that an untouched file still
imports under its old name is a `dangling-import`, with `moved_to` beside the old path. A module turned into a
package (`x.py` moved into `x/`, with an `x/__init__.py` that takes its place), or the reverse, keeps its import name,
so the files that import or name `x` are not dangling. A move git does not recognise,
or one not yet added to the index, is still a deletion and an addition. Files the analysis does not read (symlinks,
submodules, anything above the size limit, anything excluded) are not part of either side.

`tessri brief --since main` puts this and `triage` on one page from one analysis, with the commits and uncommitted
files the evidence covers and the checks you ran: [the review brief](brief.md).
