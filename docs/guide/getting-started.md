# Getting started

Start with [a worked review](https://tianyi-zhang-02.github.io/tessri/example/): expand the import that points at
a deleted module, see which tests passed, and inspect what remains unknown. It uses a teaching repository, not a
production incident.

From a source checkout, open the new local source and evidence workbench (unreleased):

```bash
python -m tessri review --since main
python -m tessri review --since main --out /tmp/tessri-review.html
```

The first command starts a loopback-only session with explicit refresh; the second writes one offline source
snapshot. See [the review guide](review.md) for file navigation, stale results and Codex, Claude Code or Copilot
handoff. Neither command runs tests or changes the checkout.

For the script-free brief:

```bash
python -m tessri brief --since main --format html --out /tmp/brief.html
```

Open `brief.html` in a browser. Start at *Look first*, expand a finding under *Structure*, then compare candidate
tests with the host's recorded checks under *Validation*. Use `--since HEAD` to inspect only uncommitted work.
With no recorded results, validation says so.

Install Tessri, run one command in any repository, and build a single-file copy when installing is not an option.

```bash
pip install tessri            # or run it once without installing: uvx tessri scan .
tessri scan .                 # markdown report
tessri scan . --format json   # machine-readable
tessri scan . --format html --out report.html   # one page to open or share
tessri why path/to/file.py    # the evidence behind one verdict
tessri graph .                # how modules depend on each other, and the cycles
tessri impact path/to/file.py # what a change can reach, the tests that reach it, who to tell
tessri triage --since main    # the files of a change to look at first, and who can look
tessri check --since main     # what a change did to the structure, with an exit code for CI
tessri brief --since main     # one page to hand the change over: both of the above, from one analysis, with what you ran
```

Every command takes the repository root as `--repo PATH` (`scan` and `graph` also as their first argument). Without
`--since`, a branch is judged against the default branch: the one the remote declares, else `main` or `master`.

No install at all: build a single 300 KB file and drop it into any repository.

```bash
mkdir build && cp -r tessri build/       # from a checkout of this repository
python3 -m zipapp build -m tessri.cli:main -o tessri.pyz
python3 tessri.pyz scan /path/to/any/repo
```

Next: [what `scan` tells you](scan.md), or [mount the agent skill](integration.md).
