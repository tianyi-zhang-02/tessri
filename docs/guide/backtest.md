# The backtest: how the order and the graph were tested

`tessri triage` orders the files of a change by recent activity and then by the size of the change, and
`tessri impact` treats the files one import away as the review set. Both are claims about what happens next, so
both are tested on history rather than assumed. `tools/backtest.py` runs the test on any repository; this page is
its method and its output on one.

```bash
python3 tools/backtest.py path/to/repository --months 12                   # from a checkout of Tessri
python3 tools/backtest.py path/to/repository --format json --out backtest.json
```

## What is measured

**The order.** A change is one commit on the first-parent line of the branch: on a branch that squashes or rebases
that is every commit, and a merge commit counts as the whole of what it merged. A row is one code file a change
touched, scored with what git knew when the change landed: the commits that touched the file in the 90 days before
it, how many of those were fixes or reverts (by the subject rule `triage` uses: `fix`, `fixes`, `bugfix`, `hotfix`,
`revert`), the lines the change moved in it, and how many files imported it in the tree at the month's start. The
outcome is whether a commit whose subject says fix or revert touched the file within the following 30 days. Nothing
from after a change goes into its score; the last 30 days of history are not scored because their outcome is not
known yet, and neither are the first 90, which have no full window of activity before them.

Each order is judged by its AUC: the probability that a file later fixed is sorted above one that was not, ties
counting half, so 0.5 is chance and 1.0 is perfect. It is given pooled over every row, as the mean over the months,
as the number of months in which the order beat "size", and within a change, the mean over the changes that had
both a file later fixed and one not, which is the question `triage` actually answers.

**The graph.** For each month the tree before the month's first change is analysed, and every pair of code files
(tests apart) falls in one class: one import statement apart in either direction, two apart, in the same directory
with no import between them, or unrelated. A pair co-changed when one change of the month touched both files; a
change touching more than 50 code files is left out. The rate of each class is compared with the rate of the
unrelated pairs.

## The result on one repository

The public `nemo-rl` repository at commit `bf33dd52e`, which squashes every pull request; read on 2026-11-09, in
twelve seconds:

```text
Tessri backtest of nemo-rl at bf33dd52e (history 2025-03-18 to 2026-08-26, 1,370 changes on the first-parent line)

Rows: 3,981 code files touched by 895 changes in 12 months (2025-08 to 2026-07); the outcome, a fix or revert
commit touching the file within 30 days, holds for 32% of them. Activity is commits in the 90 days before the
change; a deleted file is left out; a moved file counts under its new name.

Order                            pooled AUC  mean of months  ahead of size  within a change (changes)
activity, then size (triage)           0.79            0.78       11 of 12                 0.81 (314)
size                                   0.52            0.51              -                 0.48 (314)
activity                               0.79            0.77       11 of 12                 0.79 (314)
fixes, then activity, then size        0.78            0.76       11 of 12                 0.79 (314)
dependents, then size                  0.62            0.58       10 of 12                 0.58 (314)

Pairs of code files (tests apart) in the tree at each month's start, and whether one change of the month
touched both; 0 changes touching more than 50 code files left out.

Pairs                pairs  co-changed    rate  x unrelated  over the months
one import apart     6,432       1,026  15.95%         18.3      8.1 to 56.5
two imports apart   35,839       2,679   7.48%          8.6      4.3 to 35.1
same directory       2,688          50   1.86%          2.1       0.0 to 9.3
unrelated          169,197       1,473   0.87%          1.0       1.0 to 1.0
```

Read it this way:

- **Activity is the signal.** Files ordered by recent commits are where the next fix lands: 0.79, against chance
  for the size of the change (0.52), in eleven of twelve months, and 0.81 within a change, where size is below chance
  (0.48). Size only breaks ties.
- **Fix history adds nothing.** Putting the files with recent fixes first scores 0.78, no better than activity alone,
  so `triage` shows `fixes_90` and does not sort by it.
- **Dependents are a weaker signal** (0.62), so they stay context: what a mistake could reach, not how likely one is.
- **One import apart is the review set.** Those pairs changed together 18 times as often as unrelated pairs, two
  imports apart 9 times, and the same directory with no import between them twice. That is why `impact` and `triage`
  count dependents at one and two hops, and why "nearby" is not "related".

The month-by-month ratios swing (8 to 57 for one import apart) because the unrelated rate is small and a quiet month
makes it smaller; the pooled number is the one to quote.

## What it does not measure

- Severity and cost: an outcome is any fix or revert touching the file, a typo as much as an incident, and a
  repository that does not write `fix:` in its subjects shows no outcomes at all.
- Capacity: who was able to look, and whether a file with no active owner is riskier, need review or incident data
  that git does not hold. `triage` shows ownership because it answers who can look, not where trouble lands.
- Other repositories: one history is a hint, not a proof. An earlier run on the same repository, with a slightly
  different method and scripts that were never published, reached the same conclusions (0.72 against 0.64 for the
  order); this script replaces it.
- Dates are commit dates, so in a repository that merges without rebasing a commit can count as activity a little
  before it landed; and a moved file's earlier history stays under its old name, unlike in `triage`, so it looks
  quieter than it was.

## Run it on yours

Point the script at any repository with a year of history. `--rev` picks the branch, `--window` and
`--active-days` the two windows, `--months 0` scores every month, and `--no-graph` skips the monthly analyses, which
cost a few seconds each on a few thousand files and are what the dependents order and the pairs table need. If size
beats activity on your history, the order is wrong for you: open an issue with the JSON. The order is not
configurable, on purpose: a knob would make the same brief say different things in different places.
