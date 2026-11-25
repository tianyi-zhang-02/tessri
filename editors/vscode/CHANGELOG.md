# Changelog

## 0.1.0

- A code lens over each Python, JavaScript and TypeScript file: dependents, candidate tests, maintainers and the
  last commit, from `tessri impact` and `tessri why`.
- A hover over each definition: which reaching tests name it, or that none does, or that its name was not
  searched (a Tessri newer than 0.4.0), then the file's status, reachability, maintainers, history, dependents and tests,
  linking to the two pages.
- What the uncommitted work did to the structure, as problems on the files it concerns: a deleted file still
  imported (an error, at the import), a new file nothing reaches, the import that closes a new cycle, a document or
  config still naming a deleted file, changed code nobody active maintains; from `tessri check` since the base,
  checked again after each save. The status bar counts them and opens the page. `tessri.problems` turns it off.
- Commands for `why`, `impact`, `triage`, `check` and `brief`, as read-only pages; the Markdown ones open in the
  preview.
- Tessri's seven questions as tools for the chat agent (`#tessriImpact` and the rest).
- One `tessri mcp` server per workspace folder, started on the first question and kept with the window.
