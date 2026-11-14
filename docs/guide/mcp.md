# MCP: Tessri as tools

`tessri mcp` is a Model Context Protocol server over standard input and output. An agent that speaks MCP
(Claude Code, Codex, Copilot's coding agent and CLI, editors in agent mode) starts it as a subprocess and asks
Tessri's questions as tool calls, getting the same facts the command line prints, as data and as text, for one
checkout or several. Nothing is installed with it and it needs no account: it reads the checkout and its git
history, like every other command.

```bash
tessri mcp                                      # serves the current directory
tessri mcp --root ~/src/app --root ~/src/lib    # serves several checkouts; every tool names one with `root`
```

The server writes nothing to standard output but protocol messages, reports notices on standard error, and
exits when its input closes. Every call sees the checkout as it is, uncommitted work included: an analysis is
reused for a later call only while the checkout's fingerprint is unchanged (HEAD, the paths git reports as changed
or untracked with their sizes and modification times, and the configuration files) and for at most an hour, so a
run of questions about one checkout costs one analysis. `meta.generated_at` is when that analysis was made.
`tessri_triage`, `tessri_check` and `tessri_brief` compare a change and always read afresh; a checkout that is
not a git repository is analysed on every call.

## The tools

Each tool is one command. Its result carries the command's `--format json` object as `structuredContent` and the
command's text (`why`, `impact`) or Markdown (`scan`, `graph`, `triage`, `check`) as its one `content` item, both
from one analysis. The object has the `schema_version`, `kind` and `meta` of the [JSON guide](json.md); the names
of the tools, their arguments and every key they return are those of the command line, so the rest of this guide
describes them.

| Tool | Arguments | `structuredContent` | The question |
| --- | --- | --- | --- |
| `tessri_repos` | none | `{schema_version, kind: "repos", repos: [{name, root, git}]}` | which checkouts this server reads |
| `tessri_scan` | `root`, `full` | the scan report (`summary`, `languages`, `directories`, `ownership`, `review`, `largest_files`, `hotspots`, `cleanup`, `analysis`, `caveats`) | how the codebase fits together; what nobody maintains |
| `tessri_why` | `root`, `path` | `kind: "why"` (`file`, `verdict`, `git`, `owners`, `graph` with `kinds`, `advice`) | the evidence behind one file's verdict |
| `tessri_impact` | `root`, `target`, `edges`, `hops`, `report` | `kind: "file"` or `"directory"` (`files`, `code`, `module`, `dependents`, `tests`, `edges`, `depends_on`, `owners`, `contributors`) | what a change to one file or directory can reach |
| `tessri_graph` | `root`, `level`, `module_depth`, `include_tests` | `kind: "module-graph"` (`modules`, `edges`, `cycles`, `summary`, `caveats`) or `"file-graph"` (`nodes`, `edges`) | who imports whom, cycles, owners |
| `tessri_triage` | `root`, `since` | `kind: "triage"` (`change`, `summary`, `files`, `areas`, `ripple`, `tests`, `reviewers`, `nobody_else_can_look`, `notes`) | which files of a change deserve a person first, who can look |
| `tessri_check` | `root`, `since` | `kind: "change-check"` (`change`, `summary`, `changed_files`, `findings`, `orphans`, `dangling_imports`, `dangling_references`, `cycles`, `dependencies`, `unowned`, `modules_touched`, `notes`) | what a change did to the structure |
| `tessri_brief` | `root`, `since`, `ran`, `report`, `coverage` | `kind: "brief"` (`change`, `attention`, `consequences`, `validation`, `people`, `open`, and the whole `triage` and `check` objects) | one page to hand the change over to a person |

Arguments, with the command-line option each one is:

| Argument | Type | Default | Is |
| --- | --- | --- | --- |
| `root` | string | the server's only root; required when it has several | the checkout: an absolute path given to `--root`, or the `name` `tessri_repos` lists for it |
| `path` (`why`) | string | required | a file, as `why` takes it: a repository-relative path, a unique suffix, or a module name |
| `target` (`impact`) | string | required | a file or directory, repository-relative, or a dotted package name |
| `edges` (`impact`) | `"all"` or `"imports"` | `"all"` | `--edges` |
| `hops` (`impact`) | integer from 1, or null | null (any number) | `--hops` |
| `level` (`graph`) | `"module"` or `"file"` | `"module"` | `--level`; at the file level the text is the JSON itself, since that picture has no Markdown form |
| `module_depth` (`graph`) | integer from 1, or null | null (split by size) | `--module-depth` |
| `include_tests` (`graph`) | boolean | false | `--include-tests` |
| `since` (`triage`, `check`, `brief`) | string | the default branch: `origin/HEAD`, else `origin/main`, `origin/master`, `main` or `master`; `HEAD` when none exists | `--since`: a commit, branch or tag; the change is where it and HEAD part, plus uncommitted work (`HEAD`: the uncommitted work alone) |
| `ran` (`brief`) | array of strings | `[]` | `--ran`: the checks the host actually ran, one string each with the command, its result and exit code, recorded verbatim; without it the page says that none was recorded |
| `report` (`impact`, `brief`) | array of strings | `[]` | `--report`: test reports the host wrote, JUnit XML, paths relative to the root; the candidate tests are held against what ran |
| `coverage` (`brief`) | array of strings | `[]` | `--coverage`: coverage reports the host wrote (Cobertura or Clover XML, lcov, coverage.py's JSON), paths relative to the root; the lines the change added or changed are held against the statements that ran |
| `full` (`scan`) | boolean | false | `--full`: the per-file table |

Paths in and out are repository-relative with `/`, as in the JSON; `root` is the only place the machine's layout
appears. The analysis settings (`active_days`, `dormant_days`, `owner_inactive_days`, `review_days`,
`ignore_authors`, `keep`, `exclude`, `entry`) are not arguments: they come from the checkout's `.tessri.toml`, as
for the command line, and the result's `settings` or `meta` says which were in force. Options that choose a
presentation (`--format`, `--out`, `--limit`, `--top`, `--depth`, `--fail-on`, `--locationless`) have no
counterpart; the agent has the data. `level: "file"` and `full: true` can be large on a big repository.

`tessri_repos` returns, for each root, its `name` (the directory's base name, with a `-2`, `-3` suffix when two
roots share one), the absolute `root`, and `git` as `meta.git` describes it (`available`, `reason`, `head`,
`shallow`, `commits`), from probes alone: no history is read for the listing.

Every tool declares itself read-only (`readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`,
`openWorldHint: false`): no file is written, no network is touched, and a host that runs tools without asking,
such as Copilot's coding agent, can allow all of them.

## When a call cannot be answered

A mistake in the arguments is a tool result with `isError: true` whose `content` is the sentence the command
prints on standard error, without the `tessri:` prefix, so the agent can read it and try again:

| Case | Sentence |
| --- | --- |
| a path no analysed file has | `` `nope.py` is not a file in the analysed set (excluded, binary or unknown type?) `` |
| a name several files share | `` `__init__.py` is ambiguous: pkg/__init__.py, tessri/__init__.py `` |
| an unknown revision | `` `nope` is not a commit, branch or tag in this repository `` |
| a `root` the server was not started with | `` `/x` is not a root this server was started with; `tessri_repos` lists them `` |
| no `root` when the server has several | `` `root` is required: this server serves 3 checkouts; `tessri_repos` lists them `` |
| a root that is no longer a directory | `/x: not a directory` |
| a configuration file that does not parse | the sentence the command prints for it |

A malformed request, an unknown method or an unknown tool name is a JSON-RPC error (`-32602` for a bad
request, a bad argument or an unknown tool, `-32601` for an unknown method, `-32700` for a line that is not
JSON), never a tool result. A failure inside the server is `-32603` with the exception's name, and the server
stays up.

## The protocol

The server speaks two revisions of the protocol, because the current one changed the handshake and clients are
on both:

- **2025-11-25 and earlier** (`2025-06-18`, `2025-03-26`, `2024-11-05`): the client sends `initialize`; the
  server answers with the client's `protocolVersion` when it is one of these, otherwise `2025-11-25`, with
  `capabilities: {"tools": {"listChanged": false}}`, `serverInfo: {"name": "tessri", "version": <tessri's>}` and
  `instructions`; then accepts `notifications/initialized`, answers `ping` with `{}`, `tools/list` with
  `{"tools": [...]}` and `tools/call` with `{"content": [...], "structuredContent": {...}, "isError": false}`.
- **2026-07-28**: there is no handshake; every request carries `_meta` with
  `io.modelcontextprotocol/protocolVersion` and `io.modelcontextprotocol/clientCapabilities`. The server
  implements `server/discover` (`resultType: "complete"`, `supportedVersions` with every revision above,
  `capabilities: {"tools": {}}`, `instructions`, its identity under `_meta["io.modelcontextprotocol/serverInfo"]`,
  `ttlMs`, `cacheScope: "public"`), adds `resultType: "complete"` to every result, and answers a version it does
  not speak with error `-32022` and `data: {"supported": [...], "requested": "..."}`. A request without `_meta`
  is read as the earlier revision.

`instructions`, in both, is one paragraph: what Tessri is, which tool answers which question, that paths are
repository-relative and that `tessri_why` is how to check a verdict before acting on it.

## Pointing each agent at it

[`tessri integration install`](integration.md) has profiles that point a host at the server, with the receipt the
command keeps for everything it writes. A profile that adds one entry to a JSON file hosts share records the entry,
not the file: a file that is already there keeps its other entries and is rewritten as JSON with two-space
indentation; a file the entry's parent is not an object in, or that cannot be read as JSON (comments), is a
conflict whose detail holds the entry to add by hand; an entry that is already there and that no receipt installed
is a conflict too.

| Profile | Writes | Read by |
| --- | --- | --- |
| `mcp` | `.mcp.json`: `{"mcpServers": {"tessri": {"command": "tessri", "args": ["mcp"]}}}` | Claude Code (project scope; it asks you to approve the project's servers on first use), and other hosts that read `.mcp.json` |
| `vscode` | `.vscode/mcp.json`: `{"servers": {"tessri": {"type": "stdio", "command": "tessri", "args": ["mcp"]}}}` | editors that read it in agent mode |
| `copilot` | `.github/instructions/tessri.instructions.md` with `applyTo: "**"` and the skill's text | Copilot, in projects that keep its own files rather than an `AGENTS.md` |

Codex reads MCP servers from your own configuration, not the project's, so `tessri integration status` prints the
line to run instead of writing it: `codex mcp add tessri -- tessri mcp`. Copilot's coding agent takes its servers
from the repository's settings page, so `status` prints that JSON (`mcpServers.tessri` with `command`, `args` and
`tools: ["*"]`) and reminds you that `pip install tessri` belongs in `copilot-setup-steps.yml`. `status` then says,
per host, which installed file carries its instructions, which one points it at the server, and what is left to do.

The skill and the `AGENTS.md` block name the tools, so an agent that has either knows that `tessri_why` and
`tessri why` are the same question.
