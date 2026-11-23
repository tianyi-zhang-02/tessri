# Local review workbench

`tessri review` opens a read-only view of a change: the ranked file list, working-tree and base source,
structural findings, host-supplied validation and the full brief JSON. It uses the same analysis as `brief`.

```bash
tessri review --since main
tessri review --repo /path/to/project --since HEAD --no-open
tessri review --since main --ran "python -m unittest: 12 passed (exit 0)"
tessri review --since main --report junit.xml --coverage coverage.xml
tessri review --since main --out /tmp/tessri-review.html
```

Without `--out`, the command starts a server on `127.0.0.1`, chooses an available port and prints a private
session URL. `--no-open` suppresses browser launch; `--port` selects a local port. Ctrl-C stops the session.
Only the checkout and base named at launch are served. There is no file browser, code editor, test runner,
agent connection, telemetry or public listener. Repository source is never executed.

## Follow a finding

Select a structural finding, then a path in its evidence. A file outside the diff is still navigable; a deleted
file opens at the base. Use the version selector to compare captured working-tree and base source. The file list
can be filtered, and includes the ranked change, finding context and candidate tests.

Source capture is bounded to 200 relevant files and 200,000 bytes per version. Missing, binary, non-UTF-8,
oversized and symlink source is labelled unavailable. The full brief retains all findings and ranked files even
when their source is not captured. Line numbers locate captured text; they do not imply every finding has an
exact diagnostic span.

**Copy context for your agent** copies the finding, paths, base, HEAD, capture time, next check and validation
limits. Paste it into Codex, Claude Code, Copilot or another CLI. Copying sends nothing to a host automatically.
If clipboard access is unavailable, a selectable text field appears. Compare the scope with the current checkout
before acting on a copied or exported snapshot.

## Refresh and stale results

The local page checks for checkout and report changes, but recomputes only when **Refresh analysis** is pressed.
A changed checkout, changed comparison ref, changed report, interrupted session or failed refresh leaves the old
snapshot visibly marked. A refresh reloads configuration and replaces the data only after a complete capture.
If files change during capture, the new snapshot is also marked stale. This is a working-tree change detector,
not proof of an atomic filesystem snapshot. Oversized source and unusual filesystem races remain limits.

Validation remains host-supplied. A JUnit or coverage report does not establish which source contents were tested;
its association with this code snapshot stays unknown. Candidate tests are paths, not executions.

## Hand over from a CLI agent

Prefer the one-shot export inside an agent's tool call, rather than leaving a blocking server running:

```bash
tessri review --since main --out /tmp/tessri-review.html
```

Use a new file outside the checkout and give the person its path. It embeds the captured source, UI and full
evidence, with no external assets. It needs JavaScript for file navigation; without it the command's existing
`brief --format html` is the script-free alternative. An offline export cannot observe later changes or refresh.
The page may contain private source; sharing it is a separate decision.

Install the appropriate instructions and MCP entry explicitly:

```bash
# Claude Code: project skill and project MCP server
tessri integration install --agent claude --agent mcp

# Codex: project skill; register the stdio server with Codex separately
tessri integration install --agent codex
codex mcp add tessri -- tessri mcp

# Copilot CLI: instructions plus a session-scoped MCP configuration
tessri integration install --agent copilot --agent copilot-cli
copilot --additional-mcp-config @.tessri/copilot-mcp.json
```

These commands require Tessri on the host's PATH and Python 3.11+. Follow each host's normal project/server trust
flow. Installing files does not prove the host loaded them: `integration status` reports the files and remaining
host step. Existing hooks are optional and do not launch this workbench on every edit. `integration remove`
uses the receipt to remove unchanged installed files; it never edits the host's global configuration.

The configuration formats are documented by [Codex](https://developers.openai.com/codex/mcp),
[Claude Code](https://code.claude.com/docs/en/mcp) and
[Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#24-mcp-server-configuration).
Other CLIs can use `tessri mcp` when supported or the plain CLI export. No model calls are required by Tessri.
