# The reviewer match: how "who can look" was tested

`tessri triage` and `tessri brief` end their first section with a sentence: *Who can look, other than the authors:*
and up to three names, the active people who committed to the changed files in the last year, most commits first, then
those who hold a share of the files' history. That is a claim about people, so it is tested against people: on a
repository's own pull requests, do the names match who actually reviewed? The test was run first on the list as it was,
ranked by share of the files' history; what it found changed the order, and the last section measures the list as it
now ships.
`tools/reviewer_match.py` runs the test on any repository on GitHub; this page is its method and its output on two: a
large repository with a company's team behind it, and a small one maintained by a handful of core developers.

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
the 90 days before it. Since the page started naming *the repository's regulars*, those are scored as an offer too.
The last method comes from the review data git does not hold: the people who reviewed most often among the pull
requests merged before this one, once that history holds twenty review slots.

**The match.** GitHub logins are matched to git names through the names and addresses on the pull requests' commits
and the profiles' names, compared without case or punctuation; an offered name that matches no login is dropped from
the offer. A method is judged on the pull requests where it offers anyone, someone other than the authors reviewed,
and the change touched a code file: triage ranks code files, so on a change of documents or configs no method has
anything to go on. Precision is the share of offered people who reviewed; recall the share of reviewers who were
offered; hit@1 whether the first name reviewed; any hit whether at least one offered name did.

## The result on a large repository

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

## The result on a small repository

The public `pytest` repository, the 300 merged pull requests most recently updated, read on 2026-11-15: 288 of them
were merged in the twelve months before, 12 are older ones that were touched again; 89 were opened by bots, which is
why 134 changed no code file.

```text
Tessri reviewer match on pytest-dev/pytest (300 merged pull requests, 2022-03-21 to 2026-11-15)

300 scored; 277 had a reviewer other than the authors (bots and service accounts apart), 1.2 per pull request;
134 changed no code file and are left out, so 157 are judged. A method offers up to 3 people, the authors
apart, and is judged where it offers anyone.

Method                                            offered on  precision  recall  hit@1  any hit
triage: active holders of the changed files       147 of 157       0.30    0.46   0.30     0.58
committers to the changed files, last 365 days    148 of 157       0.27    0.52   0.33     0.61
busiest committers repo-wide, last 90 days        157 of 157       0.28    0.60   0.43     0.71
most frequent reviewers before this pull request  148 of 157       0.36    0.79   0.36     0.87

Who reviews: 25 people took a review slot; the two most frequent took 30% and 24% of the slots, and 65% of the
judged pull requests were reviewed only by the three most frequent. Where git names the people behind the
changed files, triage and the plain committer count hit on different pull requests: both 73, triage only 13,
committers only 17, neither 54.

Against the reviewers GitHub had requested (not yet reviewed when read; a weaker truth):

Method                                          offered on  precision  recall
triage: active holders of the changed files       20 of 22       0.20    0.50
committers to the changed files, last 365 days    21 of 22       0.22    0.50
busiest committers repo-wide, last 90 days        22 of 22       0.16    0.36

Of triage's offers, 39 (18 distinct names) matched no login and were dropped; the JSON names them.
```

Read it this way:

- **The busiest people win here.** In `pytest` four core developers write most of the code and review nearly all
  of it, so the three busiest committers of the last 90 days are the reviewers whatever the files: recall 0.60 and
  a hit on 71% of the pull requests, against 0.46 and 58% for the ownership list, which is the more precise of the
  two (0.30 against 0.28). On the large repository the busiest list lost to both file-level lists; the small one
  reverses that. Where a few people review everything, the right offer is those few, whom git can see as the
  busiest committers; the brief does not do that yet.
- **Ownership still does not beat the plain count.** Precision 0.30 against 0.27 for the ownership list, recall and
  hits a little behind (0.46 against 0.52, 58% against 61%), and the two hit on different pull requests again (73
  both, 13 and 17 one only). Two repositories now say the same thing: recency matters more than share, and the
  ownership list buys a little precision for a little recall.
- **Who reviews is a role here too.** The two most frequent reviewers took 30% and 24% of the slots (31% and 23%
  on the large repository), 65% of the judged pull requests were reviewed only by the three most frequent (56%),
  and the list of who reviewed most so far hits on 87% (82%). Two repositories run quite differently give nearly
  the same numbers.
- **Against the requested reviewers** (22 pull requests, too few to lean on) the two file-level lists tie at a
  recall of 0.50 and the busiest list trails at 0.36, as on the large repository.

So the second repository confirms the plain count and the role, and overturns the busiest-people result: the
ownership list beats the repository's regulars only where reviewing is spread beyond a few. The ownership list had
now failed to beat a plain count twice, so the list was reranked by recency, with the share ordering the rest, and the
page started naming the regulars; the number to watch was precision, the one thing the ownership list won. The next
section is the same test on the list as it ships.

## The result on the list as it ships

The two sections above tested the list ranked by share of the files' history. On 2026-11-18 the order changed to what
they recommended: the people who committed to the changed files in the last year come first, most commits first, those
who hold a share of the files' history without a commit this year follow, and the page started naming *the
repository's regulars*, the busiest committers of the last 90 days, merges included, when they are not already named.
This is the same test on the list as it ships. The small repository's pull requests are the ones collected on
2026-11-15; the large repository's were collected again on 2026-11-18, so its set moved by five days and its numbers
are close to, not the same as, the first run's.

```text
Tessri reviewer match on pytest-dev/pytest (300 merged pull requests, 2022-03-21 to 2026-11-15)

300 scored; 277 had a reviewer other than the authors (bots and service accounts apart), 1.2 per pull request;
134 changed no code file and are left out, so 157 are judged. A method offers up to 3 people, the authors
apart, and is judged where it offers anyone.

Method                                            offered on  precision  recall  hit@1  any hit
triage: who can look                              155 of 157       0.28    0.48   0.30     0.59
committers to the changed files, last 365 days    148 of 157       0.27    0.52   0.33     0.61
busiest committers repo-wide, last 90 days        157 of 157       0.28    0.60   0.43     0.71
triage: the repository's regulars                 157 of 157       0.28    0.59   0.40     0.71
most frequent reviewers before this pull request  148 of 157       0.36    0.79   0.36     0.87

Who reviews: 25 people took a review slot; the two most frequent took 30% and 24% of the slots, and 65% of the
judged pull requests were reviewed only by the three most frequent. Where git names the people behind the
changed files, triage and the plain committer count hit on different pull requests: both 87, triage only 4,
committers only 3, neither 63.

Against the reviewers GitHub had requested (not yet reviewed when read; a weaker truth):

Method                                          offered on  precision  recall
triage: who can look                              21 of 22       0.22    0.50
committers to the changed files, last 365 days    21 of 22       0.22    0.50
busiest committers repo-wide, last 90 days        22 of 22       0.16    0.36
triage: the repository's regulars                 22 of 22       0.22    0.36

Of triage's offers, 63 (22 distinct names) matched no login and were dropped; the JSON names them.
```

```text
Tessri reviewer match on NVIDIA-NeMo/RL (300 merged pull requests, 2026-09-23 to 2026-11-18)

300 scored; 254 had a reviewer other than the authors (bots and service accounts apart), 1.12 per pull
request; 53 changed no code file and are left out, so 214 are judged. A method offers up to 3 people, the
authors apart, and is judged where it offers anyone.

Method                                            offered on  precision  recall  hit@1  any hit
triage: who can look                              198 of 214       0.17    0.39   0.29     0.47
committers to the changed files, last 365 days    197 of 214       0.17    0.39   0.29     0.46
busiest committers repo-wide, last 90 days        214 of 214       0.12    0.28   0.20     0.36
triage: the repository's regulars                 214 of 214       0.12    0.27   0.18     0.35
most frequent reviewers before this pull request  198 of 214       0.27    0.66   0.42     0.80

Who reviews: 42 people took a review slot; the two most frequent took 30% and 24% of the slots, and 55% of the
judged pull requests were reviewed only by the three most frequent. Where git names the people behind the
changed files, triage and the plain committer count hit on different pull requests: both 89, triage only 4,
committers only 2, neither 119.

Against the reviewers GitHub had requested (not yet reviewed when read; a weaker truth):

Method                                          offered on  precision  recall
triage: who can look                              62 of 63       0.11    0.20
committers to the changed files, last 365 days    62 of 63       0.12    0.22
busiest committers repo-wide, last 90 days        63 of 63       0.09    0.16
triage: the repository's regulars                 63 of 63       0.07    0.15

Of triage's offers, 23 (9 distinct names) matched no login and were dropped; the JSON names them.
```

Read it this way:

- **The reranked list matches the plain count and keeps a little of the share's precision.** On the large repository
  it offers on 198 of 214 pull requests (195 of 213 before): precision 0.17, recall 0.39, hit@1 0.29, any hit 0.47,
  against 0.17, 0.33, 0.18 and 0.41 for the share-ranked list on the first run and 0.17, 0.39, 0.29 and 0.46 for the
  plain count on this one; the two now hit on nearly the same pull requests (both on 89, one alone on 4 and 2). On the
  small repository it offers on 155 of 157 (147 before): 0.28, 0.48, 0.30 and 0.59, against 0.30, 0.46, 0.30 and
  0.58 before and 0.27, 0.52, 0.33 and 0.61 for the plain count; on the 148 pull requests where both offer, 0.29 and
  0.50 against 0.27 and 0.52, so the list trades a little of the count's recall for a little of the share's
  precision, and the seven pull requests it alone offers on, with people who hold a share but made no commit this
  year, are weak (any hit 0.29).
- **The regulars are the busiest-committers baseline, as the page names it.** Small repository 0.28, 0.59, 0.40 and
  0.71 against 0.28, 0.60, 0.43 and 0.71; large 0.12, 0.27, 0.18 and 0.35 against 0.12, 0.28, 0.20 and 0.36. The
  gap is the measurement: the page names three people and fills no slot when one of them matches no login, the
  baseline draws from twelve. Two things had to change to get there. Merges count: without them the regulars scored
  0.26, 0.52, 0.34 and 0.64 on the small repository, because in a merge-commit workflow the person who merged is
  often the one who reviewed. And a service account that commits to the large repository under a name ending in
  `-ci`, which the baseline's bot filter dropped and Tessri's did not, took the first slot on 158 of its 214 pull
  requests (hit@1 0.03); a name or address ending in `-ci` or `-bot` now counts as automation wherever Tessri reads
  history, so such an account owns nothing and is offered to nobody.
- **The role is unchanged.** The two most frequent reviewers took 30% and 24% of the slots on both repositories, the
  past reviewers hit on 80% and 87%, and on the large repository the gap between the best git-only offer (0.47) and
  them (0.80) is where the data git does not hold would have to come from.


## What it does not measure

- Two repositories, and 300 pull requests of each; a repository that assigns reviewers by file owner, or one with
  many reviewers per change, will look different.
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
