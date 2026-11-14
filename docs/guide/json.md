# JSON output

Every command prints one JSON object with `--format json`, versioned by `schema_version` and carrying the same
`meta` block, so an agent can read any answer as data.

`tessri scan --format json` prints one object, versioned by `schema_version` (currently `1`; adding
fields does not bump it), with `kind: "scan"`. Top-level keys: `summary` (sizes, `by_status`, `orphans`, `test_only`,
`reachability_coverage`), `languages`, `directories` (with `owners` and `ownership` per directory), `ownership`
(`authors`, `bus_factor`, `no_active_owner`, `top_authors`, `needs_owner_files`, `codeowners`; `{"available": false}`
without git), `review` (`window`, `totals` with `bulk`, `unowned`, `areas`, `authors`, `reviewers`, `largest_changes`;
`{"available": false}` without git or with `review_days = 0`), `largest_files`, `hotspots`, `cleanup` (`orphan_files` with `owner`, `test_only_files`), `analysis`,
`caveats`, and with `--full` a per-file `files` table.

`tessri graph --format json` and `tessri impact --format json` print their own objects (`kind` is `module-graph`,
`file-graph`, or `file` or `directory` with a `target` for an impact) with the same `schema_version`. `tessri why <path> --format json`
prints the same facts the text shows, as data: `file`, `verdict` (`status`, `confidence`, `reachability`,
`entry_points`, `notes`), `git`, `owners`, `graph` (`reached_via`, `dependents`, `config_refs`, `doc_refs`,
`depends_on`, `stranded_if_removed`, and `kinds`: the kind of evidence behind each edge, as `impact` names them,
for `reached_via` as one entry per hop and for `dependents` and `depends_on` as a map from path to kind) and
`advice`; `git`, `owners` and `graph` are `null` when the analysis had nothing to say. `tessri brief --format json`
prints `kind: "brief"`: its own sections (`change` with the full base and head, the commits on the way and the
uncommitted files in scope; `attention`; `consequences`, with `not_analysed`; `validation`, with `candidates`,
`ran`, `report` and `coverage`; `people`; `open`) and, whole, the `triage` and `check` objects it was composed from.

The [MCP server](mcp.md) returns these same objects as each tool's `structuredContent`, unchanged.

Every JSON object also carries a `meta` block with the same names everywhere: `tool`, `generated_at`, `repo`
(`name`, `root`), and `git` with `available`, `reason` (`null`, or `not-a-repository`, `no-commits`,
`git-not-found`, `git-error`, `not-requested`), `head` (the checkout's HEAD, resolved on its own), `history_rev`
(the commit history was read up to: HEAD for a scan, the base for `triage` and `check`), `shallow` and `commits`.
All ids are full object ids. `triage`, `check` and `brief` add `meta.change` (`since`, as given or the default branch chosen
when none was, `base`, `head`, `uncommitted`),
and `check` and `brief` add `meta.analysis`, which says `skipped` with reason `no-code-changes` when nothing was compared, so an
empty `findings` list is never mistaken for a clean comparison. The older top-level fields (`git` in a scan, the
short `change.base` and `change.head` of `triage` and `check`) keep their meaning. A caught error (an unknown base,
a directory that is not a repository) exits 2 and prints nothing on stdout; exit 1 is reserved for `check
--fail-on`, a result that was computed and failed the chosen gate.
