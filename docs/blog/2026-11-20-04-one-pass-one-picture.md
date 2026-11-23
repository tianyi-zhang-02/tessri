# One pass, one picture: how the code is put together

Tessri is about eleven thousand lines of standard-library Python in 38 files, and one idea holds them together: a repository is read once into one picture, and every command is a view of it. This post is the map for whoever wants to change the tool: what the pass reads, what the picture holds, how the views select from it, what an analyzer has to provide to add a language, and what a change is expected to bring with it.

![One pass over the files and the history: inventory, textrefs and the analyzers feed the graph and the analysis; gitlog and ownership join it; every command is a view of the one Analysis, and the cache sits beside the analyzers.](figures/pipeline.svg)

## The pass

`inventory` lists the files, with git when there is one (`ls-files`, tracked and untracked, honouring ignores) and by walking the tree otherwise, tells languages apart by extension and counts lines; paths are always slash-separated, whatever the system. Each analyzer turns the files of one language into a `LanguageResult`: the import edges, with the kind of evidence behind each one (an import statement, a package file, a name in a string, a dynamic import), the entry points, the test files, and a function that resolves a textual reference to a file. Python goes through the `ast` module. JavaScript and TypeScript go through a scanner of our own, which handles the `.vue`, `.svelte`, `.astro` and `.mdx` blocks that hold imports, follows `tsconfig` paths, package `exports` and workspace packages, and is checked against the TypeScript compiler on real code rather than trusted. `textrefs` adds the files that configurations, CI definitions and documents name, so that a script a workflow runs is not an orphan.

`graph` builds the import graph and walks reachability from the roots, which are the entry points and the tests; a file nothing reaches is an orphan, a file only tests reach is test-only. `gitlog` reads the history, up to any revision, in one `git log` with renames followed, so a moved file keeps its past under its current name; it yields per-file activity, per-author activity, and the credit each person has in each file, with recent commits weighing more. `ownership` turns the credit into shares, a cut-off for people who went quiet, and the comparison with a `CODEOWNERS` file when there is one. `analyze` joins all of it into one `Analysis`: one record per file with its language, kind, lines, status, confidence, owner and activity, plus the graph, the ownership and the git state, including the reason when history is unavailable.

## The picture is read once

The views reuse that analysis instead of rebuilding it. Change-specific work still reads diffs, definitions and host reports; sharing the analysis is not a promise of zero additional I/O. `scan` renders the records as the report; `why` shows one file's record with the evidence lines under each claim; `graph` groups the records into modules and finds the cycles and the few edges that would cut them; `impact` walks the graph inbound from a file; `triage` ranks the files of a change; `check` compares two graphs; `brief` composes triage and check. Three of them run against another version. `triage` analyses the working tree but reads history only up to the base of the change, so the change's own commits count neither as activity nor as ownership. `check` extracts the base from git's objects into a scratch directory, analyses it with the same settings, and compares only the graph and reachability. `brief` makes those two analyses once and gives them to both.

The analyzers keep what they read from each file in the user's cache directory, keyed by a digest of the file's text, so the second run parses only what changed and answers the same; the previous post has the rules the cache keeps. Nothing is ever written into the repository being read.

## The front doors

The same views reach the reader through several doors, and the doors share everything but the framing. `tessri/cli.py` is the terminal, with Markdown, JSON, HTML and SARIF as formats; every JSON object carries a `meta` block that says which HEAD, which base and which history the analysis describes. `tessri mcp` serves the same questions as tools over newline-delimited JSON on stdin and stdout, to any host that speaks the protocol. `tessri hook` answers a coding agent's lifecycle events, after an edit and when the agent stops, with the host's own JSON. `tessri integration` writes the files that point a host at all of this, with a receipt that lets it take them out again.

## Adding a language

The engine knows no language; `graph.py` has never heard of Python. An analyzer is a class with a name, a `handles(path)` that claims files, and a `run(files, repo)` that returns a `LanguageResult`:

```python
class Analyzer(ABC):
    name: str = ""

    def handles(self, path: str) -> bool: ...

    def run(self, files: Mapping[str, str], repo: Repo) -> LanguageResult: ...


@dataclass
class LanguageResult:
    edges: dict[str, set[str]]              # importer -> imported
    indirect: dict[str, set[str]]           # edges no import statement makes
    roots: dict[str, list[str]]             # entry points, with the reason each is one
    tests: set[str]
    unparsed: set[str]
    comment_lines: dict[str, set[int]]      # extra lines to count as comments, such as docstrings
    resolve_reference: Callable[[str], set[str]]
    provenance: dict[str, dict[str, str]]   # importer -> imported -> kind of evidence
    ambiguous: dict[str, int]               # a name that fits several files, and how many
```

`repo` gives the analyzer the set of paths, a reader for file text that returns `None` for a binary or oversized file, and the cache store, which an analyzer may use to keep what it read under a digest of the text; one that ignores it is only slower. Analyzers register under the `tessri.analyzers` entry point, so a third-party package can add one without a change here. The Python analyzer is about 250 lines and is the one to read first; the JavaScript one is larger because the module systems are.

## What a change brings with it

Tests, in the suite's own style: a test builds a small repository with files and commits at fixed dates relative to now, runs the command, and asserts on the output, so the suite needs git and nothing else. This is a fixture from the triage tests, shortened:

```python
self.commit({"core/a.py": A0, "core/b.py": "from core import a\n"}, ALICE, 300, "feat: add core")
self.commit({"util/c.py": "def c():\n    return 1\n"}, BOB, 300, "feat: add util")
self.commit({"core/a.py": A0 + "def g():\n    return 'handle empty'\n"}, ALICE, 60, "fix: handle empty input")
```

A number that can be traced: every line a page prints comes from something the reader can see, a file, a commit, an edge with its kind of evidence, and what the analysis cannot see is said rather than left blank. Evidence before a ranking: an order or a threshold is tested on history with the tools in `tools/` before it ships, and a change to one comes with the numbers from another repository. The suite runs on Ubuntu with both supported Pythons and on Windows and macOS on every pull request.

The drawings on this site, this one included, come from one module too: `tools/figures.py` holds each as a viewBox, a label and a body, writes them inline for the pages and as standalone files for the README, and a test keeps the files current.

[Architecture](../guide/architecture.html) has the module table and the one cycle the tool reports about itself; [Contributing](https://github.com/tianyi-zhang-02/tessri/blob/main/CONTRIBUTING.md) has the rest.
