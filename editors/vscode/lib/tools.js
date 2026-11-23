// Tessri's questions as tools for the editor's chat agent (VS Code's language model tool API): the same names,
// descriptions and arguments as the MCP server's tools, less `root`, which here is a workspace folder's name.
// `package.json` declares them statically; the test suite checks that the two lists agree.

"use strict";

const ROOT = { type: "string", description: "the workspace folder's name, when the window has several; optional otherwise" };
const SINCE = { type: "string", description: "a commit, branch or tag; the change is where it and HEAD part, plus uncommitted work. Absent: the default branch (origin/HEAD, else origin/main, origin/master, main or master; HEAD when none exists). HEAD: only uncommitted work" };
const REPORT = { type: "array", items: { type: "string" }, default: [], description: "test reports the host wrote, as JUnit XML (pytest --junitxml, jest-junit and the like), paths relative to the root: the candidate tests are held against what ran" };
const COVERAGE = { type: "array", items: { type: "string" }, default: [], description: "coverage reports the host wrote (Cobertura or Clover XML, lcov, or coverage.py's JSON), paths relative to the root: the lines the change adds or changes are held against the statements that ran" };

const TOOLS = [
  {
    name: "tessri_impact",
    toolReferenceName: "tessriImpact",
    displayName: "Tessri: impact",
    userDescription: "What a change to a file or directory can reach: dependents, candidate tests, maintainers",
    modelDescription: "What a change to one file or directory can reach: dependents by distance, the tests that reach it, the owners of the affected code, and the kinds of evidence followed. Ask before changing a file.",
    inputSchema: {
      type: "object",
      properties: {
        root: ROOT,
        target: { type: "string", description: "a file or directory, repository-relative, or a dotted package name" },
        edges: { type: "string", enum: ["all", "imports"], default: "all", description: "all: recognized dependency syntax, package files and references found in strings or dynamic loading; imports: syntax and package files only" },
        hops: { type: ["integer", "null"], minimum: 1, default: null, description: "follow edges at most this many steps away (null: any number)" },
        report: REPORT,
      },
      required: ["target"],
    },
    invocation: (input) => `Asking Tessri what a change to ${input.target || "the target"} can reach`,
  },
  {
    name: "tessri_why",
    toolReferenceName: "tessriWhy",
    displayName: "Tessri: why",
    userDescription: "The evidence behind one file: reachability, history, owners, dependents",
    modelDescription: "The evidence behind one file's verdict: reachability and entry points, history, owners, dependents and dependencies with the kind of evidence behind each edge. Ask to verify a claim about a file before acting on it.",
    inputSchema: {
      type: "object",
      properties: { root: ROOT, path: { type: "string", description: "the file: a repository-relative path, a unique path suffix, or a module name" } },
      required: ["path"],
    },
    invocation: (input) => `Asking Tessri about ${input.path || "a file"}`,
  },
  {
    name: "tessri_triage",
    toolReferenceName: "tessriTriage",
    displayName: "Tessri: triage",
    userDescription: "Which files of a change deserve a person first, and who can look",
    modelDescription: "Which files of a change deserve a person first, what the change can ripple into, and who can look. Ask when reviewing a change.",
    inputSchema: { type: "object", properties: { root: ROOT, since: SINCE } },
    invocation: (input) => `Asking Tessri to triage the change${input.since ? ` since ${input.since}` : ""}`,
  },
  {
    name: "tessri_check",
    toolReferenceName: "tessriCheck",
    displayName: "Tessri: check",
    userDescription: "What a change did to the structure: new orphans, cycles, imports of deleted files",
    modelDescription: "What a change did to the structure: new orphans and cycles, imports of deleted files, changed code nobody maintains, with a finding for each. Ask when a change is done.",
    inputSchema: { type: "object", properties: { root: ROOT, since: SINCE } },
    invocation: (input) => `Asking Tessri what the change${input.since ? ` since ${input.since}` : ""} did to the structure`,
  },
  {
    name: "tessri_brief",
    toolReferenceName: "tessriBrief",
    displayName: "Tessri: brief",
    userDescription: "One page to hand a change over for review",
    modelDescription: "One page to hand a change over for review: triage and check from one analysis, the commits and uncommitted files the evidence covers, the files to look at first, the findings, candidate tests apart from the checks the host ran, who can look and what needs a person. Pass the checks you actually ran in `ran`.",
    inputSchema: {
      type: "object",
      properties: {
        root: ROOT,
        since: SINCE,
        ran: { type: "array", items: { type: "string" }, default: [], description: "the checks the host actually ran, one string each with the command, its result and exit code, recorded verbatim; without it the brief says that none was recorded" },
        report: REPORT,
        coverage: COVERAGE,
      },
    },
    invocation: (input) => `Asking Tessri for the review brief${input.since ? ` since ${input.since}` : ""}`,
  },
  {
    name: "tessri_scan",
    toolReferenceName: "tessriScan",
    displayName: "Tessri: scan",
    userDescription: "How the codebase fits together and what nobody maintains",
    modelDescription: "How the codebase fits together and what nobody maintains: every file's status, volume, hotspots, ownership, review load, cleanup candidates and the caveats of the analysis. Ask to get to know a repository; not for every task.",
    inputSchema: { type: "object", properties: { root: ROOT, full: { type: "boolean", default: false, description: "include the per-file table (large on a big repository)" } } },
    invocation: () => "Asking Tessri for the repository overview",
  },
  {
    name: "tessri_graph",
    toolReferenceName: "tessriGraph",
    displayName: "Tessri: graph",
    userDescription: "Who imports whom: modules, cycles and the few dependencies to cut",
    modelDescription: "Who imports whom: the modules, the dependencies between them, the cycles and the few dependencies to cut, with owners; or every import as a pair at the file level.",
    inputSchema: {
      type: "object",
      properties: {
        root: ROOT,
        level: { type: "string", enum: ["module", "file"], default: "module", description: "file: every import as a pair (large on a big repository)" },
        module_depth: { type: ["integer", "null"], minimum: 1, default: null, description: "a module is the first N directories of a path (null: split by size)" },
        include_tests: { type: "boolean", default: false, description: "draw test files too" },
      },
    },
    invocation: () => "Asking Tessri for the module graph",
  },
];

/** The static part of each tool, as `package.json` declares it. */
function declarations() {
  return TOOLS.map((t) => ({
    name: t.name,
    toolReferenceName: t.toolReferenceName,
    displayName: t.displayName,
    userDescription: t.userDescription,
    modelDescription: t.modelDescription,
    canBeReferencedInPrompt: true,
    icon: "$(type-hierarchy)",
    inputSchema: t.inputSchema,
  }));
}

module.exports = { TOOLS, declarations };
