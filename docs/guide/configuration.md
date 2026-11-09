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
```

If the repository is a library, modules that only outside users import will look orphaned.
List them under `keep`. `stop_hook` matters only with the [hooks](hooks.md) installed.
