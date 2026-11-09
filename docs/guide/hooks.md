# Hooks: Tessri while the agent works

Two profiles put Tessri into a coding agent's own loop. `tessri integration install --agent claude-hooks` adds
two hook groups to `.claude/settings.json`, the project settings Claude Code reads; `--agent codex-hooks` adds
the same two to `.codex/hooks.json`, the project hooks Codex reads. Both hosts run the same command,
`tessri hook`, at two moments, and it answers with the host's own JSON or with nothing at all.

```bash
tessri integration install --agent claude-hooks --agent codex-hooks
tessri integration status        # names the hooks file each host has
tessri integration remove        # your own hooks and settings around Tessri's stay as they were
```

## After an edit

When the agent edits or writes a file (the hosts' `Edit|Write`; Codex's `apply_patch` answers to those names, and
the hook reads the file names out of the patch), the agent is told what the edited code file can reach, as context
next to the tool's result:

> Tessri, on `tessri/since.py`: 8 code files in 2 modules depend on it, 6 directly (`tessri/brief.py`,
> `tessri/cli.py`, `tessri/hook.py`, `tessri/mcp.py`, `tessri/sinceview.py`, `tessri/triage.py`); 17 test files
> reach it (`tests/test_brief.py`, `tests/test_moves.py`, `tests/test_since.py`, `tests/test_htmlreport.py`,
> `tests/test_integration.py` and 12 more), candidates to run, not runs. The code it reaches is maintained by
> Tianyi Zhang 100%. The evidence and the full lists: `tessri impact tessri/since.py`.

That is the first half of `tessri impact <path>` in a few sentences of fact, which is the form the hosts ask for in
a hook's context. Each file is spoken about once per session, so an agent iterating on one file hears it the first
time only. A file nothing depends on gets no sentence at all, and neither does a file outside the project, a
deleted one, or one Tessri does not analyse.

## When the agent stops

When the agent ends its turn, the hook runs `check --since HEAD` on the uncommitted work and, when that finds
anything at warn or block severity (a file deleted but still imported, files nothing reaches any more, a new or
grown cycle, changed code nobody active maintains), says so once:

> Tessri, on the uncommitted work: `pkg/core.py` was deleted but is still imported (`pkg/app.py`, `pkg/cli.py`,
> `tests/test_core.py`). The evidence: `tessri check --since HEAD`; the page to hand over: `tessri brief --since HEAD`.

By default that line goes to the person, as the host's `systemMessage`: a stop is the hand-off moment, and the
findings are for whoever stands behind the change. With `stop_hook = "block"` in `.tessri.toml` the agent gets
the same line first, as the host's `decision: block` with the findings as the reason, so it continues and can deal
with them; the host marks its next stop `stop_hook_active`, and whatever is still open then goes to the person.
Each finding reaches each audience once per session. A clean change, a turn that edited nothing, a directory
without git or a repository without a commit yet produce no message.

## What it costs, and what it remembers

After an edit the hook analyses the working tree once (about half a second on a repository of a hundred files,
two to three seconds on two thousand); at a stop it compares the tree with HEAD, two analyses, and only when a
code file changed. The hosts run hooks synchronously; the installed groups carry timeouts of 60 and 120 seconds.
What each session has been told lives in one small JSON file per session under `tessri-hooks/` in the system's
temporary directory, named by a hash of the host's session id and holding only project-relative paths and finding
ids; files older than a week are dropped. Without a session id nothing is remembered, and every edit speaks.

The project root is the git top level above the host's current directory, or that directory itself;
`tessri hook --repo PATH` pins it, and editing the installed command that way makes the group yours, so `update`
leaves it alone. An error never stands in the host's way: a broken configuration, unreadable input or an
unexpected failure is one line on stderr and exit 1, which both hosts show and move past.

## Trust

Both hosts guard project hooks. Claude Code holds every hook back until the folder's trust dialog is accepted
(a non-interactive run skips the dialog, so review a repository's `.claude/` before scripting over it), and
`/hooks` lists them with their source. Codex loads a project's `.codex/` layer only once the project is trusted,
and asks you to trust each hook in `/hooks`, by its hash, so a changed hook has to be trusted again. The hooks
files are ordinary JSON: read the two groups before you commit them, as you would any hook.

## By hand

`tessri hook` reads one event on stdin, so it is easy to try in a repository:

```bash
printf '{"hook_event_name":"PostToolUse","session_id":"try","cwd":"%s","tool_input":{"file_path":"%s/tessri/since.py"}}' "$PWD" "$PWD" | tessri hook
```

The answer is the host's JSON (`hookSpecificOutput.additionalContext` after an edit; `systemMessage`, or
`decision` and `reason`, at a stop) or nothing. The same session id twice gives nothing the second time.
