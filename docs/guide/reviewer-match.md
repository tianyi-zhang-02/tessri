# The reviewer match: how "who can look" was tested

`tessri triage` and `tessri brief` end their first section with a sentence: *Who can look, other than the authors:*
and up to three names, the people who maintain the changed files and are still active. That is a claim about people,
so it is tested against people: on a repository's own pull requests, do the names match who actually reviewed?
`tools/reviewer_match.py` runs the test on any repository on GitHub; this page is its method and its output on one.

```bash
python3 tools/reviewer_match.py collect owner/name path/to/checkout --limit 300 --out pulls.json   # through gh, signed in
python3 tools/reviewer_match.py score pulls.json path/to/checkout                                   # offline from here
python3 tools/reviewer_match.py score pulls.json path/to/checkout --format json --out reviewers.json
```

## What is measured

**The pull requests.** `collect` reads the merged pull requests of the repository, newest first, through the `gh`
command, and keeps those whose merge commit the local checkout holds: their reviews, the reviewers GitHub lists as
requested, and the git identities behind their commits. A review in any state (approved, changes requested, a
comment) counts as having looked; the pull request's authors, bots and service accounts do not count as reviewers.

**The offer.** For each pull request, `score` moves a detached worktree to the merge commit and runs the triage of
the change against the commit's first parent, with the clock set to the merge time, so ownership and activity are
what git knew when the change was merged and nothing from after it is read. Triage's reviewer list is the offer: up to
three people, the authors apart. Two baselines are offered the same way from git alone: the people who committed most
to the changed files in the 365 days before the merge, and the people who committed most to the whole repository in
the 90 days before it. A fourth comes from the review data git does not hold: the people who reviewed most often among
the pull requests merged before this one, once that history holds twenty review slots.

**The match.** GitHub logins are matched to git names through the names and addresses on the pull requests' commits
and the profiles' names, compared without case or punctuation; an offered name that matches no login is dropped from
the offer. A method is judged on the pull requests where it offers anyone, someone other than the authors reviewed,
and the change touched a code file: triage ranks code files, so on a change of documents or configs no method has
anything to go on. Precision is the share of offered people who reviewed; recall the share of reviewers who were
offered; hit@1 whether the first name reviewed; any hit whether at least one offered name did.

## The result on one repository

The public `nemo-rl` repository, its newest 300 merged pull requests, read on 2026-11-13:

```text
Tessri reviewer match on NVIDIA-NeMo/RL (300 merged pull requests, 2026-09-23 to 2026-11-14)

300 scored; 253 had a reviewer other than the authors (bots and service accounts apart), 1.13 per pull
request; 54 changed no code file and are left out, so 213 are judged. A method offers up to 3 people, the
authors apart, and is judged where it offers anyone.

Method                                            offered on  precision  recall  hit@1  any hit
triage: active holders of the changed files       195 of 213       0.17    0.33   0.18     0.41
committers to the changed files, last 365 days    199 of 213       0.17    0.37   0.27     0.45
busiest committers repo-wide, last 90 days        213 of 213       0.12    0.29   0.16     0.37
most frequent reviewers before this pull request  199 of 213       0.28    0.68   0.44     0.82

Who reviews: 42 people took a review slot; the two most frequent took 31% and 23% of the slots, and 56% of the
judged pull requests were reviewed only by the three most frequent. Where git names the people behind the
changed files, triage and the plain committer count hit on different pull requests: both 56, triage only 24,
committers only 33, neither 100.

Against the reviewers GitHub had requested (not yet reviewed when read; a weaker truth):

Method                                          offered on  precision  recall
triage: active holders of the changed files       56 of 59       0.15    0.27
committers to the changed files, last 365 days    58 of 59       0.11    0.20
busiest committers repo-wide, last 90 days        59 of 59       0.07    0.10

Of triage's offers, 45 (18 distinct names) matched no login and were dropped; the JSON names them.
```

Read it this way:

- **Naming the people behind the files beats naming the busiest people.** Both file-level offers hit a reviewer more
  often and more precisely than the repository's most active committers. That is the capacity question the brief
  asks, and it is worth asking.
- **Ownership does not beat a plain count.** Triage's list, which weighs each person's share of a file's history with
  a one-year half-life and keeps only active people, is no better than the people who committed to the same files in
  the last year, and on the first name it is worse. The two agree on the first name about half the time and hit on
  different pull requests; recency matters more than share for this question. That is a reason to change how the
  list is ranked, once another repository says the same.
- **Who reviews is mostly a role.** Two people took more than half of the review slots, and most pull requests were
  reviewed only by the three most frequent reviewers, so the strongest predictor is the one git cannot see. The
  sentence in the brief, *Git cannot see who reviewed; these are the people who maintain the changed files*, is the
  right caveat, and "reviewed" is a proxy for "able to look", not the thing itself.
- **Against the requested reviewers, triage's list is the best of the three.** The people GitHub had asked to review
  are closer to "who should look" than to "who got to it", and on that truth the ownership list leads, on a smaller
  set.

## What it does not measure

- One repository, and the newest 300 of its pull requests; a repository that assigns reviewers by file owner, or one
  with many reviewers per change, will look different.
- Whether the reviewer was the right one: a review by whoever was free counts as much as one by the person who knew
  the code. Review quality and time to review need data the API does not give.
- Identities: logins are matched by name and address, so a person whose commits carry a different name than their
  profile is dropped from the offer, which lowers the offers more than the baselines, since those are filled from the
  names that do match.
- The requested reviewers are read at collection time, after the fact, so the list GitHub shows is what was still
  pending, not everyone who was ever asked.

## Run it on yours

`collect` needs the GitHub command line signed in and a checkout that holds the merge commits (a fetch of the default
branch is enough); `score` runs offline from the collected file and never touches the checkout: the worktree it moves
lives in a temporary directory and is removed afterwards. `--limit` picks how many of the newest pull requests,
`--base` the branch they were merged into, `--k` how many names a method offers. If the plain count beats triage on
your history too, open an issue with the JSON; the ranking is not configurable, on purpose, so the same brief says the
same thing everywhere, and it changes when the evidence says so.
