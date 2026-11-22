# Why there is no risk score

Tessri orders the files of a change by two things, how many commits touched each in the last 90 days and how much the change touches it, and shows everything else as context. We did not start there. We started with a risk score, and it lost its own backtest. This is the story of that score, of the test that replaced it, of what the test found on three repositories, and of the one claim that came out stronger than we expected.

![How well each order predicts a fix within 30 days, as AUC over twelve months of three repositories' history, where 0.5 is random: Tessri's order against the size of the change, 0.79 against 0.52, 0.64 against 0.54, 0.66 against 0.57.](figures/backtest.svg)

## A score that reads well

The first design had a number per file: recent change, times blast radius, times knowledge gap. Recent change was the commits of the last 90 days. Blast radius was how many files reach the file through imports. Knowledge gap was whether the change came from someone outside the file's owners, or whether the file had no active owner at all. Multiply the three and a file that was just touched, that half the system depends on, and that nobody who knows it is watching floats to the top. It is the kind of number that reads well in a review tool: one column, sorted, done.

It is also a claim about the future. A risk score says *this is where the next problem is*. A claim like that can be checked against history, and the first thing we did once the score existed was check it.

## The first test, and what it cost us

The first backtest ran on 30 October 2026, on a large public repository with squashed pull requests, over twelve monthly snapshots with nothing read from after each snapshot. The question was the one a reviewer asks: of the files this month's changes touched, which ones did a fix touch within the next thirty days? At the file level and at the level of a whole change, the composite score ranked below every one of its parts. Recent commits alone did better. Even the size of the change did better. Adding blast radius and ownership to a model that already had activity and size added nothing out of time.

That run has a second lesson in it, about tools rather than numbers. The scripts lived in a working directory that did not survive the week, and with them the exact figures. We know the conclusion and the method; we do not have the table, so this post does not quote it. The fix was to make the test part of the repository: `tools/backtest.py` runs on any checkout, prints one table, and the guide quotes only what that tool prints. Every number below is reproducible with one command.

## The test as it stands

The script walks the first-parent history month by month. For each month it takes the files the month's changes touched, orders them with only what git knew at the start of the change, and then looks thirty days ahead for a commit whose subject says it fixes or reverts something. The measure is the area under the curve, the probability that a file which did get a fix is ranked above one that did not; 0.5 is a coin toss, 1.0 is perfect. Five orders are scored side by side, and the same months are scored once more *within a change*, where only the files of one change compete with each other, because that is the question the triage page actually answers. The analysis of the tree runs once per month, so that the dependents order and the co-change table use the import graph as it was then.

This is the output on the large repository, read on 9 November 2026:

```text
Tessri backtest of nemo-rl at bf33dd52e (history 2025-03-18 to 2026-08-26, 1,370 changes on the first-parent line)

Rows: 3,981 code files touched by 895 changes in 12 months (2025-08 to 2026-07); the outcome, a fix or revert
commit touching the file within 30 days, holds for 32% of them.

Order                            pooled AUC  mean of months  ahead of size  within a change (changes)
activity, then size (triage)           0.79            0.78       11 of 12                 0.81 (314)
size                                   0.52            0.51              -                 0.48 (314)
activity                               0.79            0.77       11 of 12                 0.79 (314)
fixes, then activity, then size        0.78            0.76       11 of 12                 0.79 (314)
dependents, then size                  0.62            0.58       10 of 12                 0.58 (314)
```

Three things are in that table. Activity is the signal: 0.79 against 0.52 for the size of the change, ahead in eleven of twelve months, and 0.81 within a change, where size is below chance. Fix history, the thing a risk score would weigh most, adds nothing once activity is in: 0.78. Dependents, the blast radius, score 0.62 on their own, well below activity. The composite multiplied a strong signal by two weak ones and a constant, and the weak ones dragged it down.

## Two more repositories

One history is one history. The same script ran on a small, old repository maintained by a few core developers and merged with merge commits, and on a TypeScript monorepo with a small core team and squashed pull requests. The order held on both, by less:

| Repository | Activity then size | Size | Ahead of size | Within a change |
|---|---|---|---|---|
| large, squashed, a company's team | 0.79 | 0.52 | 11 of 12 | 0.81 vs 0.48 |
| small, old, merge commits | 0.64 | 0.54 | 6 of 10 | 0.62 vs 0.47 |
| TypeScript monorepo, small core team | 0.66 | 0.57 | 8 of 12 | 0.64 vs 0.51 |

The small repository explains its own margin: only 11% of its rows had no commit in the 90 days before the change, against 28% on the large one. Where everything is recently touched, recency separates less. It also let us test the label itself, because that project records a bug fix as a changelog fragment rather than in the commit subject: with the project's own label the order scores 0.66 against 0.53 over twelve months and 0.70 against 0.62 over 36. On the TypeScript repository fix history came out a point ahead of activity, 0.67 against 0.66, for the first time; one point on one repository of three is not a reason to reorder, so it is shown and does not rank.

## What came out stronger

The test was built to check an order. It also checked the one structural claim the tool makes everywhere: that the files one import away from a change are the ones to look at. For every month, the script takes every pair of code files in the tree and asks whether one change of the month touched both. On the large repository, 16% of the pairs one import apart co-changed in a month, against 7.5% two imports apart, 1.9% for pairs that share a directory without an import, and 0.9% for unrelated pairs. On the small repository the rates are 4.6%, 0.8%, 0.15% and 0.06%; on the TypeScript monorepo 0.69%, 0.14%, 0.00% and 0.02%. The multipliers do not travel between repositories, since the unrelated rate they divide by is tiny on a small tree, but the first class is far ahead on all three, and a directory is not a relationship. That is why `tessri impact` treats the direct dependents as the review set, and why the triage page looks one or two imports out and no further.

## What the page does with all this

`tessri triage` orders by commits in the last 90 days, breaks ties by the lines of the change, and prints the rest where a reader can weigh it: the fixes and reverts of the last 90 days, the dependents within two imports, the people who maintain the file, and the functions and classes the change touched. There is no score, and the page says so in its last section: the order says where trouble tends to land, not that this change is wrong.

## What the test does not measure

Severity: a fix is a fix, a typo as much as an outage. Capacity: who was able to look is a question about people, which this test cannot see; it has its own test against who actually reviewed. The label: a repository that never writes `fix:` in a subject shows no outcomes at all. And three histories are a hint, not a proof; they already disagree on the size of the effect.

```bash
python3 tools/backtest.py path/to/repository --months 12
```

[The backtest](../guide/backtest.html) has the method in full, the output on all three repositories including the 36-month runs, and the options.
