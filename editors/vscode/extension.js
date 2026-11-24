// Tessri in the editor: a code lens over each code file, a hover over each definition, the questions as commands
// and as tools for the chat agent. Everything shown comes from one `tessri mcp` child per workspace folder, the
// same server an agent would talk to, so the editor and the agent see the same numbers. The extension never edits
// code and never writes into the repository.

"use strict";

const vscode = require("vscode");
const { Client, ServerError } = require("./lib/client");
const facts = require("./lib/facts");
const { TOOLS } = require("./lib/tools");

const LANGUAGES = ["python", "javascript", "javascriptreact", "typescript", "typescriptreact"];
const SCHEME = "tessri"; // the pages a command opens: read-only documents the editor can preview as Markdown
const MEMO_MS = 60_000; // a file's facts are asked again after this, or at once after a save in its folder
const INSTALL = "https://github.com/tianyi-zhang-02/tessri#install";

function settings() {
  return vscode.workspace.getConfiguration("tessri");
}

function commandLine() {
  const given = settings().get("command");
  return Array.isArray(given) && given.length && given.every((s) => typeof s === "string" && s) ? given : ["tessri"];
}

function relative(uri) {
  return vscode.workspace.asRelativePath(uri, false);
}

/** One server per workspace folder, started on the first question and kept until the window closes. */
class Servers {
  constructor(output) {
    this.output = output;
    this.clients = new Map();
    this.warned = false;
  }

  for(folder) {
    const key = folder.uri.toString();
    let client = this.clients.get(key);
    if (!client) {
      client = new Client(commandLine(), folder.uri.fsPath, { log: (line) => this.output.appendLine(`${folder.name}: ${line}`) });
      this.clients.set(key, client);
    }
    return client;
  }

  async call(folder, name, args) {
    try {
      return await this.for(folder).call(name, args);
    } catch (err) {
      if (err instanceof ServerError && err.code === "ENOENT") this.warnMissing(err);
      else this.output.appendLine(`${folder.name}: ${name}: ${err.message}`);
      throw err;
    }
  }

  warnMissing(err) {
    if (this.warned) return;
    this.warned = true;
    vscode.window.showWarningMessage(`Tessri: ${err.message}`, "Open settings", "How to install").then((choice) => {
      if (choice === "Open settings") vscode.commands.executeCommand("workbench.action.openSettings", "tessri.command");
      else if (choice === "How to install") vscode.env.openExternal(vscode.Uri.parse(INSTALL));
    });
  }

  drop(folder) {
    const key = folder.uri.toString();
    const client = this.clients.get(key);
    if (client) client.dispose();
    this.clients.delete(key);
  }

  restart() {
    for (const client of this.clients.values()) client.dispose();
    this.clients.clear();
    this.warned = false;
  }

  dispose() {
    this.restart();
  }
}

/** `why` and `impact` of a file, asked together and kept briefly, so a lens and a hover share one pair of calls. */
class FileFacts {
  constructor(servers) {
    this.servers = servers;
    this.memo = new Map(); // key -> {at, promise, value}
  }

  static key(folder, rel) {
    return `${folder.uri.toString()}\n${rel}`;
  }

  /** The settled facts when they are in hand, null when the file is outside the analysed set, undefined while unknown. */
  peek(folder, rel) {
    const hit = this.memo.get(FileFacts.key(folder, rel));
    return hit && Date.now() - hit.at < MEMO_MS ? hit.value : undefined;
  }

  get(folder, rel) {
    const key = FileFacts.key(folder, rel);
    const hit = this.memo.get(key);
    if (hit && Date.now() - hit.at < MEMO_MS) return hit.promise;
    const entry = { at: Date.now(), value: undefined };
    entry.promise = this._fetch(folder, rel).then(
      (value) => {
        entry.value = value;
        return value;
      },
      (err) => {
        this.memo.delete(key);
        throw err;
      },
    );
    this.memo.set(key, entry);
    return entry.promise;
  }

  async _fetch(folder, rel) {
    const [why, impact] = await Promise.all([this.servers.call(folder, "tessri_why", { path: rel }), this.servers.call(folder, "tessri_impact", { target: rel })]);
    if (why.isError && impact.isError) return null;
    return { why: why.isError ? null : why.structuredContent, impact: impact.isError ? null : impact.structuredContent };
  }

  forget(folder) {
    const prefix = folder ? `${folder.uri.toString()}\n` : "";
    for (const key of [...this.memo.keys()]) if (key.startsWith(prefix)) this.memo.delete(key);
  }
}

/** The pages commands open: text kept in memory under `tessri:` URIs, replaced in place when asked again. */
class Pages {
  constructor() {
    this.texts = new Map();
    this.emitter = new vscode.EventEmitter();
    this.onDidChange = this.emitter.event;
  }

  put(name, text) {
    const uri = vscode.Uri.from({ scheme: SCHEME, path: `/${name}` });
    this.texts.set(uri.toString(), text);
    this.emitter.fire(uri);
    return uri;
  }

  provideTextDocumentContent(uri) {
    return this.texts.get(uri.toString()) || "";
  }
}

const DEFINITION_KINDS = () => new Set([vscode.SymbolKind.Class, vscode.SymbolKind.Method, vscode.SymbolKind.Constructor, vscode.SymbolKind.Enum, vscode.SymbolKind.Interface, vscode.SymbolKind.Function, vscode.SymbolKind.Struct]);

/** The definition whose name is under the position, from the language's own symbol provider; null elsewhere. */
function definitionAt(symbols, document, position) {
  const word = document.getWordRangeAtPosition(position);
  if (!word || !symbols) return null;
  const name = document.getText(word);
  const kinds = DEFINITION_KINDS();
  let found = null;
  const visit = (list) => {
    for (const s of list || []) {
      const range = s.selectionRange || (s.location && s.location.range);
      if (!range || !range.contains(position)) {
        if (s.range && s.range.contains(position)) visit(s.children);
        continue;
      }
      if (kinds.has(s.kind) && (s.name === name || s.name.endsWith(`.${name}`))) found = { name, range: word };
      visit(s.children);
    }
  };
  visit(symbols);
  return found;
}

function commandUri(command, uri) {
  return `command:${command}?${encodeURIComponent(JSON.stringify([uri.toString()]))}`;
}

class HoverProvider {
  constructor(fileFacts) {
    this.fileFacts = fileFacts;
  }

  async provideHover(document, position, token) {
    if (!settings().get("hover") || document.uri.scheme !== "file") return undefined;
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!folder) return undefined;
    const symbols = await vscode.commands.executeCommand("vscode.executeDocumentSymbolProvider", document.uri);
    const definition = definitionAt(symbols, document, position);
    if (!definition || token.isCancellationRequested) return undefined;
    let found;
    try {
      found = await this.fileFacts.get(folder, relative(document.uri));
    } catch (_) {
      return undefined; // the server is not there; the warning was shown once
    }
    if (!found || token.isCancellationRequested) return undefined;
    const item = facts.definitionFor(found.why, definition.name, position.line + 1);
    const text = facts.hover(definition.name, relative(document.uri), found.why, found.impact, { why: commandUri("tessri.why", document.uri), impact: commandUri("tessri.impact", document.uri) }, item);
    if (!text) return undefined;
    const markdown = new vscode.MarkdownString(text);
    markdown.isTrusted = { enabledCommands: ["tessri.why", "tessri.impact"] };
    return new vscode.Hover(markdown, definition.range);
  }
}

class LensProvider {
  constructor(fileFacts) {
    this.fileFacts = fileFacts;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeCodeLenses = this.emitter.event;
  }

  provideCodeLenses(document) {
    if (!settings().get("codeLens") || document.uri.scheme !== "file") return [];
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!folder) return [];
    const rel = relative(document.uri);
    const known = this.fileFacts.peek(folder, rel);
    if (known === undefined) {
      this.fileFacts.get(folder, rel).then(
        () => this.emitter.fire(),
        () => {},
      );
      return [];
    }
    const title = known ? facts.lens(known.why, known.impact) : null;
    if (!title) return [];
    return [new vscode.CodeLens(new vscode.Range(0, 0, 0, 0), { title, tooltip: "Open the evidence behind this line", command: "tessri.why", arguments: [document.uri] })];
  }

  refresh() {
    this.emitter.fire();
  }
}

/** The file a command is about: the explorer's URI, a hover link's string, or the active editor. */
function target(arg) {
  const uri = arg instanceof vscode.Uri ? arg : typeof arg === "string" ? vscode.Uri.parse(arg) : vscode.window.activeTextEditor ? vscode.window.activeTextEditor.document.uri : null;
  if (!uri || uri.scheme !== "file") {
    vscode.window.showInformationMessage("Tessri: open a file of the repository first.");
    return null;
  }
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) {
    vscode.window.showInformationMessage("Tessri: the file is outside the workspace folders.");
    return null;
  }
  return { folder, uri, rel: relative(uri) };
}

/** The workspace folder a chat tool call is about. */
function folderFor(rootName) {
  const folders = vscode.workspace.workspaceFolders || [];
  if (rootName) {
    const match = folders.find((f) => f.name === rootName || f.uri.fsPath === rootName);
    if (!match) throw new Error(`\`${rootName}\` is not a workspace folder; the folders are ${folders.map((f) => f.name).join(", ") || "none"}`);
    return match;
  }
  if (folders.length === 1) return folders[0];
  const active = vscode.window.activeTextEditor && vscode.workspace.getWorkspaceFolder(vscode.window.activeTextEditor.document.uri);
  if (active) return active;
  if (!folders.length) throw new Error("no workspace folder is open");
  throw new Error(`\`root\` is required: the window has ${folders.length} folders: ${folders.map((f) => f.name).join(", ")}`);
}

function activate(context) {
  const output = vscode.window.createOutputChannel("Tessri", { log: true });
  const servers = new Servers(output);
  const fileFacts = new FileFacts(servers);
  const pages = new Pages();
  const hover = new HoverProvider(fileFacts);
  const lenses = new LensProvider(fileFacts);
  const selector = LANGUAGES.map((language) => ({ language, scheme: "file" }));

  async function page(folder, name, args, title, ext) {
    let result;
    try {
      result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title: `Tessri: ${title}` }, () => servers.call(folder, name, args));
    } catch (err) {
      if (!(err instanceof ServerError && err.code === "ENOENT")) vscode.window.showErrorMessage(`Tessri: ${err.message}`);
      return;
    }
    const text = result.content.map((c) => c.text).join("\n");
    const uri = pages.put(`${folder.name}/${title}.${result.isError ? "txt" : ext}`, result.isError ? `Tessri could not answer: ${text}` : text);
    const document = await vscode.workspace.openTextDocument(uri);
    if (ext === "md" && !result.isError) {
      try {
        await vscode.commands.executeCommand("markdown.showPreviewToSide", uri);
        return;
      } catch (_) {
        // no Markdown preview: the text is still worth reading
      }
    }
    await vscode.window.showTextDocument(document, { preview: true, viewColumn: vscode.ViewColumn.Beside, preserveFocus: true });
  }

  const since = () => {
    const given = settings().get("since");
    return typeof given === "string" && given.trim() ? { since: given.trim() } : {};
  };

  const commands = {
    "tessri.why": async (arg) => {
      const t = target(arg);
      if (t) await page(t.folder, "tessri_why", { path: t.rel }, `why/${t.rel}`, "txt");
    },
    "tessri.impact": async (arg) => {
      const t = target(arg);
      if (t) await page(t.folder, "tessri_impact", { target: t.rel }, `impact/${t.rel}`, "md");
    },
    "tessri.triage": async (arg) => {
      const t = target(arg);
      if (t) await page(t.folder, "tessri_triage", since(), "triage", "md");
    },
    "tessri.check": async (arg) => {
      const t = target(arg);
      if (t) await page(t.folder, "tessri_check", since(), "check", "md");
    },
    "tessri.brief": async (arg) => {
      const t = target(arg);
      if (t) await page(t.folder, "tessri_brief", since(), "brief", "md");
    },
    "tessri.restart": () => {
      servers.restart();
      fileFacts.forget(null);
      lenses.refresh();
    },
    "tessri.showLog": () => output.show(true),
  };

  context.subscriptions.push(
    output,
    servers,
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, pages),
    vscode.languages.registerHoverProvider(selector, hover),
    vscode.languages.registerCodeLensProvider(selector, lenses),
    ...Object.entries(commands).map(([id, run]) => vscode.commands.registerCommand(id, run)),
    vscode.workspace.onDidSaveTextDocument((document) => {
      fileFacts.forget(vscode.workspace.getWorkspaceFolder(document.uri) || null);
      lenses.refresh();
    }),
    vscode.workspace.onDidChangeWorkspaceFolders((event) => {
      for (const folder of event.removed) {
        servers.drop(folder);
        fileFacts.forget(folder);
      }
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("tessri.command")) commands["tessri.restart"]();
      else if (event.affectsConfiguration("tessri")) lenses.refresh();
    }),
  );

  if (vscode.lm && typeof vscode.lm.registerTool === "function") {
    for (const tool of TOOLS) {
      context.subscriptions.push(
        vscode.lm.registerTool(tool.name, {
          prepareInvocation(options) {
            return { invocationMessage: tool.invocation(options.input || {}) };
          },
          async invoke(options) {
            const input = { ...(options.input || {}) };
            const rootName = input.root;
            delete input.root;
            let text;
            try {
              const result = await servers.call(folderFor(rootName), tool.name, input);
              text = result.content.map((c) => c.text).join("\n");
              if (result.isError) text = `Tessri could not answer: ${text}`;
            } catch (err) {
              text = `Tessri could not answer: ${err.message}`;
            }
            return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
          },
        }),
      );
    }
  }

  return { servers, fileFacts, pages, hover, lenses, commands, folderFor, definitionAt }; // for the tests
}

function deactivate() {}

module.exports = { activate, deactivate, definitionAt, folderFor, LANGUAGES, SCHEME };
