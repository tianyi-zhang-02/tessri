# In the editor: the VS Code extension

The questions Tessri answers, where the code is read: a line over each file, a hover over each definition, the
commands, and the same questions as tools for the chat agent. The extension is in
[`editors/vscode`](../../editors/vscode/README.md), with no dependency of its own; it runs `tessri` and shows what
it says. It never edits code and never writes into the repository.

## What you see

| Where | What | From |
|---|---|---|
| over each Python, JavaScript or TypeScript file | `Tessri: 8 dependents (5 direct) · 24 candidate tests · maintained by Tianyi Zhang 100% · last commit 2026-11-23` | `tessri impact <file>`, `tessri why <file>` |
| over the name of a function, class or method | which reaching tests name the definition, or that none does, or that its name was not searched; then the file's status and reachability, who maintains it and since when, how many code files depend on it and how many tests reach it, two links | `why`'s `definitions`, and the same two objects |
| in the Problems panel, on the files the change concerns | what the uncommitted work did to the structure: a deleted file still imported (an error, at the import), a new file nothing reaches, the import that closes a new cycle, a document or config still naming a deleted file, changed code nobody active maintains; the status bar counts them (`Tessri: 1 block · 2 warn`) and opens the page | `tessri check --since <base>`, again after each save |
| the *Tessri* context menu, the command palette | *Why this file*, *What a change here can reach*, *Triage the change*, *What the change did to the structure*, *Review brief*, as read-only pages | `why`, `impact`, `triage`, `check`, `brief` |
| the chat agent | `#tessriImpact`, `#tessriWhy`, `#tessriTriage`, `#tessriCheck`, `#tessriBrief`, `#tessriScan`, `#tessriGraph` | the [MCP tools](mcp.md), one to one |

A test *names* a definition when the identifier appears in the test's code, strings and comments apart: a mention,
not an assertion, and a test can exercise code without naming it. The rest of the hover is the file's. The same
join, for the definitions a change touched, is on the [triage](triage.md) page and in the brief.

The problems are the [check](check.md) page's findings, one per file they concern, with the check's own severity
(`block` is an error, `warn` a warning, `info` an information) and its words. A finding about a group of files
becomes one entry on each; the entry sits on the first line that names the file that is gone (its path, its dotted
module, its base name), else on the first line. Findings that are good news (an orphan gone, a cycle resolved) and
findings about no file in particular (a new dependency between modules) stay on the page.

## How it works

The extension starts `tessri mcp --root <folder>` once per workspace folder and asks it over the Model Context
Protocol's standard-input transport, as an agent would, so the editor and the agent see the same numbers. The first
question analyses the repository; while the checkout is unchanged the server reuses that analysis and the rest cost
milliseconds. A save in the folder asks again, and a second and a half after the last save the structure of the
change is checked again (`tessri_check`, which always reads afresh), once per folder. The server stays with the
window; *Tessri: Restart the server* starts it afresh and *Tessri: Show the log* shows what it said.

## Install and settings

`pip install tessri` (or `uv tool install tessri`) and the extension from the Marketplace or Open VSX, which Cursor,
Windsurf and Kiro read. When `tessri` is not on the editor's PATH, `tessri.command` takes the command as a list:
`["python3", "-m", "tessri"]`, `["uvx", "tessri"]` or a full path. `tessri.codeLens`, `tessri.hover` and
`tessri.problems` switch the three off; `tessri.since` is the base the change commands and the problems compare
with (empty: the default branch). Analysis options
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
