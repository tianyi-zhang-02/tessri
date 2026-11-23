# A quarter of the time: one pass over each tree, and a cache that changes no number

Every Tessri command reads the repository into one picture and answers from it. For a while the picture cost about three seconds on a repository of two thousand files, and every query paid it again, because a hook that fires after each edit and a server that answers each tool call cannot carry state between runs. This is what the three seconds were made of, the two things that cut them, and the rules the cache had to keep so that nothing a page says depends on whether it was warm.

![One pass over the files and the history: inventory, textrefs and the analyzers feed the graph and the analysis; gitlog and ownership join it; every command is a view of the one Analysis, and the cache sits beside the analyzers.](figures/pipeline.svg)

## Where the time went

The first measurement was crude and enough: eight queries on a repository of 2,034 records and 1,429 commits took 30.8 seconds, so every query paid about 3.3 seconds before it did anything of its own. Reading git took a tenth of a second of that. The rest was the analysis, and most of the analysis was the Python analyzer walking the syntax tree of every file.

It walked everything because it was looking for three kinds of things: import statements, docstrings, and names in strings or dynamic imports (`importlib.import_module("pkg.mod")`, a module name in a configuration dictionary). The first two live in statements. The third lives in expressions, and expressions are most of a tree. Visiting every expression of every statement of every file is what cost the time, and the strings it found were rare.

## The one pass

Every string literal holds a quote character. That sounds too obvious to be useful, but it is the whole trick. Before walking a file, the analyzer counts, line by line, how many of the lines up to that point hold a quote. A statement spans lines `first` to `end`; if the count does not change across them, no string literal can be inside, and the statement's expressions are never visited. Import statements and docstrings are read from the statements themselves, as before. The walk that was most of a scan now visits the expressions of the few statements that can hold a string, and finds the same things: before it shipped, the old and the new reading were run over the repositories we had on hand and the edges they found compared.

On the repository of 1,900 files, 730 of them Python, `scan` went from 3.7 seconds to 2.6. That was the pass.

## The cache

The second cut is the one with rules. What an analyzer reads from a file is now kept between runs, and a second run parses only what changed: `scan` on the same repository takes 0.6 seconds warm, `impact` 2.5 cold and 0.6 warm, `brief` 4.7 and 1.8.

| Command | Before | Cold | Warm |
|---|---|---|---|
| `scan` | 3.7 s | 2.6 s | 0.6 s |
| `impact` | | 2.5 s | 0.6 s |
| `brief` | | 4.7 s | 1.8 s |

These are recorded timings from one local run, not a portable benchmark. The machine and interpreter were not
captured with this table, so the exact speedup is not reproducible from the post alone. Cache behavior and unchanged
output are the claims checked by the tests; timing the same commands on another checkout is a separate measurement.

The rules matter more than the numbers, because a cache is the easiest way to make a tool lie.

**An entry is keyed by content, never by place.** The key is the analyzer, the format of what it keeps, and a digest of the file's text. A file that moved is found again under its new name; a file that changed is read again; nothing in an entry depends on what else the repository holds, so no entry can go stale because a neighbour changed.

**One file per repository, shared by everything that reads it.** The store is a JSON file in the user's cache directory, named after the repository's git directory. Every worktree of the repository shares it, and so does the scratch copy of the base commit that `check` extracts, which is why a `check` against a base that was analysed last week costs little. Nothing is ever written into the repository being read.

**Replaced whole, atomically.** The file is written to a temporary name and renamed over the old one, so a run that stops halfway leaves the previous cache intact. Entries no run has used for thirty days go at the next write.

**It changes no number.** The same tree and history give the same output with the cache, without it (`--no-cache` on any command, `tessri mcp --no-cache`, or `cache = false` in the configuration) and after the directory is deleted. The suite checks that: a warm run gives the cold run back byte for byte, a changed file is read again and only it, and `check` shares the store with the scratch copy of its base. If the cache ever changed a result, that would be a bug in the analyzer's idea of what it depends on, and those tests are there to catch it.

## What it changed

A hook that runs after every edit and a server that answers every tool call now run warm as a matter of course; the 3.3 seconds that each query paid became the price of the first one. The brief, which makes two analyses, one of the base and one of the working tree, is the command that gains most, since the base rarely changes between runs.

What we did not do: no daemon, no incremental graph, no background process. The tool is still a command that starts, reads, answers and exits, with nothing installed and nothing running. The cache is the one piece of state it keeps, it lives outside the repository, and it is allowed to disappear at any moment.

[Configuration](../guide/configuration.html) says where the cache lives on each system and how to turn it off; [Architecture](../guide/architecture.html) has the pipeline the cache sits in.
