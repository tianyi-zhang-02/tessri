# One page to hand a change over

A change is done, by an agent or by a person, and someone else has to stand behind it. `tessri brief --since <base>` is the page that person gets: what the change is, where to look first, what it did to the structure, which tests reach it and which checks actually ran, and what needs a human. Each of its six parts carries one of the principles the tool is built on.

![The six parts of the page and the principle each carries: the scope line names the state the evidence describes; Look first orders by two things; the structure is compared on the graph alone; candidates are kept apart from what ran; what has no evidence needs a person; what it cannot see is said with its reason.](figures/brief.svg)

## Say which state the evidence describes

The first line names the base, the HEAD and, when there is uncommitted work, the files it is in, because a commit id does not identify uncommitted contents. The commits on the way appear with their authors' own subjects. The page never infers what a change was for from the files it touched; intent is the author's to state.

## Order by two things, show the rest

*Look first* is the triage order: commits in the last 90 days, then the size of the change, because that is what the backtest found hard to beat. Fix history, the dependents within two imports and the owners stand beside each row as context. Under the table, the people who can look, the authors apart, ordered by their commits to the changed files in the last year, and the repository's regulars when they are not already named.

## Compare the structure on the graph alone

*What it did to the structure* is `tessri check` on the same analysis: imports of deleted files, new cycles, new files nothing reaches, changed code nobody active maintains, each with what to do about it. The base is read from git's objects into a scratch directory and analysed with the same settings; only the import graph and reachability are compared between the two analyses, never a status, a confidence or an owner, because those depend on history the base cannot have.

## Keep candidates apart from what ran

*Validation* has two halves that never mix. The candidate tests are the test files that reach the changed files through imports: paths, not results. What ran is what the host says ran, through `--ran` lines, a JUnit report with `--report` or a coverage report with `--coverage`. With a coverage report the page says how many of the lines the change added or changed have a statement the tests executed, which did not, and which files the report does not measure at all.

## Where there is no evidence, say so

*Open for a person* collects what the analysis cannot settle: changed code with no active owner, files only the author has touched, files in a language without an analyzer, candidates that failed or did not run, the absence of any recorded check. *Read this with care* closes the page with what every line rests on and what static analysis cannot see: registries, dynamic loading, consumers outside the repository. A clean result is never a proof.

The page aims to stay under 800 words. Every list it shortens carries its count, and `--format json` holds the whole `triage` and `check` objects, so selecting for reading filters nothing away. The same page is what `tessri integration install --agent review` posts on every pull request.

[The review brief](../guide/brief.html) has a complete sample and every option.
