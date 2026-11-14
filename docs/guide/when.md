# Which command, when

Every command is one view of the same picture of the code and its history, so the question is only which moment
you are at. The MCP tool is the same question for an agent that speaks the protocol; it returns the command's JSON
and its text from one analysis.

| Moment | Command | MCP tool | Read first |
| --- | --- | --- | --- |
| Getting to know a repository | `tessri scan .`, or `--format html --out report.html` for the explorer | `tessri_scan` | the summary, the per-directory table, then `caveats` |
| About to change a file or directory | `tessri impact <path>` | `tessri_impact` | the dependents and the tests that reach it, then the owners |
| Checking a claim about one file | `tessri why <path>` | `tessri_why` | the verdict and the evidence lines under it |
| Planning a cleanup, or reading the structure | `tessri graph .` | `tessri_graph` | the cycles, then the few dependencies to cut |
| Reviewing a change | `tessri triage --since <base>` | `tessri_triage` | the first rows and why they are first, then who can look |
| When a change is done | `tessri check --since <base>` | `tessri_check` | the findings by severity; `--fail-on` turns a severity into an exit code |
| Handing a change to a person | `tessri brief --since <base> --ran "<check: result>"` | `tessri_brief` | the scope line, then the look-first table, then what is open for a person |
| On every pull request | `tessri integration install --agent review` | | the comment on the pull request, updated on every push |
| Weekly | `tessri integration install --agent report` | | the run's summary; the JSON and the HTML page are its artifact |
| Giving it to an agent | `tessri integration install --agent claude` (or `codex`, `agents`, `copilot`, `mcp`, `vscode`) | | `tessri integration status`, which says per host what it has and what is left |

Three things hold across the table. Without `--since`, a branch is judged against the default branch (the one the
remote declares, else `main` or `master`); on the default branch itself the change is the uncommitted work, and
`--since HEAD` means that anywhere. Every command takes the repository root as `--repo PATH`, and `scan` and `graph`
also as their first argument. And the command line, the MCP tool and the JSON say the same thing in the same words:
`--format json` is the same facts as data, with the [`meta` block](json.md) that says exactly what was analysed.

Ownership and review load have no command of their own: they are sections of `scan` (the [ownership](ownership.md)
and [review load](review-load.md) pages), and `why` shows one file's maintainers with the rest of its evidence.
