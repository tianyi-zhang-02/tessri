# Who maintains it

Ownership is read from git history: whoever has been maintaining a file lately, with older work counting less, and
whether they are still around.

Ownership is read from git. Each commit credits its author with the files it touched, and a commit
loses half its weight per year, so a file's owner is whoever has been maintaining it lately, not whoever
wrote it first. An owner counts as **gone** after `owner_inactive_days` (180) without a commit anywhere in the
repository. A file or directory with no active person holding at least 20% of the maintenance has
**no active owner**.

```text
$ tessri why legacy/old.py
legacy/old.py  (Python, 2 code lines)
status:        DORMANT
reachability:  reachable from a production entry point
owners:        Bob Brown 100% (silent 800d); NO ACTIVE OWNER
CODEOWNERS:    @someone-else (none of them maintains it)
```

The report's ownership section answers the questions a large codebase makes hard:

| Question | Where |
|---|---|
| Who maintains each directory, and are they still around? | table of directories: owners, share, `silent Nd`, state |
| What live code has nobody looking after it? | "Live code nobody active maintains", largest first |
| How concentrated is knowledge? | `bus_factor`: the fewest people who together hold half the code |
| Who should I ask before deleting an orphan? | an `Owner` column on every cleanup candidate |
| Does `CODEOWNERS` match reality? | files with no declared owner, and files whose declared owner is not among their maintainers |

A directory nobody clearly owns is shown honestly, e.g. `Dana 10% + 25 others`. Bots (`[bot]`,
dependabot, renovate, github-actions, pre-commit-ci, and a name or address ending in `-ci` or `-bot`) never own code,
and neither do authors matching `ignore_authors`.
A commit touching 300 or more files (a reformat, a vendor drop) is ignored for ownership unless it is all
a file has, and a pure move (a rename that changes nothing inside the file) credits nobody: the file keeps the
credit of the people who wrote what is in it. Authors are matched by name, so one person committing from two addresses is one author; add a
`.mailmap` for anything this gets wrong. Emails are used to identify people and never appear in a report.

`CODEOWNERS` is read from `.github/`, the root, `docs/` or `.gitlab/` (first found), last matching rule wins.
A declared `@login` can be compared with the people who maintain a file only when they commit from a GitHub
noreply address, and git knows nothing about `@org/team`, so those comparisons are reported as undecidable
rather than as a mismatch.
