# Security

Tessri reads a repository and its git history and writes a report. It runs no code from the repository it reads,
makes no network connection, and writes nothing into the repository; the one file it writes is its cache, in the
user's cache directory. Its surfaces are the parsers (Python's own, the JavaScript scanner, the readers of configs
and markup), the MCP server on standard input and output, the hooks, and the files `tessri integration install`
writes into a repository with a receipt.

To report a vulnerability, open a
[private security advisory](https://github.com/tianyi-zhang-02/tessri/security/advisories/new) on this repository;
it reaches the maintainer and nobody else. Please do not open a public issue for it. A fix ships in the next release,
the advisory is published with it, and the changelog names it.

The latest release is the supported one. A report against an older version is read, and the fix goes into the latest.
