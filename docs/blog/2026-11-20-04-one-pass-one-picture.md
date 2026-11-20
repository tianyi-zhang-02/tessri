# One pass, one picture: how the code is put together

Tessri is about ten thousand lines of standard-library Python in a few dozen files, and one idea holds them together: a repository is read once into one picture, and every command is a view of that picture. If you want to change the tool, this is the map.

![One pass over the files and the history: inventory, textrefs and the analyzers feed the graph and the analysis; gitlog and ownership join it; every command is a view of the one Analysis, and the cache sits beside the analyzers.](figures/pipeline.svg)

## The pass

`inventory` lists the files and tells languages apart. Each analyzer turns the files of one language into edges, entry points, tests and a function that resolves a name to a file: Python through the `ast` module, JavaScript and TypeScript through a scanner of our own, which is checked against the TypeScript compiler on real code rather than trusted. `textrefs` adds the files that configs, CI definitions and documents name. `graph` walks reachability from the entry points and the tests. `gitlog` reads the history, up to any revision, following renames; `ownership` turns it into who maintains what, with a yearly half-life and a cut-off for people who went quiet. `analyze` joins all of it into one `Analysis`, one record per file.

What an analyzer read from a file is kept in your cache directory, keyed by the file's content, so the next run parses only what changed and answers the same. Nothing is ever written into the repository being read.

## The views

`scan`, `why`, `graph`, `impact`, `triage`, `check` and `brief` do not read files again; they select from the picture. Three of them run against another version: `triage` reads history only up to the base of the change, so the change's own commits count neither as activity nor as ownership; `check` extracts the base from git's objects and compares the two graphs; `brief` makes those two analyses once and gives them to both. The front doors are the terminal, the JSON with its `meta` block on every object, SARIF for code scanning, `tessri mcp` for any host that speaks the protocol, and `tessri hook` for an agent's lifecycle events.

## Adding a language

The engine knows no language. An analyzer is a module that registers under the `tessri.analyzers` entry point and implements one interface: given the repository's files, return the edges with the kind of evidence behind each, the entries, the tests and a resolver. The Python analyzer is about 250 lines and is the one to read first. A new language needs no change to `graph`, `triage` or the pages.

## What a change brings with it

Three things, and [CONTRIBUTING.md](https://github.com/tianyi-zhang-02/tessri/blob/main/CONTRIBUTING.md) spells them out. Tests: the suite builds small repositories with fixed commit dates and asserts on the output, so it needs git and nothing else. A number that can be traced: every line a page prints comes from something the reader can see, and what the analysis cannot see is said rather than left blank. Evidence before a ranking: an order or a threshold is tested on history with the tools in `tools/` before it ships, and a change to one comes with the numbers from another repository.

The drawings on this site, this one included, come from one module too: `tools/figures.py` writes them inline for the pages and as files for the README, and a test keeps the files current.

[Architecture](../guide/architecture.html) has the module table and the one cycle the tool reports about itself.
