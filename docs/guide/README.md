# Tessri guide

Tessri reads a codebase and its git history and answers the questions a maintainer asks of a system that grows
faster than anyone can read it. One page per question, each with real output and with what the analysis cannot see.

- [Getting started](getting-started.md): install, run, or build a single-file copy.
- [Which command, when](when.md): the moment, the command, the MCP tool, and the first thing to read in the output.
- [What is unused: scan and reachability](scan.md): every file's status, and how reachability is decided.
- [Who maintains it](ownership.md): owners from git history, who went quiet, and `CODEOWNERS` against reality.
- [Review load](review-load.md): how much review the recent changes ask for, where, and from whom.
- [How the modules fit together](graph.md): the module graph, the cycles, and the few dependencies to cut.
- [What a change can reach](impact.md): dependents, the tests that reach a file, the evidence behind each edge.
- [Triage a change](triage.md): which changed files deserve a person first, and who can look.
- [Check what a change did to the structure](check.md): findings, the exit code for CI, and SARIF.
- [Hand a change over: the review brief](brief.md): triage and check on one page, from one analysis, with the
  state the evidence describes and what the host ran kept apart from candidate tests.
- [The HTML report](html-report.md): one offline page with the explorer.
- [Integration: skills, AGENTS.md, MCP, configuration, CI](integration.md): every profile installed with a receipt, and
  taken out again.
- [MCP: Tessri as tools](mcp.md): `tessri mcp`, the eight tools, their arguments and errors, and the profiles that
  point each agent at the server.
- [Configuration](configuration.md): `.tessri.toml` and `[tool.tessri]`.
- [JSON output](json.md): the objects, `schema_version` and the `meta` block.
- [Architecture](architecture.md): the pipeline, one view per command, and how to add a language.
- [Limits](limits.md): what is static, what is invisible, and what to read with care.
- [Formerly repolife](formerly-repolife.md): what to rename when upgrading from the old name.

Design contracts and acceptance records are in [docs/design](../design/); copyable CI and agent recipes are in
[workflow-recipes.md](../workflow-recipes.md); the examples of a review brief are in [docs/examples](../examples/).
