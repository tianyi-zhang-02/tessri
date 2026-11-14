# Integration: skills, AGENTS.md, MCP, hooks, configuration, workflows

`tessri integration` installs the agent skill for Claude Code or Codex, one marked block in `AGENTS.md`, Copilot's
instructions file, the entry that points a host at the [MCP server](mcp.md), the [hooks](hooks.md) Claude Code or
Codex runs, a starter configuration file, a weekly report workflow or the review brief on every pull request, with a
receipt, and takes it out again.

```bash
tessri integration install --agent claude --agent codex --dry-run   # show the plan, write nothing
tessri integration install --agent claude --agent codex             # project skills for Claude Code and Codex
tessri integration install --agent agents                           # one marked block in AGENTS.md
tessri integration install --agent copilot                          # Copilot's instructions file
tessri integration install --agent mcp --agent vscode               # .mcp.json and .vscode/mcp.json entries for the server
tessri integration install --agent claude-hooks --agent codex-hooks # the hooks each host runs: impact after an edit, findings at a stop
tessri integration install --agent config                           # a .tessri.toml with every option commented out, to start from
tessri integration install --agent report                           # a weekly scan workflow that keeps the report
tessri integration install --agent review                           # the brief as one comment on every pull request
tessri integration status                                           # what is installed and whether it changed
tessri integration update                                           # refresh files that are still as installed
tessri integration remove                                           # take everything out again
```

Every form takes the project root as `--repo PATH` or as its first argument (default: the current directory).

`integration` keeps a receipt, `.tessri-integration.json`, at the project root: which profiles are installed
(`claude` writes `.claude/skills/tessri/SKILL.md`, `codex` writes `.agents/skills/tessri/SKILL.md`, `agents`
inserts one marked block into `AGENTS.md`, `copilot` writes `.github/instructions/tessri.instructions.md`, `mcp`
adds the `mcpServers.tessri` entry to `.mcp.json`, `vscode` the `servers.tessri` entry to `.vscode/mcp.json`,
`claude-hooks` adds Tessri's two hook groups to `.claude/settings.json` and `codex-hooks` to `.codex/hooks.json`,
`config` writes `.tessri.toml`, `report` writes `.github/workflows/tessri-report.yml` and `review` writes
`.github/workflows/tessri-review.yml`),
the hash of every file it wrote, the exact bytes it inserted into `AGENTS.md`, the entry or the hook groups it added
to a JSON file and the directories it created. Only what the receipt records is ever updated or removed. A file that
already exists is a conflict, even when it is byte-identical to the template; a recorded file you edited is yours
and is left alone; text you add outside the block survives `update` and `remove`; a shared file that was there
before is never deleted. Every command plans and checks all its targets first and writes nothing when any of them
conflicts (exit 1, with the plan); `--dry-run` shows the same plan without writing; `--format json` gives it as
data; single files are replaced atomically and an ordinary failure is rolled back, which is not a cross-file
transaction. Installing files does not prove a running host has discovered them: start a new session in the
project afterwards. Nothing else is touched: no `.gitignore` line, no network, no hook you did not ask for. It works
in an empty or non-git project too.

`tessri integration status .` also says, per host (Claude Code, Codex, Copilot's coding agent, editors reading
`.vscode/mcp.json`), which installed file carries its instructions, which one points it at the server, which one
holds its hooks (for the two hosts that run them), and what is left to do; for a host whose server configuration is not in the project it prints the line to run or the JSON
to paste. The MCP guide has the [profiles and what each host reads](mcp.md#pointing-each-agent-at-it).

Updating Tessri itself does not rewrite installed instructions. For receipt-managed integrations,
`tessri integration status .` reports `installed-outdated` when the bundled instructions have changed.
Preview with `tessri integration update . --dry-run`, then run `tessri integration update .` to refresh
unchanged managed files and blocks. User-modified content remains a conflict; review and reconcile it yourself.
The updated skill explains impact's evidence sources and `--edges imports`, while candidate tests remain
subject to the project's runner and required checks.

Two profiles put Tessri into the agent's own loop. `claude-hooks` and `codex-hooks` add one matcher group per event
(`PostToolUse` of `Edit|Write`, and `Stop`) to the hooks file each host reads, next to whatever hooks and settings
are there already; each group runs `tessri hook`, and `remove` takes exactly those groups out again. What the
hooks say, when they are silent, what they cost and how the hosts guard them is on the [hooks page](hooks.md).

Three profiles are not an agent's. `config` seeds `.tessri.toml` with every option commented out, and the file is
yours from the moment it is written: `status` reports it `installed-current` whatever it says, `update` never
rewrites it, a deleted one is forgotten rather than recreated, and `remove` deletes it only while it is untouched
and otherwise just stops recording it. An existing `.tessri.toml` is a conflict for `install` and is never listed as
unmanaged.

`report` writes a workflow that scans the repository every Monday and on demand, summarises the report on the run
and keeps the JSON and the HTML page as an artifact. `review` writes a workflow that runs on every push to a pull
request: it checks out the branch as pushed with the whole history, runs `tessri brief --since origin/<base>` with
the pull request's own base (never an assumed branch name), posts the page as one comment that it finds again by
its marker and updates in place, puts the same page in the run's summary, and keeps it with
`check --format sarif --locationless omit` as an artifact. From a fork, whose token cannot comment, the summary and
the artifact are all there is. The gate (`--fail-on block`) and the upload of the SARIF to code scanning are
commented lines in the file; turning either on is the team's choice, and makes the file yours. Both workflows pin
the Tessri that installed them (`pip install tessri==<version>`), so after an upgrade `status` says
`installed-outdated` and `update` refreshes the pin; like a skill, an edited workflow is yours and `update` leaves
it alone. This repository runs the review workflow on its own pull requests, installing Tessri from the checkout.
As a Claude Code plugin, it also ships `.claude-plugin/plugin.json` and `skills/tessri/SKILL.md`.

Copyable recipes for CI artifacts, SARIF uploads, gates and test selection are in
[workflow-recipes.md](../workflow-recipes.md).
