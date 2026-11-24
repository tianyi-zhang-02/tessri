# Plugins: Tessri in Claude Code and Codex

The repository is a plugin for both hosts: one install brings the [skill](integration.md), the questions as
[MCP tools](mcp.md) and the [hooks](hooks.md) to every project you open, and writes nothing into any of them. The
plugin carries its own copy of Tessri and runs it with `python3` (3.11 or newer), so there is nothing to
`pip install`; a Tessri installed elsewhere is neither needed nor touched.

## Install

Claude Code, in a terminal (or `/plugin marketplace add tianyi-zhang-02/tessri` in a session, then `/plugin`):

```bash
claude plugin marketplace add tianyi-zhang-02/tessri
```

```bash
claude plugin install tessri@tessri
```

Codex, in a terminal (or `/plugins` in a session once the marketplace is added):

```bash
codex plugin marketplace add tianyi-zhang-02/tessri
```

```bash
codex plugin add tessri@tessri
```

Either host sees the plugin from its next session. `claude plugin update tessri@tessri` and
`codex plugin marketplace upgrade tessri` bring a new release: the plugin's `version` is Tessri's, so an update
arrives when a release does, not with every commit.

## What arrives

| | Claude Code | Codex |
|---|---|---|
| the skill, `skills/tessri/SKILL.md` | `/tessri:tessri`, and the agent reads it when a task matches its description | discovered from `skills/`, like a skill under `.agents/skills` |
| the tools, one `tessri mcp` server | started as `python3 <plugin>/bin/tessri mcp --root <project>` | started as `./bin/tessri mcp` in the plugin's directory; the server takes the project from the workspace Codex names in each call ([how](mcp.md)) |
| the hooks, `hooks/hooks.json` | run with the plugin: after `Edit` and `Write`, and at `Stop` | listed under `/hooks`, where you trust them; a plugin's hooks are not trusted by being installed |

The eight tools, their arguments and what each returns are on the [MCP page](mcp.md); what the hooks say, once
each per session, is on the [hooks page](hooks.md). `tessri_repos` tells you which checkout the server is reading.

## Alongside the project integration

`tessri integration install` writes the same skill, hooks and server entry into one project, with a receipt, for a
team that wants them in the repository; the plugin is yours, for every project, and leaves the repository alone.
Having both in a project is harmless: the hook remembers what a session was told, so two sets of hooks still say
each thing once, and the agent reads two copies of one skill.

## Removing

```bash
claude plugin uninstall tessri && claude plugin marketplace remove tessri
```

```bash
codex plugin remove tessri@tessri && codex plugin marketplace remove tessri
```

## Trying a checkout

`claude --plugin-dir <checkout>` loads the checkout as a session-only plugin; `claude --plugin-dir . mcp list`,
run in the checkout, shows the server connected. `claude plugin validate .claude-plugin/plugin.json --strict`
and the same for `.claude-plugin/marketplace.json` validate the manifests, which CI does on every push. For Codex,
`codex plugin marketplace add <checkout>` then `codex plugin add tessri@tessri` installs a copy of the checkout
into Codex's cache; a change needs a remove and an add. `tests/test_plugins.py` holds the manifests, the
marketplace files, the hooks and the launcher to what the hosts expect.

## The files

| File | Read by |
|---|---|
| `.claude-plugin/plugin.json` | Claude Code: name, version, the server (inline) |
| `.claude-plugin/marketplace.json` | Claude Code: the marketplace, with the plugin at `./` |
| `plugin.json`, `mcp.json` | Codex: the portable manifest and the server, in the Agent Plugins format |
| `.agents/plugins/marketplace.json` | Codex: the marketplace, with the plugin at `./` |
| `hooks/hooks.json` | both: the same two hooks `integration` installs, through the launcher |
| `skills/tessri/SKILL.md` | both: the skill, the same text `integration` installs |
| `bin/tessri` | both: `tessri` from this checkout, without installing it |

The manifests name `python3`. Where that is not a command (most Windows installs of Python answer to `python`),
the hooks and the server do not start; a `python3` alias or the Store's Python puts that right.
