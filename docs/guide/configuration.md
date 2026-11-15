# Configuration

`.tessri.toml` (or `[tool.tessri]` in `pyproject.toml`); every flag has a CLI equivalent.
`tessri integration install --agent config` writes a `.tessri.toml` with every option commented out, to start from.

```toml
active_days = 90
dormant_days = 365
keep = ["src/mypkg/api/*"]    # public API, plugins: never reported as orphans
exclude = ["vendor/*"]        # skipped entirely
entry = ["mypkg.cli"]         # extra entry points (module or path)
owner_inactive_days = 180     # no commit anywhere in the repository for this long => no longer an owner
review_days = 30              # review load: changes in this many days against the same number before (0 = off)
ignore_authors = ["ci-*"]     # author name or email globs that never own code
stop_hook = "inform"          # agent hooks: findings at a stop go to you ("inform") or to the agent first ("block")
cache = true                  # keep what the analyzers read from each file between runs (false: read everything every time)
```

If the repository is a library, modules that only outside users import will look orphaned.
List them under `keep`. `stop_hook` matters only with the [hooks](hooks.md) installed.

## The cache

Between runs, what the analyzers read from each file is kept in your cache directory, keyed by the file's content, so
a second run parses only what changed. On a repository of 1,900 files, 730 of them Python, `scan` took 2.6 seconds
cold and 0.6 warm, `impact` 2.5 and 0.6, `brief` 4.7 and 1.8. The [hooks](hooks.md) and the [server](mcp.md) run at
every edit and every call, so for them the warm run is the usual one. The cache changes no number: the same tree and
history give the same output with it, without it (`--no-cache` on any command, `tessri mcp --no-cache`, or
`cache = false` here) and after the directory is deleted. It is one JSON file per repository, named after the
repository's git directory so that every worktree shares it, under `TESSRI_CACHE_DIR` when that is set, else
`$XDG_CACHE_HOME/tessri`, else `~/Library/Caches/tessri` on macOS, `%LOCALAPPDATA%\tessri\cache` on Windows and
`~/.cache/tessri` elsewhere. Entries no run has used for 30 days are dropped at the next write; nothing is written
into the repository.
