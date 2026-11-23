# Tessri for VS Code

Who maintains this file, what a change to it can reach and which tests get there, in the editor, from the code
and the git history. The same questions are tools for the chat agent. Tessri never edits code and never writes
into the repository.

## What you see

- **A line over each file** (Python, JavaScript, TypeScript): dependents, candidate tests, maintainers and the last
  commit. Click it for the evidence.

  `Tessri: 8 dependents (5 direct) · 24 candidate tests · maintained by Tianyi Zhang 100% · last commit 2026-11-23`

- **A hover over each definition** (function, class, method): the file's status and reachability, who maintains it
  and since when, how many code files depend on it and how many tests reach it, with links to the two pages below.

- **Commands**, from the editor's or the explorer's context menu under *Tessri*, or the command palette:
  *Why this file* (the evidence, as text), *What a change here can reach* (dependents, candidate tests, maintainers),
  *Triage the change*, *What the change did to the structure* and *Review brief* (the change since the base,
  as Markdown preview).

- **Tools for the chat agent**: `#tessriImpact`, `#tessriWhy`, `#tessriTriage`, `#tessriCheck`, `#tessriBrief`,
  `#tessriScan` and `#tessriGraph`. Agent mode picks them up by itself; a prompt can name one. Each returns the
  command's text, the same the terminal prints.

Every number comes from `tessri why <file>` and `tessri impact <file>`; the editor adds no judgement of its own.

## Install

1. Tessri itself, Python 3.11 or newer, no dependencies:

   ```
   pip install tessri
   ```

   or `uv tool install tessri`, or `pipx install tessri`. `tessri --version` should answer.

2. This extension, from the Marketplace or Open VSX. If `tessri` is not on the editor's PATH, set
   `tessri.command` to `["python3", "-m", "tessri"]`, `["uvx", "tessri"]` or the full path.

## How it works

The extension starts `tessri mcp --root <folder>` once per workspace folder and asks it the way an agent would,
over the Model Context Protocol's standard-input transport. The first question analyses the repository, which
takes a second or a few on a large one; while the checkout is unchanged the server reuses that analysis, so the
rest cost milliseconds. A save in the folder asks again.

The server stays with the window. *Tessri: Restart the server* starts it afresh; *Tessri: Show the log* shows
what it said.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `tessri.command` | `["tessri"]` | the command that runs Tessri, as a list |
| `tessri.codeLens` | `true` | the line over each file |
| `tessri.hover` | `true` | the hover over each definition |
| `tessri.since` | `""` | the base for triage, check and brief; empty is the default branch |

Analysis options (what counts as active, who counts as an owner, which paths are ignored) are Tessri's own, in the
repository's `.tessri.toml`: `tessri integration install --agent config` writes one with every option explained.

## Limits

Static analysis of one repository: registries, dependency injection and consumers outside the repository are not
seen, and a file nothing reaches is a candidate, not a verdict. A candidate test is a path that reaches the file,
never a run. The hover's facts are the file's, not the definition's. The extension needs a trusted workspace and
runs where the files are.

## Also

- [Tessri](https://github.com/tianyi-zhang-02/tessri): the command line, the review brief, the hooks for coding
  agents and the MCP server this extension talks to.
- `tessri integration install --agent vscode` writes `.vscode/mcp.json` instead, for an editor that should reach
  the server without this extension.
