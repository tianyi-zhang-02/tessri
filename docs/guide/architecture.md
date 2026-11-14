# Architecture

One pass over a repository builds one `Analysis`; every command is a view of it, and no view reads the files again.
The package is standard library only, about 7,700 lines of code in 34 files. The table is the import graph of this
checkout as `tessri graph . --level file --format json` reads it, and `tessri graph .` reports the one thing the
layering does not keep: `analyzers/python.py` imports the dotted-name patterns of `textrefs`, so `tessri` and
`tessri/analyzers` depend on each other, a cycle the tool lists against itself.

```text
repository ─► inventory ─► analyzers ─► graph ─► analyze ─► Analysis ─► one view per command ─► cli
 (files, git)      │       (python, javascript)   ▲            ▲                  │
                   └─► textrefs (config, CI, docs) ┘   gitlog ─► ownership         meta (on every JSON object)
```

| Stage | Modules | What happens |
|---|---|---|
| Discover | `inventory` | lists the files (`git ls-files`, or a walk without git), detects the language, reads the text and counts code, comment and blank lines; binaries, build output and oversized files are skipped |
| Understand code | `analyzers/python` (on `ast`), `analyzers/javascript` (`jslex` scanner, `jsproject` resolution), `textrefs` | each analyzer turns its files into edges, entry points, tests and a resolver for names found elsewhere; `textrefs` finds the names that config, CI, shell scripts and docs mention |
| Reachability | `graph` | walks from entry points and config references; tests are roots of their own, so test-only code stays visible |
| History | `gitlog`, `ownership` | history is read once up to a rev for per-file activity and fix commits, and once more for the two review windows; `GitState` says why history is or is not there; ownership credits authors with yearly decay, marks owners who went quiet and compares with `CODEOWNERS` |
| Verdict | `analyze`, `model` | one `FileRecord` per file, the status rules, and the `Analysis` everything below reads |
| Views | `report` + `render` (scan, Markdown and JSON), `htmlreport` + `htmlassets` + `graphview` (HTML, mermaid, dot), `explain` (why), `modules` (graph, impact), `review` (review load), `triage`, `since` + `sinceview` + `sarifview` (check), `brief` (triage and check from one pair of analyses, on one page), `mcp` (the same answers as tools over stdin/stdout) | each computes its own tables from an `Analysis` and renders them; `render` is the shared Markdown, `meta` the shared `meta` block |
| Front door | `cli` | argparse, `--format` and `--out`, and the exit codes: 0; 1 for a `--fail-on` gate that failed or an integration plan blocked by conflicts, always with the complete result; 2 for a caught error, with nothing on stdout |
| Into other repositories | `templates`, `integration` | the texts written into a project (skill, block, workflow, hooks, configuration) and the receipt-based install, update, status and remove |
| In the agent's loop | `hook` | reads a host's lifecycle event on stdin and answers, as the host's JSON, with `impact` of the edited file or with the warn and block findings of `check` on the uncommitted work, once each per session |

Three commands run the pipeline against another revision. `triage` analyses the working tree with history read up to the
base of the change, so the change's own commits count neither as activity nor as ownership. `check` extracts the base
from git objects into a scratch directory (`cat-file --batch`, never `git archive`, which honours export-ignore),
analyses both sides with the same settings and compares only the import graph and the reachability of each file;
status, confidence and owners are never compared between the two analyses. `brief` makes those two analyses once and
hands them to both `triage` and `check`, so its page costs what `check` costs. Only `inventory`, `gitlog`, `triage`, `since`,
`brief` and `hook` run git; the analyzers and views never shell out, and nothing fetches, caches or calls a model, so the same tree
and history give the same output. The tests in `tests/`, one file per area, build small repositories in temporary
directories with fixed commit dates and assert on the output, so the suite needs git and nothing else, except `node`
for the one test that runs the HTML page's script, which is skipped without it.

## Supporting another language

The engine in `tessri/graph.py` knows nothing about any language. An analyzer maps files to
`edges` (what each depends on), `roots` (entry points), `tests`, and a `resolve_reference` for names
found in config. Subclass `tessri.analyzers.Analyzer`, implement `handles(path)` and
`run(files, repo)`, return a `LanguageResult`, and register it from a package through the
`tessri.analyzers` entry-point group. `repo.paths` lists every file and `repo.read(path)` returns
any file's text, for project metadata such as `tsconfig.json` or `go.mod`.

Two reference implementations, written against the same interface: `tessri/analyzers/python.py`
(about 250 lines, uses `ast`) and `tessri/analyzers/javascript.py` (a hand-written scanner in
`jslex.py` plus tsconfig/package.json resolution in `jsproject.py`, because there is no parser to import).
