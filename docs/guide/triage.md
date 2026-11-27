# Triage a change

Which files of a change should a person look at first, what outside the change can it ripple into, and who is able
to look?

```bash
tessri triage --since main                 # a branch, judged from where it parted from main, plus uncommitted work
tessri triage                              # the same against the default branch: origin/HEAD, else origin/main, origin/master, main or master
tessri triage --since HEAD                 # only uncommitted work
tessri triage --since main --format json   # for an agent
```

Given a change, which of its files should a human look at first, what outside the change can it ripple into, and who
is able to look? The answer is a ranked list of the changed code files, each with why it is there, what imports it, and
who maintains it, followed by the code outside the change that imports the changed files (one and two steps away),
the tests that reach them, and the people who maintain them other than the authors.

```text
$ tessri triage --since main
# Change triage: demo

`main` (base 8f9c528cc) to HEAD fc97f1a93. 4 code files changed, **21** lines, in 2 areas; 2 other files (2 lines of config, docs and the like) not ranked.

- **1** file was fixed or reverted in the last 90 days
- **1** file has no active owner: nobody who maintains the code has committed lately
- **1** file is maintained by nobody but the author
- code outside the change that imports it: **1 file** directly, 0 files through one more step
- **1** test file reaches it
- **0** of the 5 definitions it touched are named in a test that reaches the file

Look at these first:

| # | File | Why | This change | Owners | Imported by | Flags |
|---:|---|---|---|---|---:|---|
| 1 | `core/a.py` | 3 commits in 90 days, 2 of them fixes or reverts | +4 -0 | Alice Adams 100% | 2 | author is not among the owners |
| 2 | `util/c.py` | quiet since 2026-01-03 | +8 -0 | Bob Brown 100% (silent 300d) | 1 | no active owner; author is not among the owners |
| 3 | `core/d.py` | new file | +6 -0 | - | 0 | new file; orphan: nothing reaches it |
| 4 | `core/b.py` | quiet since 2026-04-13 | +2 -1 | Alice Adams 100% | 1 | author is not among the owners |

What changed in them, by definition:

- `core/a.py`: added `carol`; module-level code
- `util/c.py`: added `c2`, `c3`; module-level code
- `core/d.py`: added `d`
- `core/b.py`: changed `b`; module-level code

Who can look, other than the authors: Alice Adams (2 files, 5 commits in the last year). Git cannot see who reviewed; these are the people who committed to the changed files in the last year, most commits first, then the people who maintain them.

Only the author maintains: `util/c.py`

Not in the change, but importing it (by area):

| Area | Directly | One more step |
|---|---:|---:|
| `.` | 1 | 0 |

Tests that reach it, nearest first: `tests/test_a.py`

By name, in the tests that reach their file: `carol`, `c2` and `c3` are named in none; `d` and `b` were not searched, being too short, private or too common.
```

**How the order is decided.** Files are ordered by how many commits touched them in the last 90 days, then by how much
this change touches. We tested that rather than assuming it, and the test is in the repository: `tools/backtest.py`
scores the files every change of the last twelve months touched with what git knew when the change landed, and asks
which of them a fix touched in the following 30 days ([the backtest](backtest.md) has the method and the full output).
On a large repository the order scored an AUC of 0.79, against 0.52 for "largest diff first", and beat it in
eleven of twelve months; on a small one 0.64 against 0.54, and 0.66 against 0.53 with that project's own bug-fix
label, so the order holds there too, by less; on a TypeScript monorepo 0.66 against 0.57, ahead in eight of twelve
months. Two things we expected to help did not, or barely, so they are shown but do not move a file: knowing which
of those commits were fixes or reverts (`fixes_90`) added nothing beyond activity on two repositories and a point on
the third, and how many files import it scored 0.62, 0.59 and 0.56 on its own. The first describes trouble that
already happened, the second what a mistake could reach; ownership is shown because it describes who can catch it,
which a "will it need a fix" score does not measure. Three repositories are a hint, not a proof; the script runs on
yours.

Under the table, *What changed in them, by definition* names the functions and classes the change touched in each
file, from the diff's hunks and the language's definitions: a definition whose name is new is *added*, one whose name
is gone is *removed*, the rest a hunk touches is *changed*, named the way a reader names it (`Shape.area`), and lines
outside every definition are *module-level code*; a renamed function is a removal and an addition. Each row carries
it as `symbols` (`changed`, `added`, `removed`, `module_level`). Python is read with its own parser. JavaScript and
TypeScript are read by a scanner that tells strings, templates, comments and regex literals from code and matches
braces: functions, classes and their methods, a variable or export assigned a function, a class or an object literal
and that object's methods (`nodeOps.insert`), and interfaces, type aliases, enums and namespaces; a callback has no
name, so what it holds is named by the definition around it, except a test's (`describe`, `it`, `test`), which its
title names (`ref.should unwrap nested values`). A file in another language, or one that cannot be read
(Python that does not parse, JavaScript whose braces or literals never close), says so there instead of guessing.

The last line joins those definitions with the tests: for each one, the candidate tests that reach its file and use
its name in their code. A test's code is read with the language's own token reader (Python's `tokenize`, the
JavaScript reader), so a name in a string or a comment does not count, and only the last segment of a name is
searched (`Shape.area` → `area`), when it is three characters or more, not private by convention (`_helper`,
`#secret`: a test naming one is the exception, so being named by none is no finding) and not a name every module may
have (`default`, `constructor`, dunder methods); the rest are listed as not searched rather than said to be named by
nobody. A name two changed files share is told apart by its file. A definition that was removed but is still named by a test gets its own clause. Each row carries the
result as `symbols.named_in` (definition → tests, nearest first) and `symbols.unsearched`, and the summary counts
them under `definitions`. A name in a test is a mention, not an assertion: the test may use the name without
checking what it does, and a test can exercise a definition without naming it, through a caller, a fixture or a
dynamic call; test files in the change and deleted files are not searched.

After it, when there are any, one sentence names the files that usually change with the changed files and are not in
this change: "Usually changed together, not in this change: `docs/guide/brief.md` (with `tessri/brief.py` 9 of 10;
`tessri/triage.py` 6 of 10 commits), `tests/test_brief.py` (with `tessri/brief.py` 5 of 10 commits)." For each
changed code file, the commits that touched it in the last 365 days up to the base are read (the latest 50, under
the name each file has now; merge commits, bulk commits of 300 files or more and ignored authors apart), and a
*companion* is another file in at least half of them, three at least, that still exists and that the change leaves
untouched. Each row carries `companions` (`commits` in the window, `window_days`, `usually_with` with `together`),
the JSON a `companions` list grouped by companion (`with`: the changed file, `together`, `of`), surest first, and the
summary the count. On this repository it names the guide pages, the skill and the README that an edit to `brief.py`
usually comes with; on a repository with a short history, the test file beside the module. It is a prompt to check
whether the file should have changed too, not a rule that it must, and a change that brings its companions has none
to name.

History is read up to the base of the change, so the change's own commits count neither as activity nor as making its
author an owner. A file the change adds has no history and sorts by its size; a file it moves keeps the history of its
old name (`from` names it, the flag reads `moved`) and its lines are the edits made on the way. *Who can look* lists the
people, other than the authors (the commits of the change, or whoever `git config user.name` is when the work is
uncommitted), who committed to the changed files in the last year, most commits first, then those who hold a share of
the files' history without a commit this year; git cannot see who reviewed. The order comes from holding the list
against who did review, on two repositories' pull requests (a third records too few reviews on GitHub to judge;
[the reviewer match](reviewer-match.md)): ranked by share
of the files' history it did not beat a plain count of who committed to the same files in the last year on either
repository, so the count ranks and the share orders the rest. The same test found that the repository's busiest people
lose to the file-level list on a large repository and beat it on a small one, where four people write and review most
of the code, so the page adds *the repository's regulars* of the last 90 days, with their share of its commits, when
they are not already named (merges count: in a merge-commit workflow the person who merged is often the one who
reviewed); and that on both repositories half the reviewing was done by two people, whom git cannot name. Dependents are static imports only: importing `a.b.c`
does not make a file depend on the package `a`, and dynamic loading and consumers outside the repository are invisible.

`tessri brief --since main` puts this and `check` on one page from one analysis, with the commits and uncommitted
files the evidence covers and the checks you ran: [the review brief](brief.md).
