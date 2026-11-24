# In the editor: the VS Code extension

The questions Tessri answers, where the code is read: a line over each file, a hover over each definition, the
commands, and the same questions as tools for the chat agent. The extension is in
[`editors/vscode`](../../editors/vscode/README.md), with no dependency of its own; it runs `tessri` and shows what
it says. It never edits code and never writes into the repository.

## What you see

| Where | What | From |
|---|---|---|
| over each Python, JavaScript or TypeScript file | `Tessri: 8 dependents (5 direct) · 24 candidate tests · maintained by Tianyi Zhang 100% · last commit 2026-11-23` | `tessri impact <file>`, `tessri why <file>` |
| over the name of a function, class or method | the file's status and reachability, who maintains it and since when, how many code files depend on it and how many tests reach it, two links | the same two objects |
| the *Tessri* context menu, the command palette | *Why this file*, *What a change here can reach*, *Triage the change*, *What the change did to the structure*, *Review brief*, as read-only pages | `why`, `impact`, `triage`, `check`, `brief` |
| the chat agent | `#tessriImpact`, `#tessriWhy`, `#tessriTriage`, `#tessriCheck`, `#tessriBrief`, `#tessriScan`, `#tessriGraph` | the [MCP tools](mcp.md), one to one |

The hover's facts are the file's, not the definition's: which reaching tests name a definition is on the
[triage](triage.md) page and in the brief, for the definitions a change touched.

## How it works

The extension starts `tessri mcp --root <folder>` once per workspace folder and asks it over the Model Context
Protocol's standard-input transport, as an agent would, so the editor and the agent see the same numbers. The first
question analyses the repository; while the checkout is unchanged the server reuses that analysis and the rest cost
milliseconds. A save in the folder asks again. The server stays with the window; *Tessri: Restart the server*
starts it afresh and *Tessri: Show the log* shows what it said.

## Install and settings

`pip install tessri` (or `uv tool install tessri`) and the extension from the Marketplace or Open VSX, which Cursor,
Windsurf and Kiro read. When `tessri` is not on the editor's PATH, `tessri.command` takes the command as a list:
`["python3", "-m", "tessri"]`, `["uvx", "tessri"]` or a full path. `tessri.codeLens` and `tessri.hover` switch the
two off; `tessri.since` is the base the change commands compare with (empty: the default branch). Analysis options
are Tessri's own, in the repository's [`.tessri.toml`](configuration.md).

An editor that should reach the server without the extension takes the `.vscode/mcp.json` entry instead:
`tessri integration install --agent vscode`, on the [integration](integration.md) page.

## Developing it

```bash
cd editors/vscode
node --test test/*.test.js                          # against the real server on this checkout; Python 3.11+ and git
npx --yes @vscode/vsce@3 package --no-dependencies  # the .vsix, which also validates the manifest
```

`package.json` declares the tools statically and the tests check that it agrees with `lib/tools.js`. The
extension needs a trusted workspace, runs where the files are, and keeps to VS Code 1.95 or newer.

To try it without installing, open a second VS Code on this checkout with the extension loaded from source:

```bash
code --extensionDevelopmentPath "$PWD/editors/vscode" "$PWD"
```

When `tessri` is not a command on that machine, set `tessri.command` there to `["python3", "-m", "tessri"]`; the
server restarts by itself. Releasing is `npx --yes @vscode/vsce@3 publish --no-dependencies` for the Marketplace and
`npx --yes ovsx publish --no-dependencies` for Open VSX, each with that registry's token and the publisher
`package.json` names; neither runs in CI.
