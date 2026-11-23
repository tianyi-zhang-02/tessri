"use strict";

// The extension against a fake `vscode` and the real server on this repository: what activation registers, that
// `package.json` agrees with the code, where a hover appears, what the lens and the hover say, what a chat tool
// returns, what a command opens, and how a missing command is reported.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const fakevscode = require("./fakevscode");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const COMMAND = (process.env.TESSRI_TEST_COMMAND || "python3 -m tessri").split(/\s+/);
process.env.TESSRI_CACHE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "tessri-vscode-test-"));

const vscode = fakevscode.install(fakevscode.make(ROOT));
vscode.config.command = COMMAND;
const extension = require("../extension");
const { Position, Range, Uri, SymbolKind } = fakevscode;
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

const context = { subscriptions: [] };
const api = extension.activate(context);
test.after(() => api.servers.dispose());

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
  assert.equal(wrong.parts[0].value, "Tessri could not answer: `elsewhere` is not a workspace folder; the folders are repolife");
  const missing = await why.invoke({ input: { path: "nope/none.py", root: "repolife" } }, token);
  assert.match(missing.parts[0].value, /^Tessri could not answer: `nope\/none\.py` is not a file/);
  const impact = await vscode.registered.tools.tessri_impact.invoke({ input: { target: "tessri/triage.py", edges: "imports" } }, token);
  assert.match(impact.parts[0].value, /^Changing tessri\/triage\.py/);
});

test("a command opens a page under the tessri scheme and asks for the Markdown preview", async () => {
  await vscode.registered.commands["tessri.impact"](triage.uri);
  const preview = vscode.calls.find((c) => c.id === "markdown.showPreviewToSide");
  assert.ok(preview, "the preview was asked for");
  assert.equal(preview.args[0].toString(), "tessri:///repolife/impact/tessri/triage.py.md");
  assert.match(api.pages.provideTextDocumentContent(preview.args[0]), /^Changing tessri\/triage\.py/);
  await vscode.registered.commands["tessri.why"](triage.uri.toString()); // a hover link passes the URI as a string
  const shown = vscode.shown[vscode.shown.length - 1];
  assert.equal(shown.document.uri.toString(), "tessri:///repolife/why/tessri/triage.py.txt");
  assert.match(shown.document.getText(), /^tessri\/triage\.py {2}\(Python/);
  vscode.window.activeTextEditor = undefined;
  await vscode.registered.commands["tessri.brief"]();
  assert.equal(vscode.messages.info[vscode.messages.info.length - 1], "Tessri: open a file of the repository first.");
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
