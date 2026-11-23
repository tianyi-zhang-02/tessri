"use strict";

// Enough of the `vscode` module for the extension to activate and answer outside the editor: ranges that know
// containment, URIs, event emitters, registries that remember what was registered, and a configuration the
// test can change. Install it with `install()` before requiring the extension.

const path = require("path");
const Module = require("module");

class Position {
  constructor(line, character) {
    this.line = line;
    this.character = character;
  }
}

class Range {
  constructor(a, b, c, d) {
    if (a instanceof Position) {
      this.start = a;
      this.end = b;
    } else {
      this.start = new Position(a, b);
      this.end = new Position(c, d);
    }
  }
  contains(p) {
    const before = p.line < this.start.line || (p.line === this.start.line && p.character < this.start.character);
    const after = p.line > this.end.line || (p.line === this.end.line && p.character > this.end.character);
    return !before && !after;
  }
}

class Uri {
  constructor(scheme, fsPath) {
    this.scheme = scheme;
    this.fsPath = fsPath;
    this.path = fsPath.split(path.sep).join("/");
  }
  static file(p) {
    return new Uri("file", p);
  }
  static parse(s) {
    const at = s.indexOf(":");
    const scheme = s.slice(0, at);
    let rest = s.slice(at + 1);
    if (rest.startsWith("//")) rest = rest.slice(2);
    return new Uri(scheme, decodeURIComponent(rest));
  }
  static from({ scheme, path: p }) {
    return new Uri(scheme, p);
  }
  toString() {
    return `${this.scheme}://${this.path}`;
  }
}

class EventEmitter {
  constructor() {
    this.listeners = [];
  }
  get event() {
    return (listener) => {
      this.listeners.push(listener);
      return { dispose: () => {} };
    };
  }
  fire(value) {
    for (const l of this.listeners) l(value);
  }
  dispose() {}
}

class MarkdownString {
  constructor(value) {
    this.value = value;
  }
}
class Hover {
  constructor(contents, range) {
    this.contents = contents;
    this.range = range;
  }
}
class CodeLens {
  constructor(range, command) {
    this.range = range;
    this.command = command;
  }
}
class LanguageModelToolResult {
  constructor(parts) {
    this.parts = parts;
  }
}
class LanguageModelTextPart {
  constructor(value) {
    this.value = value;
  }
}

const SymbolKind = { File: 0, Module: 1, Namespace: 2, Package: 3, Class: 4, Method: 5, Property: 6, Field: 7, Constructor: 8, Enum: 9, Interface: 10, Function: 11, Variable: 12, Constant: 13, String: 14, Number: 15, Boolean: 16, Array: 17, Object: 18, Key: 19, Null: 20, EnumMember: 21, Struct: 22, Event: 23, Operator: 24, TypeParameter: 25 };

function make(root) {
  const disposable = { dispose: () => {} };
  const folder = { name: path.basename(root), uri: Uri.file(root), index: 0 };
  const fake = {
    Position,
    Range,
    Uri,
    EventEmitter,
    MarkdownString,
    Hover,
    CodeLens,
    LanguageModelToolResult,
    LanguageModelTextPart,
    SymbolKind,
    ViewColumn: { Beside: -2 },
    ProgressLocation: { Window: 10 },
    config: { command: ["python3", "-m", "tessri"], codeLens: true, hover: true, since: "" },
    symbols: [], // what the symbol provider answers
    registered: { commands: {}, tools: {}, hovers: [], lenses: [], content: {}, saves: [], folderChanges: [], configChanges: [] },
    calls: [], // executeCommand calls the extension made that nobody registered
    messages: { warning: [], info: [], error: [] },
    shown: [],
    folder,
    workspace: {
      workspaceFolders: [folder],
      getWorkspaceFolder: (uri) => (uri && uri.scheme === "file" && uri.fsPath.startsWith(root) ? folder : undefined),
      asRelativePath: (uri) => path.relative(root, uri.fsPath).split(path.sep).join("/"),
      getConfiguration: () => ({ get: (key) => fake.config[key] }),
      registerTextDocumentContentProvider: (scheme, provider) => {
        fake.registered.content[scheme] = provider;
        return disposable;
      },
      onDidSaveTextDocument: (l) => {
        fake.registered.saves.push(l);
        return disposable;
      },
      onDidChangeWorkspaceFolders: (l) => {
        fake.registered.folderChanges.push(l);
        return disposable;
      },
      onDidChangeConfiguration: (l) => {
        fake.registered.configChanges.push(l);
        return disposable;
      },
      openTextDocument: async (uri) => ({ uri, getText: () => fake.registered.content[uri.scheme].provideTextDocumentContent(uri) }),
    },
    languages: {
      registerHoverProvider: (selector, provider) => {
        fake.registered.hovers.push({ selector, provider });
        return disposable;
      },
      registerCodeLensProvider: (selector, provider) => {
        fake.registered.lenses.push({ selector, provider });
        return disposable;
      },
    },
    commands: {
      registerCommand: (id, run) => {
        fake.registered.commands[id] = run;
        return disposable;
      },
      executeCommand: async (id, ...args) => {
        if (id === "vscode.executeDocumentSymbolProvider") return fake.symbols;
        if (fake.registered.commands[id]) return fake.registered.commands[id](...args);
        fake.calls.push({ id, args });
        return undefined;
      },
    },
    window: {
      activeTextEditor: undefined,
      createOutputChannel: () => ({ lines: [], appendLine(line) { this.lines.push(line); }, show() {}, dispose() {} }),
      showWarningMessage: async (message, ...items) => {
        fake.messages.warning.push({ message, items });
        return undefined;
      },
      showInformationMessage: async (message) => {
        fake.messages.info.push(message);
        return undefined;
      },
      showErrorMessage: async (message) => {
        fake.messages.error.push(message);
        return undefined;
      },
      withProgress: (_options, task) => task(),
      showTextDocument: async (document, options) => {
        fake.shown.push({ document, options });
      },
    },
    lm: {
      registerTool: (name, tool) => {
        fake.registered.tools[name] = tool;
        return disposable;
      },
    },
    env: { openExternal: async () => true },
  };
  return fake;
}

/** Make `require("vscode")` return the fake, from now on in this process. */
function install(fake) {
  const original = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    return request === "vscode" ? "vscode" : original.call(this, request, ...rest);
  };
  require.cache.vscode = { id: "vscode", filename: "vscode", loaded: true, exports: fake };
  return fake;
}

module.exports = { make, install, Position, Range, Uri, SymbolKind };
