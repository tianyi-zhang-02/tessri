# What a change can reach

`tessri impact <path>` walks the dependency graph backwards from a file, directory or dotted package and lists what
can be affected, the tests that reach it, and who maintains the affected code, saying which kind of evidence each
step rests on.

```text
$ tessri impact util/helpers.py
Changing util/helpers.py  (1 file, 2 code lines) can affect:

- **3 code files** in **3 modules** (37.5% of the code), 1 of them directly (one followed edge away)
- **1 test file** reaching it (candidates to run, not runs), 0 directly
- code files by number of followed edges away: 1: 1, 2: 2
- edges followed, any number of steps: recognized dependency syntax, package files, and 0 references found in strings, dynamic loading or unclassified evidence; syntax and package files alone reach 3 code files and 1 test file

| Affected module | Files | Direct |
|---|---:|---:|
| `app` | 1 | 0 |
| `billing` | 1 | 0 |
| `core` | 1 | 1 |

Tests that reach it, nearest first: `tests/test_engine.py`
```

`impact` takes a file, a directory or a dotted package name and walks the dependency graph backwards, through
cycles without looping. With git history it also lists who maintains the affected code, which is who to tell or
ask for a review. `--hops 1` keeps only direct dependents. A package `__init__` is affected by any import
beneath it, because Python runs it.

`--report FILE` (repeatable) reads a test report the host wrote, JUnit XML as pytest `--junitxml`, jest-junit and
most CI systems produce it, and holds the candidate tests against it: the text marks each as passed, failed, skipped
or not run and says how many of them ran, and the JSON adds `tests.report` (`sources`, `cases`, `ran`, `passed`,
`failed`, `skipped`, `not_run`, `unmatched`). A candidate the report does not mention did not run, as far as the
report says; nothing is inferred from the candidates.

Every edge carries the kind of evidence it rests on, strongest first: `import` (recognized literal dependency
syntax names the file: a Python import statement; for JavaScript and TypeScript an `import`, `export ... from`,
`require()`, a literal `import()`, `new URL(...)` or a reference path), `package` (a parent `__init__.py` that
Python runs for such a statement), `dynamic` (a supported computed import, glob or `require.context` pattern
expands to the file), `string` (a dotted name or path in an ordinary string resolves to it) and `unknown` (an
analyzer from before this field reported the edge without saying why). When one pair has both an import and a
string, it is an import. A Python `import_module("pkg.mod")` with a literal argument counts as a `string`,
because the analyzer does not look at the call around the literal; a JavaScript `import("./x")` with a literal
is recognized syntax. The names describe evidence, not what runs.

By default `impact` follows every kind, as it always has, and says so. The `edges` block of the JSON carries
`policy`, `hops`, the `kinds` followed, `followed` and `excluded` counted by kind, `references` (the total and a
capped list of the string, dynamic and unknown edges met, with the cap stated), `unclassified` (such edges and
the analyzers that gave no provenance) and, under the default only, `imports_only`: what the narrower policy
would reach from the same seeds under the same hop limit. The text has one line for the same facts.
`--edges imports` follows `import` and `package` edges only; the string, dynamic and unknown edges met at the
frontier are counted and listed, not followed, and *direct* means one followed edge away under either policy. The
line names the hop limit it ran under, `at most N steps` or `any number of steps`.
Counts are per source/target pair met while expanding the walk, so they describe the frontier the walk saw, not
every such edge in the repository, and an excluded edge is never expanded. `depends_on` is the other direction,
the dependencies the target itself names, and never the result of the reverse walk: under `--edges imports`
only `import` and `package` edges count; under the default it is the set it always was, which for Python is
what import statements name and for JavaScript everything the scanner resolved, path strings and globs included.
Tests are listed because they reach the target; nothing here records what ran. Neither policy shows that a file
outside the result is unaffected.
