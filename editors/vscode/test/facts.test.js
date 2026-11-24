"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const facts = require("../lib/facts");

// Trimmed from real `tessri why` and `tessri impact` output on this repository.
const WHY = {
  path: "tessri/triage.py",
  file: { language: "Python", kind: "code", code: 344, test: false, analyzer: "python" },
  verdict: { status: "ACTIVE", confidence: null, reachability: "prod", entry_points: [], notes: [] },
  git: { tracked: true, last_commit: "2026-11-23", age_days: 0, first_commit: "2026-10-30", commits_active: 12, commits_year: 12, authors_year: 1, fixes_90: 0, fixes_year: 0 },
  owners: { state: "owned", inactive_days: 180, people: [{ name: "Tianyi Zhang", share: 100, idle_days: 0, silent: false }], codeowners: null },
};
const IMPACT = {
  target: "tessri/triage.py",
  dependents: { direct: 5, files: 8, code: 2624, share: 16.3, by_distance: [5, 3] },
  tests: { files: 24, direct: 5, paths: ["tests/test_brief.py"] },
  owners: [{ name: "Tianyi Zhang", share: 100, idle_days: 0 }],
};

test("the lens names dependents, candidate tests, maintainers and the last commit, from the two objects", () => {
  assert.equal(facts.lens(WHY, IMPACT), "Tessri: 8 dependents (5 direct) · 24 candidate tests · maintained by Tianyi Zhang 100% · last commit 2026-11-23");
  assert.equal(facts.lens(null, IMPACT), "Tessri: 8 dependents (5 direct) · 24 candidate tests · maintained by Tianyi Zhang 100%");
  assert.equal(facts.lens(WHY, null), "Tessri: maintained by Tianyi Zhang 100% · last commit 2026-11-23");
  assert.equal(facts.lens(null, null), null);
});

test("zero, one and no-active-owner read as sentences, not as numbers alone", () => {
  const lonely = { ...IMPACT, dependents: { direct: 0, files: 0 }, tests: { files: 1, direct: 1 } };
  const untracked = { ...WHY, git: { tracked: false }, owners: { state: "no-active-owner", people: [{ name: "Ada", share: 60, idle_days: 400, silent: true }, { name: "Bo", share: 40, idle_days: 200, silent: true }] } };
  assert.equal(facts.lens(untracked, lonely), "Tessri: no dependents · 1 candidate test · no active owner; last Ada 60% (silent 400d), Bo 40% (silent 200d) · no git history yet");
  const nobody = { ...WHY, owners: { state: "unknown", people: [] } };
  assert.equal(facts.lens(nobody, null), "Tessri: no usable history · last commit 2026-11-23");
});

test("more than three people are counted, not listed", () => {
  const four = [1, 2, 3, 4].map((i) => ({ name: `P${i}`, share: 25, idle_days: 0, silent: false }));
  assert.equal(facts.people(four), "P1 25%, P2 25%, P3 25% and 1 more");
  assert.equal(facts.people([]), null);
  assert.equal(facts.people({ people: four.slice(0, 1) }), "P1 25%");
});

test("the hover is a paragraph per fact, with the links last", () => {
  const text = facts.hover("compute", "tessri/triage.py", WHY, IMPACT, { why: "command:tessri.why?%5B%5D", impact: "command:tessri.impact?%5B%5D" });
  assert.deepEqual(text.split("\n\n"), [
    "**`compute`** · `tessri/triage.py`",
    "ACTIVE: reachable from a production entry point",
    "Maintained by Tianyi Zhang 100% · last commit 2026-11-23, 12 commits by 1 author in a year",
    "8 code files depend on it, 5 directly · 24 candidate tests reach it, 5 directly",
    "_Candidate tests are paths that reach the file, not runs._",
    "[Why this file](command:tessri.why?%5B%5D) · [What a change here can reach](command:tessri.impact?%5B%5D)",
  ]);
});

test("the hover says what is missing: no analyzer, nothing reaching, no tests, and leaves out what it has no object for", () => {
  const unread = { ...WHY, file: { ...WHY.file, language: "Go", analyzer: null, test: true }, verdict: { status: null, reachability: "none" } };
  const alone = { ...IMPACT, dependents: { direct: 0, files: 0 }, tests: { files: 0, direct: 0 } };
  const text = facts.hover("main", "cmd/main.go", unread, alone);
  assert.deepEqual(text.split("\n\n"), ["**`main`** · `cmd/main.go` · test file", "not analysed (no analyzer for Go)", "Maintained by Tianyi Zhang 100% · last commit 2026-11-23, 12 commits by 1 author in a year", "No code file depends on it · no test reaches it"]);
  assert.equal(facts.hover("f", "a.py", { ...WHY, verdict: { status: "ORPHAN", reachability: "none" } }, null).split("\n\n")[1], "ORPHAN: nothing reaches it: no entry point, test or config reference");
  assert.equal(facts.hover("f", "a.py", null, null), null);
  assert.equal(facts.hover("f", "a.py", null, IMPACT).split("\n\n").length, 4);
});
