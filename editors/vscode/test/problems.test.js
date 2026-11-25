"use strict";

// `lib/problems.js` on a hand-made check result: one problem per file, the check's severity (or the fallback), the
// words for each kind, the needles that find the line, and the status bar's summary.

const test = require("node:test");
const assert = require("node:assert/strict");
const { problems, needles, lineOf, summary } = require("../lib/problems");

const CHECK = {
  findings: [
    { id: "dangling-import:old/thing.py", kind: "dangling-import", severity: "block" },
    { id: "dangling-reference:gone.py", kind: "dangling-reference", severity: "info" },
    { id: "new-orphan:stranded", kind: "new-orphan", severity: "warn" },
    { id: "new-orphan:added", kind: "new-orphan", severity: "info" },
    { id: "cycle-grew:app+core+util", kind: "cycle-grew", severity: "warn" },
    { id: "orphan-resolved:all", kind: "orphan-resolved", severity: "info", files: ["x.py"] },
  ],
  dangling_imports: [{ deleted: "old/thing.py", importers: ["a.py", "b/c.py"], moved_to: "new/thing.py" }],
  dangling_references: [
    { deleted: "gone.py", referrers: [{ path: "docs/guide.md", kind: "doc" }] },
    { deleted: "cfg.py", referrers: [{ path: "setup.cfg", kind: "config" }, { path: "loader.py", kind: "string" }], moved_to: "conf/cfg.py" },
  ],
  orphans: { new: [{ path: "scripts/run.py", how: "added" }, { path: "lib/left.py", how: "stranded", was_reached_from: ["lib/main.py", "tool.toml"], reached_kinds: { "lib/main.py": "import", "tool.toml": "config" } }] },
  cycles: {
    new: [{ modules: ["pkg", "svc"], closing: [{ from: "pkg", to: "svc", examples: [["pkg/__init__.py", "svc/x.py"]] }, { from: "svc", to: "pkg", examples: [] }] }],
    grown: [{ modules: ["app", "core", "util"], added_modules: ["util"], closing: [{ from: "util", to: "core", examples: [["util/fmt.py", "core/base.py"], ["util/io.py", "core/base.py"]] }] }],
  },
  unowned: [{ path: "legacy/old.py", lines: 12, last_owner: "Ada", owner_idle_days: 400 }, { path: "legacy/none.py", lines: 1, last_owner: null, owner_idle_days: null }],
};

test("one problem per file, the check's severity where it has one and the fallback where it has none, ranked", () => {
  const out = problems(CHECK);
  assert.deepEqual(
    out.map((p) => [p.severity, p.path, p.kind]),
    [
      ["block", "a.py", "dangling-import"],
      ["block", "b/c.py", "dangling-import"],
      ["warn", "legacy/none.py", "no-active-owner"],
      ["warn", "legacy/old.py", "no-active-owner"],
      ["warn", "lib/left.py", "new-orphan"],
      ["warn", "loader.py", "dangling-reference"], // no finding for `cfg.py`: the fallback
      ["warn", "pkg/__init__.py", "new-cycle"], // no finding for `pkg+svc`: the fallback
      ["warn", "setup.cfg", "dangling-reference"],
      ["warn", "util/fmt.py", "cycle-grew"],
      ["info", "docs/guide.md", "dangling-reference"],
      ["info", "scripts/run.py", "new-orphan"],
    ],
  );
  assert.ok(!out.some((p) => p.path === "x.py"), "a resolved orphan is good news, not a problem");
  assert.deepEqual(problems({ findings: [], orphans: { new: [] }, dangling_imports: [], cycles: {} }), []);
  assert.deepEqual(problems({}), []);
});

test("the words name the file that is gone or moved, what the referrer is, and what to do", () => {
  const by = Object.fromEntries(problems(CHECK).map((p) => [`${p.path}:${p.kind}`, p]));
  assert.equal(by["a.py:dangling-import"].message, "`old/thing.py` was moved to `new/thing.py`, and this file still imports it under its old name. Update the import to the new path in the same change.");
  assert.deepEqual(by["a.py:dangling-import"].needles, ["old/thing.py", "old.thing", "old/thing", '/thing"', "/thing'", "thing.py"]);
  assert.equal(by["docs/guide.md:dangling-reference"].message, "`gone.py` was deleted, and this document still names it: a sentence that is now wrong. Update the documentation in the same change.");
  assert.equal(by["setup.cfg:dangling-reference"].message, "`cfg.py` was moved to `conf/cfg.py`, and this config still names it by its old name: wiring that now points at a file that is gone. Update the name in the same change, or restore the file.");
  assert.match(by["loader.py:dangling-reference"].message, /^`cfg\.py` was moved to `conf\/cfg\.py`, and a string in this file still names it by its old name: the analysis's guess .* Check whether it does; if so, update the name in the same change or restore the file\.$/);
  assert.equal(by["scripts/run.py:new-orphan"].message, "Nothing reaches this file: no entry point, test or config imports it, so as far as the analysis can tell it is dead on arrival. Import it from where it is meant to be used, add a test that does, or drop it.");
  assert.equal(by["lib/left.py:new-orphan"].message, "Nothing reaches this file any more: the change removed the last way to it (it was reached from `lib/main.py`, `tool.toml` (config)). Delete it with the change, or restore the link.");
  assert.deepEqual(by["lib/left.py:new-orphan"].needles, []);
  assert.equal(by["pkg/__init__.py:new-cycle"].message, "This import closes a cycle: modules `pkg`, `svc` now depend on each other, through `svc/x.py`. Remove or invert the new dependency, or move what both need into a module they both depend on.");
  assert.deepEqual(by["pkg/__init__.py:new-cycle"].needles, ["svc/x.py", "svc.x", "svc/x", '/x"', "/x'", "x.py"]);
  assert.equal(by["util/fmt.py:cycle-grew"].message, "This import draws `util` into an existing cycle with `app`, `core`, through `core/base.py`. Remove or invert the new dependency, or move what both need into a module they both depend on.");
  assert.equal(problems(CHECK).filter((p) => p.kind === "cycle-grew").length, 1, "one problem per closing file, not per example");
  assert.equal(by["legacy/old.py:no-active-owner"].message, "Nobody active maintains this file: its last maintainer, Ada, has not committed in 400 days. Have someone who knows the code look before merging, or assign an owner.");
  assert.equal(by["legacy/none.py:no-active-owner"].message, "Nobody active maintains this file: its history names nobody who is still active. Have someone who knows the code look before merging, or assign an owner.");
});

test("needles and the line they find", () => {
  assert.deepEqual(needles("pkg/sub/__init__.py"), ["pkg/sub/__init__.py", "pkg.sub", "pkg/sub/__init__", '/__init__"', "/__init__'", "__init__.py"]);
  assert.deepEqual(needles("web/index.js"), ["web/index.js", "web/index", '/index"', "/index'", "index.js"]); // no dotted module for JavaScript
  assert.deepEqual(needles("b.py"), ["b.py", "b", '/b"', "/b'"].filter((s) => s !== "b")); // a one-letter module would match anything
  assert.deepEqual(needles("Makefile"), ["Makefile", '/Makefile"', "/Makefile'"]);
  const text = 'import os\nfrom pkg import sub\nimport pkg.sub.thing\nx = "./thing"\n';
  assert.equal(lineOf(text, needles("pkg/sub/thing.py")), 2);
  assert.equal(lineOf(text, needles("pkg/sub/__init__.py")), 2); // `pkg.sub` is spelled on the third line; `from pkg import sub` does not spell it
  assert.equal(lineOf(text, needles("web/thing.js")), 3); // `/thing"`
  assert.equal(lineOf(text, needles("elsewhere/none.py")), 0);
  assert.equal(lineOf("", []), 0);
  assert.equal(lineOf("a\r\nimport pkg.b\r\n", ["pkg.b"]), 1);
});

test("the summary counts by severity in the check's order, or says there is nothing", () => {
  assert.equal(summary(problems(CHECK)), "2 block · 7 warn · 2 info");
  assert.equal(summary([{ severity: "warn" }]), "1 warn");
  assert.equal(summary([]), "no findings");
});
