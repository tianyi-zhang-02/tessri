# Changelog

Dates are the day a version was tagged.

## Unreleased

- Faster, and a cache. The Python analyzer reads a tree in one pass: the statements for imports and docstrings, and
  the expressions of a statement only when one of its lines holds a quote, which every string literal does, so the
  walk that was most of a scan now takes a fifth of the time and finds the same things. What the analyzers read from
  each file is then kept between runs in the user's cache directory, keyed by the file's content, so a second run
  parses only what changed: `check` shares it with the scratch copy of the base, worktrees share it with their
  repository, and the hooks and the server, which run at every edit and every call, run warm. On a repository of
  1,900 files (730 of them Python) `scan` went from 3.7 seconds to 2.6 cold and 0.6 warm; `impact` takes 2.5 and
  0.6, `brief` 4.7 and 1.8. The output is the same with the cache, without it (`--no-cache`, `tessri mcp --no-cache`,
  `cache = false` in the configuration) and after the directory is deleted, and nothing is written into the
  repository. [Configuration](docs/guide/configuration.md) says where it lives.
- The front doors do more. The site searches the guide: `/` or Ctrl K (⌘K) opens a search over every page and
  section, with the matching words marked and the keyboard moving through the places found. Guide pages carry the
  page before and after in reading order, an edit link to their Markdown, and a skip link to the content; every page
  has a canonical address and the card a link to it shows elsewhere; a wrong address gets a page that says so and
  searches; a sitemap and robots.txt. The README leads with its badges, a table of where Tessri goes in an agent's
  loop and a table of the questions and their commands; the repository gains a contributing guide, a security policy,
  two issue forms (something broke; Tessri said something wrong, with the evidence it gave) and a pull request
  template.
- The backtest and the reviewer match ran on a second repository: `pytest`, small, old, maintained by a few core
  developers and merged with merge commits, where `nemo-rl` is large, young and squashed. The order `triage` uses
  holds there, by less: 0.64 against 0.54 for the size of the change over twelve months, 0.66 against 0.53 with
  pytest's own bug-fix changelog fragments as the label, 0.69 against 0.57 over 36 months; fix history and dependents
  add nothing on either repository; files one import apart still change together far more often than files that
  merely share a directory, though the multiplier is not comparable between repositories. *Who can look* on its pull
  requests: the ownership list and a plain count of recent committers to the same files are about even again, two
  people again take half the review slots, and naming the repository's busiest people, which lost on the large
  repository, wins on the small one, where four people write and review most of the code.
  [The backtest](docs/guide/backtest.md) and [the reviewer match](docs/guide/reviewer-match.md) carry both outputs,
  and the brief's note on the order now says two repositories.
- *Who can look* is ranked by recent commits, and the page names the repository's regulars. The people `triage` and
  the brief offer, the authors apart, are now those who committed to the changed files in the last year, most commits
  first, then those who hold a share of the files' history without a commit this year; the share used to rank alone.
  The reviewer match on two repositories had found that the share did not beat a plain count of recent committers; on
  the list as it ships the large repository's recall went from 0.33 to 0.39 and its first name hit on 29% of the pull
  requests instead of 18%, the small one's recall from 0.46 to 0.48, with precision within a point of the plain
  count's (0.28 against 0.27). Below that line the page names *the repository's regulars*, the busiest committers of
  the last 90 days with their share of its commits, merges included, when they are not already offered, because on
  the small repository they beat every file-level list: where a few people review everything they are the reviewers
  whatever the files. Each reviewer row carries `commits`; `triage` and the brief's `people` carry `regulars`
  (`window_days`, `commits`, `committers`, `people` with `commits` and `share`); `tools/reviewer_match.py` scores
  both lists beside the baselines. On the way the service account that commits most to the large repository turned
  up first among its regulars, so a name or address ending in `-ci` or `-bot` now counts as automation, like `[bot]`,
  dependabot, renovate, github-actions and pre-commit-ci, wherever Tessri reads history: such an account owns nothing
  and is offered to nobody. [The reviewer match](docs/guide/reviewer-match.md) has the numbers.

## 0.4.0 (2026-11-14)

- `tessri integration install --agent claude-hooks` (or `codex-hooks`) puts Tessri into the agent's own loop. Two
  hook groups go into `.claude/settings.json` or `.codex/hooks.json`, next to whatever is there, and run
  `tessri hook`, a new command that reads the host's event on stdin and answers with the host's JSON or with
  nothing: after an edit, what the edited code file can reach (the files that depend on it, the tests that reach
  it, who maintains the code it reaches), once per file and session; when the agent stops, the warn and block
  findings of `check --since HEAD` on the uncommitted work, once each, to the person as a message or, with
  `stop_hook = "block"` in the configuration, to the agent first. A new receipt kind, `hooks`, finds the groups
  again by their exact content, so `update` and `remove` never touch your own hooks; `integration status` names
  the hooks file per host.
- `brief --report FILE` and `impact --report FILE` (and `report` on the MCP tools) read a test report the host wrote,
  JUnit XML as pytest `--junitxml`, jest-junit and most CI systems produce it, and hold the candidate tests against
  it: each is passed, failed, skipped or not run, the page says how many of the candidates ran, and a failed or
  missing candidate is an item for a person. Nothing is inferred: a candidate the report does not mention did not
  run, as far as the report says. Triage's JSON carries every candidate path under `tests.paths`.
- `brief --coverage FILE` (and `coverage` on the MCP tool) reads a coverage report the host wrote, Cobertura or Clover
  XML, lcov or coverage.py's JSON, and holds the lines the change added or changed against it: of the changed lines in
  the code files the analyzers read, tests left out, how many the report has a statement on, how many of those ran
  under the recorded tests and which did not, line by line, and which changed files the report does not measure at
  all. The ones that did not run, and the files not measured, are items for a person. A test report's case now also
  finds its file through the suite it is in when the suite is named after the file, as jest-junit's `{filepath}` is.
- `check` reads the names of files outside import statements for one finding and says so: a file the change deleted
  or moved that an untouched file still names is a `dangling-reference`, with the kind of every name: in a config or a
  script (a warning: wiring that now points at nothing), in a string or a dynamic import (a warning for a person, since
  such a name is a guess that the file is loaded at run time), or in documentation (a note; changelogs and release
  notes are left alone, since they name deleted files on purpose). `dangling_references` in the JSON, a rule in the
  SARIF. A stranded file now lists every link the change cut, with its kind. The report's caveat about names that fit
  several files now covers the names the analyzers found in code, not only those in configs and scripts.
- A module turned into a package (`x.py` moved into `x/`, with an `x/__init__.py` in its place), or the reverse, keeps
  its import name, so `check` no longer reports its importers as dangling; and a package `__init__.py` deleted while a
  module the name names stays (or goes with it, in which case the module's own row names the referrer) is no longer a
  `dangling-reference`, since Python only ran it on the way. A file name in a string of Python code,
  `"setup.py"`, is a path, not the dotted name `setup.py`, so it no longer links the file to a top-level module `setup`.
- `tools/backtest.py` publishes the test behind the order `triage` uses and the review set `impact` draws. On any
  repository's history it scores the files each change touched with what git knew when the change landed, against
  the fixes of the following 30 days, and compares how often files one import apart, two apart, in the same
  directory or unrelated change together. [The backtest](docs/guide/backtest.md) in the guide is its output on one
  repository, and the wording of `triage` and the guide follows those numbers.
- `tools/reviewer_match.py` publishes the test behind *who can look*: on a repository's merged pull requests, read
  through the GitHub command line, it offers triage's reviewer list at each pull request's base with the clock at
  its merge, alongside two baselines from git alone and one from the review data, and scores each against who
  reviewed. [The reviewer match](docs/guide/reviewer-match.md) in the guide is its output on one repository: naming
  the people behind the changed files beats naming the busiest people, triage's ownership does not beat a plain
  count of recent committers to those files, and most reviewing there was done by two people git cannot name.
- `tools/deletions.py` replays every change of a repository's history that deleted or moved a code file through
  `check` and says what became of each name left behind: removed, restored, or still there, and after how long. On
  one repository's last year every name it reports is a real loose end; the three false alarms it exposed are the fixes
  above.
- The site's landing page now leads with a brief: the command line, the scope and the three steps *Look first*, *What
  changed* and *Validation* of `tessri brief` on the latest change on this repository's `main`, with the candidate
  tests labelled apart from the checks the host ran, and the drawing's key telling an import statement from a name
  found in a string, a config or a dynamic import. The demo pages, the brief and the HTML report of this repository,
  are rebuilt from it on every push to `main`. The guide's reference gains the backtest and the reviewer match.
- A version tag publishes the package. `git tag v0.4.0 && git push origin v0.4.0` runs `.github/workflows/release.yml`:
  `tools/release_notes.py` checks that the tag is the version `tessri/__init__.py` and `pyproject.toml` state and that
  this file has the version's dated section, then the sdist and the wheel are built, the wheel is installed on 3.11
  and 3.12 and runs `tessri scan` on the repository, PyPI accepts the workflow's identity (trusted publishing, nothing
  secret in the repository), and the GitHub release is created with the section as its notes. Nothing of Tessri had
  reached PyPI before: `pip install tessri` found nothing through 0.3.0, which was prepared and never uploaded.

## 0.3.0 (2026-11-06)

0.3.0 reached `main` on this day and was never tagged or uploaded, so the paragraph below about PyPI came true
only with 0.4.0.

**On PyPI.** `pip install tessri`, `uvx tessri scan .` and `pipx run tessri` install the real package, and so do
the `command: tessri` of the MCP profiles, the `pip install tessri` of a Copilot setup step and of the report
workflow.

**The old name is gone**, as 0.2.0 announced: the `repolife` command and module, `.repolife.toml` and
`[tool.repolife]`, the `repolife.analyzers` entry-point group, and the reading of a receipt, skill files and
`AGENTS.md` markers that 0.1.x wrote. To upgrade: rename `.repolife.toml` to `.tessri.toml` and `[tool.repolife]`
to `[tool.tessri]` (0.3.0 does not read the old names and does not notice them, where 0.2.x said so on every
run); register analyzer plugins under `tessri.analyzers`; and move an integration that 0.1.x installed with
`tessri integration update` on 0.2.x before upgrading, or delete its files by hand and install again.
`import repolife` is an ImportError.

Behaviour changes:

- `triage`, `check` and `brief` without `--since` compare the branch with the default branch instead of looking at
  the uncommitted work alone: the branch the remote declares (`origin/HEAD`), else the first of `origin/main`,
  `origin/master`, `main` and `master` that exists, else `HEAD`. On the default branch itself the change is still
  the uncommitted work, and `--since HEAD` keeps the old meaning everywhere. The ref chosen is `change.since` in
  the output and in the first line of the page, so a reader sees which base the change was judged against. The
  MCP `since` argument has the same default.
- `--repo PATH` on every command. `scan`, `graph` and `integration` keep the positional root as the same thing,
  and giving both with different values is an error.
- `tessri init` is folded into `tessri integration`. `--agent config` seeds `.tessri.toml` with every option
  commented out; the file is yours from the moment it is written, `update` never rewrites it, a deleted one is
  forgotten rather than recreated, and `remove` deletes it only while it is untouched and otherwise just stops
  recording it (a target of kind `seed` in the receipt; `manifest_version` stays 1). `--agent report` installs
  the weekly scan workflow at `.github/workflows/tessri-report.yml`, managed like a skill, pinned to the Tessri
  that installed it (`pip install tessri==<version>`; after an upgrade `status` says `installed-outdated` and
  `update` refreshes the pin) in place of `--install-spec`. The `.gitignore` line `init` added (`.tessri/`, a directory
  nothing writes) is not carried over, and a workflow `init` wrote at `.github/workflows/tessri.yml` is an
  unmanaged file to delete once `report` is installed.
- The skill's note on roots says `--repo` first; `tessri --help` no longer mentions the former name.

Also in this version, since 0.2.0:

- `tessri integration install --agent review`: the review brief on every pull request, whoever or whatever wrote
  it. The workflow (`.github/workflows/tessri-review.yml`, managed like a skill and pinned the same way) checks the
  branch out as pushed with the whole history, runs `tessri brief --since origin/<base>` with the pull request's
  own base, posts the page as one comment that it finds again by its marker and updates in place on every push,
  puts the same page in the run's summary, and keeps it with `check --format sarif --locationless omit` as an
  artifact. From a fork, whose token cannot comment, the summary and the artifact are all there is. The gate and
  the upload to code scanning are commented lines, the team's to turn on. This repository runs it on its own pull
  requests.
- `tessri brief --since <base>`: one page to hand a change over, with the sections the review-brief design asked for.
  It is triage and check from one pair of analyses (the base and the working tree, each analysed once, so the page
  costs what `check` costs): the exact state the evidence describes (full base and HEAD, the commits on the way in
  their authors' words, the uncommitted files in scope), the files to look at first with triage's reasons, the
  findings, the candidate tests kept apart from the checks the host ran (`--ran`, repeatable, recorded verbatim;
  without it the page says that none was recorded, and an execution is never inferred from a candidate), who can
  look, what needs a person, and what was not analysed (a changed file in a language without an analyzer is named,
  not dropped). Every shortened list carries its count, and the JSON (`kind: "brief"`) holds the whole `triage` and
  `check` objects. The MCP server serves it as `tessri_brief` (`ran` is an array of strings); the skill, the
  `AGENTS.md` block and Copilot's instructions name it. `triage.compute` and `since.check` take analyses the caller
  made (`analysis=`, `analyses=`); without them they work as before.
- `tessri mcp`: the questions as Model Context Protocol tools over stdin/stdout, with nothing installed. Eight
  read-only tools mirror the commands (`tessri_repos`, `tessri_scan`, `tessri_why`, `tessri_impact`,
  `tessri_graph`, `tessri_triage`, `tessri_check`, `tessri_brief`); each returns the command's `--format json` object as
  `structuredContent` and its text as `content`, from one analysis. `--root` is repeatable, so one server serves
  several checkouts and a tool names one with `root`. A mistake in the arguments is a tool result in the sentence
  the command prints; a malformed request is a JSON-RPC error. Both the 2026-07-28 revision of the protocol
  (`_meta` version, `server/discover`) and the earlier `initialize` handshake are spoken. An analysis is reused
  across calls while the checkout's fingerprint holds (HEAD, the changed and untracked paths with their sizes and
  modification times, the configuration files) and for at most an hour, so asking several questions about one
  checkout costs one analysis (2.5 to 3 seconds on a 2,000-file repository, 30 to 85 ms to check the fingerprint);
  `tessri_triage` and `tessri_check` always read afresh.
- `tessri integration` gains three profiles: `mcp` (the `mcpServers.tessri` entry in `.mcp.json`), `vscode` (the
  `servers.tessri` entry in `.vscode/mcp.json`) and `copilot` (`.github/instructions/tessri.instructions.md`, the
  skill under Copilot's frontmatter). An entry profile records the entry, not the file: an existing file keeps its
  other entries; one that cannot be read as JSON, or already has the entry, is a conflict. `status` says per host
  which file carries its instructions, which points it at the server, and what is left to do, with the line to run
  for Codex and the JSON to paste for Copilot's coding agent. The skill and `AGENTS.md` block name the tools.
- JSON: the scan object carries `kind: "scan"` and the impact object `schema_version`, which the JSON guide said it
  had; nothing else changed and `schema_version` stays 1.
- A page (`.html`) wires in what it loads and only mentions what it says. Its `src` attributes, `<link href>` and
  inline `<script>` code are wiring, as before (`<script src="/src/main.tsx">` makes that file an entry point);
  its text, its hyperlinks and its other attributes are now a mention, like a README's, where every path in the
  file used to count as wiring. On this repository the landing page's sentence about `tessri/graph.py` had made
  that file and `tessri/config.py` "reachable from a production entry point" through `config-ref: site/index.html`;
  `why` now shows the import route and lists the page under `mentioned in docs`. A page under `docs/` is all
  mention, as before.
- `why` says what evidence each edge rests on, with the names `impact` uses: `pkg/loader.py (string)` under
  `depended on by` or `depends on`, and `-(string)->` for a hop of the `reached via` route; an import statement
  goes unmarked. The JSON carries the same under `graph.kinds` (`reached_via`, `dependents`, `depends_on`); no
  existing key changed.

## 0.2.0 (2026-11-04)

**Tessri is the new name of repolife.** The project, the Python package, the command, the configuration, the
integration receipt, the bundled skill, the SARIF output and the repository are all called `tessri` now. The old
name keeps working through 0.2.x and goes away in 0.3.0:

- `repolife ...` and `python -m repolife ...` run the same program after a one-line notice on stderr.
  `import repolife` works with a `DeprecationWarning`, and `repolife.<module>` resolves to `tessri.<module>` as an
  attribute.
- `.repolife.toml` and `[tool.repolife]` are read when `.tessri.toml` and `[tool.tessri]` are absent, with a notice
  on stderr. When both exist the new one is in force and the old one is ignored, also with a notice.
- An integration receipt, skill files and AGENTS.md markers written by 0.1.x are recognised by
  `tessri integration status` and moved to the new names by the next `install`, `update` or `remove`: the skill is
  created at `.claude/skills/tessri/SKILL.md` (or `.agents/skills/tessri/SKILL.md`) and the old file removed in the
  same run, the AGENTS.md block is rewritten in place with the new markers, and the receipt is written as
  `.tessri-integration.json` with the old file deleted. A user-modified old file is a conflict, as before, and then
  nothing is written.
- `tessri init` replaces an AGENTS.md block that `repolife init` wrote instead of adding a second one.
- Analyzer plugins registered under the `repolife.analyzers` entry-point group keep loading.

What a reader of the output sees change:

- JSON: `meta.tool.name`, and the top-level `tool.name` of scan and integration results, is `tessri`.
  `schema_version` stays 1: no key changed its name or meaning.
- SARIF: the driver is `tessri`, rule ids are `tessri/<kind>`, the property bags are `tessri/finding`,
  `tessri/check` and `tessri/locationless`, and the URI base id is `TESSRI_ROOT`. Code-scanning alert continuity
  from a `repolife/<kind>` rule does not carry over.
- Markdown: the scan heading is `# Tessri report: <repo>`. Error lines on stderr start with `tessri:`.

Also in this version:

- `check --format sarif --locationless keep|omit`. GitHub code scanning rejects a log that contains a result
  without a location; `omit` moves such findings out of `results` and whole into
  `run.properties["tessri/locationless"].omitted`, next to their `count` and the `policy`, which are recorded under
  both policies. Nothing is invented and nothing is dropped; `--fail-on` counts findings, not displayed results.
- A GitHub Actions workflow runs the test suite on Python 3.11 and 3.12 for every push to `main` and every pull
  request.
- Git history follows the renames git detects: activity, authors, fix counts, ownership credit and the review
  windows are read under a file's current name, so a move no longer restarts its history (this repository's own
  rename had made every file look one commit old). A pure move is activity but credits nobody with maintenance.
  A file rewritten beyond git's similarity threshold when moved starts over; a path re-created after a move is a new file.
- A file name that several files share names none of them. A bare `utils.py` in a config, a script or a string used
  to resolve to every `utils.py` in the repository (on one 2,000-file repository, fourteen such names fanned out to
  701 files, `__init__.py` alone to 432), making them all reachable and giving each a `string` edge; now such a name
  resolves to nothing, the scan's caveats list the names configs and scripts used with how many files each fits, and
  an `entry` in the configuration still means every file it fits. The bare `__init__.py` and `__main__.py` never
  name a file. Verdicts on that repository did not change; a third of its `string` edges were this.
- `check` and `triage` follow the renames git detects. A moved file is one changed file under its new name, with the
  lines edited on the way (a pure move has none) and its old path as `from`; the summary counts it under `moved`.
  `check` compares the two sides under the new names, so a renamed package keeps its cycles, dependencies and orphans
  instead of reporting them gone and new again; a file moved but still imported under its old name by a file the change
  did not touch is a `dangling-import` (`moved_to` names the new path); and moved code keeps its maintainers for the
  no-active-owner check, which used to pass it over for lack of history. `triage` ranks a moved file by the history of
  its old name instead of as a new file. History read for a dirty tree follows an uncommitted `git mv` the same way,
  and history read up to the base of a change is read under the names the tree has now. Across this repository's own
  rename, `check` went from 84 code files (37 added, 31 deleted), 17,292 lines, a false new cycle and a false resolved
  one to 53 code files (6 added, 16 modified, 31 moved), 1,790 lines and no finding; `triage` had ranked the twelve
  deleted `repolife/*.py` paths first and now ranks the moved files by their history.
- A site: the landing page and the guide at https://tianyi-zhang-02.github.io/tessri/, built from the README and
  `docs/guide/` by `tools/build_site.py` with nothing installed (no framework, no webfont, no request to anyone
  else), and published by a workflow on every push to `main` that touches them.

## 0.1.0

repolife: `scan` (Markdown, JSON and a self-contained HTML report), `why`, `graph`, `impact` with edge provenance
and `--edges imports`, `triage`, `check` (Markdown, JSON and SARIF), `init` and `integration` with a receipt, a
bundled agent skill and a `meta` block on every JSON output. Never tagged; see the git history.
