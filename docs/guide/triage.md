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

Look at these first:

| # | File | Why | This change | Owners | Imported by | Flags |
|---:|---|---|---|---|---:|---|
| 1 | `core/a.py` | 3 commits in 90 days, 2 of them fixes or reverts | +4 -0 | Alice Adams 100% | 2 | author is not among the owners |
| 2 | `util/c.py` | quiet since 2026-01-03 | +8 -0 | Bob Brown 100% (silent 300d) | 1 | no active owner; author is not among the owners |
| 3 | `core/d.py` | new file | +6 -0 | - | 0 | new file; orphan: nothing reaches it |
| 4 | `core/b.py` | quiet since 2026-04-13 | +2 -1 | Alice Adams 100% | 1 | author is not among the owners |

Who can look, other than the authors: Alice Adams (2 files). Git cannot see who reviewed; these are the people who maintain the changed files.

Only the author maintains: `util/c.py`

Not in the change, but importing it (by area):

| Area | Directly | One more step |
|---|---:|---:|
| `.` | 1 | 0 |

Tests that reach it, nearest first: `tests/test_a.py`
```

**How the order is decided.** Files are ordered by how many commits touched them in the last 90 days, then by how much
this change touches. We tested that rather than assuming it, and the test is in the repository: `tools/backtest.py`
scores the files every change of the last twelve months touched with what git knew when the change landed, and asks
which of them a fix touched in the following 30 days ([the backtest](backtest.md) has the method and the full output).
On one large repository the order scored an AUC of 0.79, against 0.52 for "largest diff first", and beat it in
eleven of twelve months. Two things we expected to help did not, so they are shown but do not move a file: knowing
which of those commits were fixes or reverts (`fixes_90`) added nothing beyond activity, and how many files import it
scored 0.62 on its own. The first describes trouble that already happened, the second what a mistake could reach;
ownership is shown because it describes who can catch it, which a "will it need a fix" score does not measure. One
repository is a hint, not a proof; the script runs on yours.

History is read up to the base of the change, so the change's own commits count neither as activity nor as making its
author an owner. A file the change adds has no history and sorts by its size; a file it moves keeps the history of its
old name (`from` names it, the flag reads `moved`) and its lines are the edits made on the way. *Who can look* lists the people
who maintain the changed files, excluding the authors (the commits of the change, or whoever `git config user.name` is
when the work is uncommitted); git cannot see who reviewed. That list was held against who did review, on one
repository's pull requests ([the reviewer match](reviewer-match.md)): it beats naming the repository's busiest people,
it does not beat a plain count of who committed to the same files in the last year, and most reviewing there was done
by two people whom git cannot name. Dependents are static imports only: importing `a.b.c`
does not make a file depend on the package `a`, and dynamic loading and consumers outside the repository are invisible.

`tessri brief --since main` puts this and `check` on one page from one analysis, with the commits and uncommitted
files the evidence covers and the checks you ran: [the review brief](brief.md).
