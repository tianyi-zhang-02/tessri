# One page to hand a change over

A change is done, by an agent or by a person, and someone else has to stand behind it. `tessri brief --since <base>` is the page that person gets. It took longer to decide what the page must not do than what it should show, so this post walks through a real one, section by section, with the rule behind each section and the mistake the rule exists to prevent.

![The six parts of the page and the principle each carries: the scope line names the state the evidence describes; Look first orders by two things; the structure is compared on the graph alone; candidates are kept apart from what ran; what has no evidence needs a person; what it cannot see is said with its reason.](figures/brief.svg)

## Why a page, and not a score or a chat

The reviewer's problem is not a lack of information; it is that the information arrives as a diff, and the diff does not say where to start, who else knows this code, what else the change can reach, or what was actually run. An agent can be asked all of that, and will answer from the diff plus whatever it chooses to read, with the confidence of prose. We wanted the opposite: a page whose every line comes from something the reader can check, that says what it cannot see, and that is the same page whether a person or a workflow asked for it. The brief is assembled from two queries Tessri already had, `triage` and `check`, from one analysis of the base and one of the working tree; it adds nothing of its own except the order of the sections and the decision of what to leave out.

## The scope line: say which state the evidence describes

The page opens like this, from a pull request of Tessri's own repository, where the `review` workflow posted it as a comment:

```text
`origin/release-0.3.0` (base 922381dac) to HEAD 788f979b5. 6 code files changed (0 added, 6 modified, 0 deleted),
**186** lines; 5 other files (122 lines of config, docs and the like).

1 commit on the way, by Tianyi Zhang, in their words:

- `788f979b5` The review brief on every pull request: `tessri integration install --agent review` (Tianyi Zhang)
```

Three decisions are in those lines. The JSON keeps the full base and head object ids, because *since main* means something different tomorrow; the rendered page shows short prefixes for reading. When there is uncommitted work, the page lists the files it is in, because a commit id does not identify uncommitted contents and a page that silently included them would be describing a state nobody can get back to. And the commits appear with their authors' own subjects, labelled *in their words*: the page never infers what a change was for from the files it touched, because an import graph cannot know intent and a page that guessed would be believed.

## Look first: order by two things, show the rest

```text
| # | File                        | Why                   | This change | Owners           | Flags     |
|---|-----------------------------|-----------------------|-------------|------------------|-----------|
| 1 | `tessri/cli.py`             | 15 commits in 90 days | +2 -2       | Tianyi Zhang 100% | -         |
| 2 | `tessri/templates.py`       | 12 commits in 90 days | +81 -3      | Tianyi Zhang 100% | -         |
| 3 | `tests/test_integration.py` | 5 commits in 90 days  | +83 -1      | Tianyi Zhang 100% | test file |
```

The order is commits in the last 90 days, then the lines of the change, because that is the order a backtest on three repositories found hard to beat. A two-line change to a file that was touched fifteen times this quarter comes before an eighty-line change to a quiet one, and the *Why* column says so in words a reader can argue with. Everything else about a file is beside it, not multiplied into a rank: the fixes and reverts among those commits, the owners with their share, the flags (new file, moved, no active owner, author is not among the owners, orphan, test file). Under the table, one line per file names the functions and classes the change touched, from the diff's hunks and Python's parser, so a reviewer can go to `Shape.area` rather than to a file. Then the people who can look, the authors apart, ordered by their commits to these files in the last year, and the repository's regulars when they are not already named.

What the section refuses to do is combine. There is no score, because the one we tried did not beat its parts, and a column of numbers that cannot be traced to a commit or a line would be the first thing a reader trusted and the last thing they could check.

## What it did to the structure: compare the graph alone

```text
No structural findings: the change adds no orphan, cycle, dangling import or unowned code that this analysis can see.

Code outside the change that imports it: **1 file** directly, 0 files through one more step (by area: `tessri` 1).
```

This is `check` on the same analysis: imports of files the change deleted, new cycles, new files nothing reaches, changed code that nobody active maintains, each with its first files and what to do about it, most serious first. The base is read from git's objects into a scratch directory and analysed with the same settings as the working tree. Only the import graph and reachability are compared between the two analyses, never a file's status, confidence or owners: those depend on history, and the base's analysis has less of it by construction, so a comparison would manufacture differences. The sentence for an empty result names what was looked for, so that *no findings* cannot be read as *nothing to worry about*.

## Validation: keep candidates apart from what ran

```text
Candidate tests, nearest first: `tests/test_brief.py`, `tests/test_htmlreport.py`, `tests/test_integration.py`,
`tests/test_mcp.py`, `tests/test_meta.py` and 3 more (15 in all). They reach the changed files; they are paths, not results.

Checks the host ran: none recorded. Record each with `--ran "<command>: <result, exit code>"`, or hand over a test
report with `--report` or a coverage report with `--coverage`.
```

This section has two halves that never mix, and the wording is deliberate to the word. The candidate tests are the test files that reach the changed files through imports, nearest first: paths, not results, and the page says so every time. What ran is what the host says ran: a line per check through `--ran`, verbatim, with the command and the exit code; or a JUnit report the host wrote, read through `--report`, which marks each candidate passed, failed, skipped or not run, and says how many of them the report mentions at all; or a coverage report through `--coverage`, which joins the report with the diff and says how many of the lines the change added or changed have a statement the tests executed, which did not, and which changed files the report does not measure. Tessri runs no tests and reads no CI. A page that let *tests that could run* drift into *tests that ran* would be the most dangerous page in the tool.

## Open for a person: where there is no evidence, say so

The fourth section collects what the analysis cannot settle: changed code with no active owner, files only the author has ever touched, files in a language without an analyzer, candidates that failed or are missing from the report, changed statements no recorded test executed, and the absence of any recorded check. Each is a sentence with the files and what a person would have to decide. Nothing here is a verdict; the page does not say a change is safe, because it has no way to know, and it does not say a change is blocked, because that is a team's policy. It says *this needs a person*, and names the person it can.

## Read this with care: what it cannot see, with the reason

The page ends with the limits that apply to everything above it: that dependents and findings rest on static imports between files of this repository, that a name in a string or a dynamic import is a guess and says so, that registries and consumers outside the repository are invisible, that history is read up to the base so the change's own commits are not its own activity, that candidate tests are paths. The section is the same on every brief, on purpose; a reader who has seen it once knows where to look when a result seems too clean.

## The budget

The page aims to stay under 800 words. Every list it shortens carries its count, and `--format json` holds the whole `triage` and `check` objects, so selecting for reading filters nothing away: an agent that wants all fifteen candidate tests reads the JSON, a person reads the page. The same page is what `tessri integration install --agent review` posts on every pull request, updated on each push, and what `tessri_brief` returns to an agent that asks over MCP.

[The review brief](../guide/brief.html) has a complete sample, every option, and the JSON's shape.
