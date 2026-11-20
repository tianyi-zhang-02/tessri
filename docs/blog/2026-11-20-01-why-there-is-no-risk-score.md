# Why there is no risk score

Tessri orders the files of a change by two things, how many commits touched each in the last 90 days and how much the change touches it, and shows everything else as context. The score we tried first did not survive its own backtest. This is how the order was chosen, and how to run the same test on your history.

![How well each order predicts a fix within 30 days, as AUC over twelve months of three repositories' history, where 0.5 is random: Tessri's order against the size of the change, 0.79 against 0.52, 0.64 against 0.54, 0.66 against 0.57.](figures/backtest.svg)

## The score that looked right

The first idea was the obvious one: a file is risky when it changed recently, when a lot depends on it, and when nobody who knows it is around. Multiply the three and you have a number that feels like risk. It reads well on a page. It is also a claim about the future, so it can be tested on the past.

## The test

`tools/backtest.py` walks a repository's history month by month. At the start of each month it takes the files the month's changes touched, ranks them with only what git knew at that moment, and then looks thirty days ahead: did a commit that fixes or reverts something touch the file? A good order puts those files first. The measure is the area under the curve, AUC, where 0.5 is a coin toss and 1.0 is perfect. Nothing from after the change is read, so the test cannot cheat.

## What came back

The composite score did not beat its parts. Recent activity alone predicted the later fixes about as well as anything simple, and better than the size of the change, which is what a reviewer sees first in a diff. Adding how many files import the changed one made the order worse, not better: dependents say what a mistake could reach, not whether one was made. Fix history, the files that were patched before, added nothing beyond activity on two repositories and a point on the third.

So there is no score. `tessri triage` orders by activity, breaks ties by the size of the change, and prints the rest where a reader can weigh it: the fixes of the last 90 days, the dependents within two imports, the people who maintain the file. The page says where trouble tends to land, not that this change is wrong.

## What survived

One claim did better than expected. Files one import apart change together far more often than files that merely share a directory: in a month, 16% of such pairs on the large repository, 4.6% on the small one, 0.69% on the TypeScript monorepo, against 1.9%, 0.15% and 0.02% for the directory. That is why `tessri impact` treats the direct dependents as the review set and why the brief looks one or two imports out, not further.

## Three repositories, not a proof

The order held on a large, young repository that squashes every pull request, on a small, old one maintained by a few core developers, and on a TypeScript monorepo, by different margins each time. Three histories are a hint. The script runs on any repository with a year of history:

```bash
python3 tools/backtest.py path/to/repository --months 12
```

[The backtest](../guide/backtest.html) has the method, the full output on all three and what the test does not measure.
