# Local review experience

A person takes over a change produced in a terminal or agent session. The shared review interface provides
ranked files, captured source, structural findings, supplied validation, history-backed reviewer context and
complete brief JSON. The homepage demonstrates that interface using the generated teaching fixture.

## One analysis contract, three surfaces

`tessri review` uses `brief.compute` without altering its schema, rank, findings or severity. `tessri/workbench.py`
adds bounded working-tree and base source plus navigation paths for findings. `tessri/reviewview.py` embeds the
shared HTML/CSS/JS assets in a live local page, a single-file offline export or the site's worked review. The
existing Markdown, JSON and script-free HTML brief remain available.

The capture includes changed files, unchanged finding context and candidate test paths. Missing, symlink, binary,
non-UTF-8 and oversized source is explicitly unavailable. At most 200 relevant files, each at most 200,000 bytes
per version, are embedded. The complete brief retains evidence beyond those source limits. Source lines are
numbered; no diagnostic span is invented for a finding that only names files.

All repository-controlled data is inert JSON with HTML-significant characters escaped. The client constructs
text nodes, never repository-controlled markup, URLs or executable code. The same renderer operates on arbitrary
repository findings rather than a hardcoded story. The teaching case is validated by the site generator, including
the deleted module, unchanged importer and actual fixture test result. Its temporary machine paths are normalized.

## Local session boundary

The standard-library HTTP server binds only 127.0.0.1, on an ephemeral or explicitly selected port. Every resource
requires an unguessable session path and the expected Host header; refresh also requires a capability header and
rejects a foreign Origin. No arbitrary filesystem route, shell execution, agent dispatch, telemetry or public
listener is exposed. Responses disable storage and referrers, and constrain browser resources to the page itself.

The page observes changes but recomputes only on an explicit refresh. Detection combines HEAD, comparison-ref,
Git status, changed-file metadata/contents, configuration metadata and supplied report contents. Capture compares
that key before and after the analysis; an in-flight change marks the result stale. Refresh replaces the previous
snapshot only after successful capture, reloads CLI configuration and preserves the previous view on failure.
This is change detection, not an atomic filesystem or validation provenance protocol. Large files and unusual
filesystem races remain limits.

`--out` emits one offline source snapshot without starting a server or opening a browser. The exported page cannot
observe subsequent edits. Its mode and capture time remain visible. It may contain private source; sharing is a
separate user decision. Without JavaScript, the existing brief HTML is the readable alternative.

## Agent handoff

Codex, Claude Code and Copilot instructions explain the same nonblocking one-shot export. The person can copy a
finding's paths, scope, capture time, action and validation limits back into the active CLI. Copying does not send
messages or execute an action. The agent must check whether the captured scope still matches before using it.

The existing stdio MCP tools remain read-only. Host adapters retain their own formats: Claude project MCP,
Codex's explicit registration command, and a reversible Copilot CLI session configuration supplied with
--additional-mcp-config. Installation reports files and the remaining host step; it does not claim host activation
or bypass trust. No global host configuration is edited automatically.

## Visual direction and validation

The approved direction uses a centered task statement, existing Inter/Commit Mono and violet identity, restrained
page surfaces, and a charcoal source/evidence workspace as the main visual. The narrow layout stacks file
navigation, code and evidence. Guide navigation, search, themes, looks and the existing live demo stay available.

Checks cover real unchanged importers and deleted base source, read-only capture, hostile text round trips,
source bounds, content changes with preserved metadata, refresh and loopback access boundaries, offline CLI
handoff, reversible host configurations and agreement between the site and the shared fixture. Browser checks
cover file/version/finding navigation, copy fallback, stale/refresh behavior, themes and narrow widths.

No claim of reviewer speedup follows from a teaching example. A small future task trial should record missed
important evidence, navigation steps and interruption cost before broadening the product surface.
