"use strict";

// The extension against a fake `vscode` and the real server on this repository: what activation registers, that
// `package.json` agrees with the code, where a hover appears, what the lens and the hover say, what a chat tool
// returns, what a command opens, how a missing command is reported, and, on a second folder with a change in it,
// which problems appear on which files and lines.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const fakevscode = require("./fakevscode");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const FOLDER = path.basename(ROOT); // the workspace folder's name: whatever the checkout is called
const COMMAND = process.env.TESSRI_TEST_COMMAND ? process.env.TESSRI_TEST_COMMAND.split(/\s+/) : ["python3", path.join(ROOT, "bin", "tessri")]; // the checkout's Tessri, from any folder
process.env.TESSRI_CACHE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "tessri-vscode-test-"));

const vscode = fakevscode.install(fakevscode.make(ROOT));
vscode.config.command = COMMAND;
const extension = require("../extension");
const { Position, Range, Uri, SymbolKind, DiagnosticSeverity } = fakevscode;
const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
const token = { isCancellationRequested: false };

function document(rel, lines) {
  const uri = Uri.file(path.join(ROOT, ...rel.split("/")));
  return {
    uri,
    languageId: "python",
    lines,
    getWordRangeAtPosition(position) {
      const text = lines[position.line] || "";
      const re = /[A-Za-z_][A-Za-z0-9_]*/g;
      let m;
      while ((m = re.exec(text))) if (m.index <= position.character && position.character <= m.index + m[0].length) return new Range(position.line, m.index, position.line, m.index + m[0].length);
      return undefined;
    },
    getText(range) {
      return lines[range.start.line].slice(range.start.character, range.end.character);
    },
  };
}

function symbol(name, kind, line, column, endLine, children = []) {
  return { name, kind, range: new Range(line, 0, endLine, 0), selectionRange: new Range(line, column, line, column + name.length), children };
}

const triage = document("tessri/triage.py", ["import x", "", "def compute(root, cfg, base):", "    return 1", "", "class Row:", "    def markdown(self):", "        return compute"]);
vscode.symbols = [symbol("compute", SymbolKind.Function, 2, 4, 3), symbol("Row", SymbolKind.Class, 5, 6, 7, [symbol("markdown", SymbolKind.Method, 6, 8, 7)])];

// The real file, with its real line numbers, for the hover's definition paragraph: the server reports where each
// definition is, and the fake symbol provider has to agree.
const realLines = fs.readFileSync(path.join(ROOT, "tessri", "triage.py"), "utf8").split("\n");
const real = document("tessri/triage.py", realLines);
const lineOf = (prefix) => realLines.findIndex((l) => l.startsWith(prefix));
const realSymbols = [symbol("compute", SymbolKind.Function, lineOf("def compute("), 4, realLines.length - 1), symbol("_reach", SymbolKind.Function, lineOf("def _reach("), 4, lineOf("def _reach(") + 12)];

const context = { subscriptions: [] };
const api = extension.activate(context);
test.after(() => {
  api.structure.dispose(); // its timers would otherwise start a server after the next line
  api.servers.dispose();
});

/** A repository with one commit and an uncommitted change that `check` has four things to say about. */
function changedRepository() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "tessri-vscode-change-")));
  const write = (rel, text) => {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  };
  const git = (...args) => execFileSync("git", ["-C", root, "-c", "user.name=T", "-c", "user.email=t@example.com", ...args], { stdio: "pipe" });
  write("main.py", "import pkg.a\nimport svc.x\n");
  write(".tessri.toml", 'entry = ["main.py"]\n');
  write("pkg/__init__.py", "");
  write("pkg/a.py", "import pkg.b\n\n\ndef a():\n    return pkg.b.b()\n");
  write("pkg/b.py", "def b():\n    return 1\n");
  write("svc/__init__.py", "");
  write("svc/x.py", "import pkg.a\n\n\ndef x():\n    return pkg.a.a()\n");
  write("tests/test_a.py", "import pkg.a\n");
  write("docs/notes.md", "# Notes\n\nSee pkg/b.py for the helper.\n");
  git("init", "-q");
  git("add", ".");
  git("commit", "-q", "-m", "init");
  fs.unlinkSync(path.join(root, "pkg", "b.py")); // still imported by pkg/a.py and named by docs/notes.md
  write("pkg/__init__.py", "import svc.x\n"); // pkg and svc now depend on each other
  write("pkg/orphan.py", "x = 1\n"); // nothing reaches it
  return root;
}

test("activation registers the commands, the two providers for the five languages, the page scheme and the tools", () => {
  assert.deepEqual(Object.keys(vscode.registered.commands).sort(), ["tessri.brief", "tessri.check", "tessri.impact", "tessri.restart", "tessri.showLog", "tessri.triage", "tessri.why"]);
  assert.deepEqual(vscode.registered.hovers[0].selector.map((s) => s.language), extension.LANGUAGES);
  assert.deepEqual(vscode.registered.lenses[0].selector.map((s) => s.language), extension.LANGUAGES);
  assert.ok(vscode.registered.content[extension.SCHEME]);
  assert.deepEqual(Object.keys(vscode.registered.tools), ["tessri_impact", "tessri_why", "tessri_triage", "tessri_check", "tessri_brief", "tessri_scan", "tessri_graph"]);
  assert.ok(context.subscriptions.length >= 15);
});

test("package.json declares what the code registers: commands, activation languages and the tools' schemas", () => {
  const { declarations } = require("../lib/tools");
  assert.deepEqual(pkg.contributes.languageModelTools, declarations());
  assert.deepEqual(pkg.contributes.commands.map((c) => c.command).sort(), Object.keys(vscode.registered.commands).sort());
  assert.deepEqual(pkg.activationEvents, extension.LANGUAGES.map((l) => `onLanguage:${l}`));
  for (const key of Object.keys(vscode.config)) assert.ok(pkg.contributes.configuration.properties[`tessri.${key}`], `tessri.${key} is a setting`);
  for (const t of pkg.contributes.languageModelTools) assert.ok(!("root" in (t.inputSchema.required || [])), "root is never required");
  assert.equal(pkg.main, "./extension.js");
  assert.deepEqual(pkg.dependencies, undefined);
});

test("a definition is found under its name, through its parents, and nowhere else", () => {
  const at = (line, col) => extension.definitionAt(vscode.symbols, triage, new Position(line, col));
  assert.equal(at(2, 6).name, "compute");
  assert.equal(at(6, 10).name, "markdown"); // a method, through its class
  assert.equal(at(5, 7).name, "Row");
  assert.equal(at(2, 1), null); // `def`, not the name
  assert.equal(at(7, 17), null); // a use of the name, not its definition
  assert.equal(at(0, 8), null); // an import
  assert.equal(extension.definitionAt([{ name: "compute", kind: SymbolKind.Variable, range: new Range(2, 0, 3, 0), selectionRange: new Range(2, 4, 2, 11) }], triage, new Position(2, 6)), null);
  assert.equal(extension.definitionAt(undefined, triage, new Position(2, 6)), null);
  const info = [{ name: "compute", kind: SymbolKind.Function, location: { range: new Range(2, 0, 3, 0) } }]; // the older SymbolInformation shape
  assert.equal(extension.definitionAt(info, triage, new Position(2, 6)).name, "compute");
});

test("the hover over a definition carries the file's facts from the server, with links to the two commands", async () => {
  const hover = await api.hover.provideHover(triage, new Position(2, 6), token);
  assert.ok(hover, "a hover");
  const paragraphs = hover.contents.value.split("\n\n");
  assert.equal(paragraphs[0], "**`compute`** · `tessri/triage.py`");
  assert.equal(paragraphs[1], "ACTIVE: reachable from a production entry point");
  assert.match(paragraphs[2], /^Maintained by .+ · last commit \d{4}-\d{2}-\d{2}, \d+ commits? by \d+ authors? in a year$/);
  assert.match(paragraphs[3], /^\d+ code files? depends? on it, \d+ directly · \d+ candidate tests? reach(es)? it, \d+ directly$/);
  assert.match(paragraphs[paragraphs.length - 1], /^\[Why this file\]\(command:tessri\.why\?%5B%22file.+\) · \[What a change here can reach\]\(command:tessri\.impact\?/);
  assert.deepEqual(hover.contents.isTrusted, { enabledCommands: ["tessri.why", "tessri.impact"] });
  assert.equal(paragraphs.length, 6); // the fake lines do not match the real definitions: no definition paragraph
  vscode.symbols = realSymbols;
  const onCompute = (await api.hover.provideHover(real, new Position(lineOf("def compute("), 6), token)).contents.value.split("\n\n");
  assert.match(onCompute[1], /^Named in `tests\/test_[a-z_]+\.py`(, `tests\/test_[a-z_]+\.py`)*( and \d+ more)?, of the \d+ tests that reach the file\.$/);
  assert.equal(onCompute.length, 7);
  const onReach = (await api.hover.provideHover(real, new Position(lineOf("def _reach("), 6), token)).contents.value.split("\n\n");
  assert.equal(onReach[1], "Not searched by name in the tests: too short, private or too common.");
  vscode.symbols = [symbol("compute", SymbolKind.Function, 2, 4, 3), symbol("Row", SymbolKind.Class, 5, 6, 7, [symbol("markdown", SymbolKind.Method, 6, 8, 7)])];
  assert.equal(await api.hover.provideHover(triage, new Position(7, 17), token), undefined);
  vscode.config.hover = false;
  assert.equal(await api.hover.provideHover(triage, new Position(2, 6), token), undefined);
  vscode.config.hover = true;
});

test("the lens appears once the facts are in, says the same numbers, and opens `why`", async () => {
  const other = document("tessri/mentions.py", ["x"]);
  assert.deepEqual(api.lenses.provideCodeLenses(other), []); // not yet known: asked in the background
  await api.fileFacts.get(vscode.folder, "tessri/mentions.py");
  const [lens] = api.lenses.provideCodeLenses(other);
  assert.match(lens.command.title, /^Tessri: \d+ dependents? \(\d+ direct\) · \d+ candidate tests? · maintained by .+ · last commit \d{4}-\d{2}-\d{2}$/);
  assert.equal(lens.command.command, "tessri.why");
  assert.equal(lens.command.arguments[0], other.uri);
  assert.deepEqual([lens.range.start.line, lens.range.end.line], [0, 0]);
  const outside = document("tessri/nope.py", ["x = 1"]);
  assert.deepEqual(api.lenses.provideCodeLenses(outside), []);
  assert.equal(await api.fileFacts.get(vscode.folder, "tessri/nope.py"), null);
  assert.deepEqual(api.lenses.provideCodeLenses(outside), []); // outside the analysed set: no lens, no noise
  const styled = document("site/tessri.css", ["body {}"]); // in the inventory with history, but no code: `why` answers, `impact` does not
  await api.fileFacts.get(vscode.folder, "site/tessri.css");
  assert.match(api.lenses.provideCodeLenses(styled)[0].command.title, /^Tessri: maintained by .+ · last commit \d{4}-\d{2}-\d{2}$/);
  vscode.config.codeLens = false;
  assert.deepEqual(api.lenses.provideCodeLenses(other), []);
  vscode.config.codeLens = true;
});

test("a chat tool answers with the command's text, names the folder's problem, and never throws", async () => {
  const why = vscode.registered.tools.tessri_why;
  assert.equal(why.prepareInvocation({ input: { path: "tessri/cli.py" } }).invocationMessage, "Asking Tessri about tessri/cli.py");
  const result = await why.invoke({ input: { path: "tessri/cli.py" } }, token);
  assert.match(result.parts[0].value, /^tessri\/cli\.py {2}\(Python/);
  const wrong = await why.invoke({ input: { path: "tessri/cli.py", root: "elsewhere" } }, token);
  assert.equal(wrong.parts[0].value, `Tessri could not answer: \`elsewhere\` is not a workspace folder; the folders are ${FOLDER}`);
  const missing = await why.invoke({ input: { path: "nope/none.py", root: FOLDER } }, token);
  assert.match(missing.parts[0].value, /^Tessri could not answer: `nope\/none\.py` is not a file/);
  const impact = await vscode.registered.tools.tessri_impact.invoke({ input: { target: "tessri/triage.py", edges: "imports" } }, token);
  assert.match(impact.parts[0].value, /^Changing tessri\/triage\.py/);
});

test("a command opens a page under the tessri scheme and asks for the Markdown preview", async () => {
  await vscode.registered.commands["tessri.impact"](triage.uri);
  const preview = vscode.calls.find((c) => c.id === "markdown.showPreviewToSide");
  assert.ok(preview, "the preview was asked for");
  assert.equal(preview.args[0].toString(), `tessri:///${FOLDER}/impact/tessri/triage.py.md`);
  assert.match(api.pages.provideTextDocumentContent(preview.args[0]), /^Changing tessri\/triage\.py/);
  await vscode.registered.commands["tessri.why"](triage.uri.toString()); // a hover link passes the URI as a string
  const shown = vscode.shown[vscode.shown.length - 1];
  assert.equal(shown.document.uri.toString(), `tessri:///${FOLDER}/why/tessri/triage.py.txt`);
  assert.match(shown.document.getText(), /^tessri\/triage\.py {2}\(Python/);
  vscode.window.activeTextEditor = undefined;
  await vscode.registered.commands["tessri.brief"]();
  assert.equal(vscode.messages.info[vscode.messages.info.length - 1], "Tessri: open a file of the repository first.");
});

test("the structure of the change appears as problems on the files concerned, at the line that names what is gone", async () => {
  for (const timer of api.structure.timers.values()) clearTimeout(timer); // activation scheduled a check of this checkout: not what this test is about
  api.structure.timers.clear();
  await Promise.all([...api.structure.running.values()].map((p) => p.catch(() => {})));
  api.structure.clear(vscode.folder);
  assert.equal(vscode.statusBar.visible, false);
  const changed = vscode.addFolder(changedRepository());
  vscode.config.since = "HEAD";
  try {
    await api.structure.refresh(changed);
    const at = (rel) => vscode.diagnostics.get(Uri.file(path.join(changed.uri.fsPath, ...rel.split("/"))).toString()) || [];
    const [dangling] = at("pkg/a.py");
    assert.equal(dangling.severity, DiagnosticSeverity.Error);
    assert.equal(dangling.code, "dangling-import");
    assert.equal(dangling.source, "Tessri");
    assert.deepEqual([dangling.range.start.line, dangling.range.end.character], [0, "import pkg.b".length]);
    assert.equal(dangling.message, "`pkg/b.py` was deleted, and this file still imports it. Restore the file, or update the import in the same change.");
    const [orphan] = at("pkg/orphan.py");
    assert.deepEqual([orphan.severity, orphan.code, orphan.range.start.line], [DiagnosticSeverity.Warning, "new-orphan", 0]);
    const [cycle] = at("pkg/__init__.py");
    assert.deepEqual([cycle.severity, cycle.code, cycle.range.start.line], [DiagnosticSeverity.Warning, "new-cycle", 0]);
    assert.match(cycle.message, /^This import closes a cycle: modules `pkg`, `svc` now depend on each other, through `svc\/x\.py`\./);
    const [note] = at("docs/notes.md");
    assert.deepEqual([note.severity, note.code, note.range.start.line], [DiagnosticSeverity.Information, "dangling-reference", 2]);
    assert.match(note.message, /^`pkg\/b\.py` was deleted, and this document still names it/);
    assert.deepEqual(at("svc/x.py"), []); // untouched, and nothing about it changed
    assert.equal(vscode.statusBar.text, "Tessri: 1 block · 2 warn · 1 info");
    assert.ok(vscode.statusBar.visible);
    assert.equal(vscode.statusBar.command, "tessri.check");
    assert.match(vscode.statusBar.tooltip, /^What the uncommitted work did to the structure, since HEAD: 1 block · 2 warn · 1 info\. Click for the page\.$/);

    fs.writeFileSync(path.join(changed.uri.fsPath, "pkg", "b.py"), "def b():\n    return 1\n"); // the file is back
    await api.structure.refresh(changed);
    assert.deepEqual(at("pkg/a.py"), []); // the problem went with its cause
    assert.deepEqual(at("docs/notes.md"), []);
    assert.equal(vscode.statusBar.text, "Tessri: 2 warn");

    vscode.config.problems = false;
    await api.structure.refresh(changed);
    assert.deepEqual([at("pkg/orphan.py"), at("pkg/__init__.py")], [[], []]);
    assert.equal(vscode.statusBar.visible, false);
  } finally {
    vscode.config.problems = true;
    vscode.config.since = "";
    api.structure.clear(changed);
    api.servers.drop(changed);
    vscode.removeFolder(changed);
  }
});

test("a command that is not installed is reported once, and the editor stays quiet", async () => {
  vscode.config.command = ["tessri-is-not-installed-here-7f3a"];
  api.commands["tessri.restart"]();
  assert.equal(await api.hover.provideHover(triage, new Position(2, 6), token), undefined);
  await api.fileFacts.get(vscode.folder, "tessri/triage.py").catch(() => {});
  assert.deepEqual(api.lenses.provideCodeLenses(triage), []);
  await new Promise((r) => setTimeout(r, 50));
  assert.equal(vscode.messages.warning.length, 1);
  assert.match(vscode.messages.warning[0].message, /^Tessri: `tessri-is-not-installed-here-7f3a` was not found: install Tessri/);
  assert.deepEqual(vscode.messages.warning[0].items, ["Open settings", "How to install"]);
  const tool = await vscode.registered.tools.tessri_why.invoke({ input: { path: "tessri/cli.py" } }, token);
  assert.match(tool.parts[0].value, /^Tessri could not answer: `tessri-is-not-installed-here-7f3a` was not found/);
  assert.equal(vscode.messages.warning.length, 1);
  vscode.config.command = COMMAND;
  api.commands["tessri.restart"]();
});
