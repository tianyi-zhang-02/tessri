# Contributing

Tessri is a small Python package with no dependencies, and the shape of a change matters as much as the change.

## What the code keeps

- **Standard library only.** No runtime dependency, and none for the site build or the tools in `tools/`. The test
  suite needs git, and `node` for the one test that runs the HTML page's script, which is skipped without it.
- **Python 3.11 and 3.12.** Both run in CI on every pull request; run both locally when you can.
- **Every number is traceable.** A line in a report comes from something the reader can see: a file, a commit, an
  edge with the kind of evidence behind it. What the analysis cannot see, it says it cannot see, and an empty section
  says so rather than reassuring. There is no composite score.
- **The tool never edits code** and never writes into the repository it reads. The one thing it writes is its cache,
  in the user's cache directory, and that changes no number.
- **A claim about an order or a threshold is tested on history before it ships**, with the tools in `tools/`
  (`backtest.py`, `reviewer_match.py`, `deletions.py`); the guide shows their output on one repository, and a change
  to a ranking comes with the numbers from another.

## Running it

```bash
python3 -m unittest discover -s tests
```

```bash
python3 -m unittest discover -s tests -p "test_triage.py"
```

```bash
python3 tools/build_site.py --out _site --demo && python3 -m http.server --directory _site
```

The suite takes about two minutes; the second line runs one area; the third builds the site with the demo pages and
serves it.

## Where things live

| A change to | Lives in | Comes with |
|---|---|---|
| what a command reports | the command's view in `tessri/` (`triage.py`, `since.py`, `brief.py`, …), on the one analysis in `tessri/analyze.py` | its page in `docs/guide/`, a line in `CHANGELOG.md` |
| a language | `tessri/analyzers/`, see [Architecture](docs/guide/architecture.md) | `tests/test_<language>.py` |
| an option | `tessri/config.py`, its flag in `tessri/cli.py`, the commented line in `tessri/templates.py` | `docs/guide/configuration.md` |
| what is written into other repositories | `tessri/templates.py` and `tessri/integration.py` | `skills/tessri/SKILL.md`, which must equal `templates.SKILL` (a test checks) |
| a guide page | `docs/guide/<page>.md`, linked from `docs/guide/README.md`; the site build refuses an unlinked page | |
| the landing page | `site/`, built by `tools/build_site.py` | `tests/test_site.py` |

## A pull request

- Tests for the behaviour, in the file of its area: `tests/`, one file per area, each building small repositories in
  temporary directories with fixed commit dates and asserting on the output.
- The guide page and the changelog's Unreleased section, when a reader would notice the change.
- Commit messages that say what changed and why, in sentences.
- The brief on your pull request is Tessri's own: the `review` workflow posts it as a comment. It names the files to
  look at first and the candidate tests; read it as a reviewer would.

## Telling us what Tessri got wrong

The most useful issue is a claim that is wrong: a file called unreachable that something reaches, an owner who is
not one, an edge that should not be there, a test that was never a candidate. `tessri why <path>` prints the
evidence behind every claim about a file; paste it. The issue templates ask for exactly that.
