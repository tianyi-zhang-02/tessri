// One `tessri mcp` child per workspace folder, spoken to over standard input and output as newline-delimited
// JSON-RPC: the Model Context Protocol's stdio transport, which the server already serves to agents. The editor
// is just another client of it, so every number the editor shows is one the agent would get from the same tool.
//
// The child starts on the first call and stays until disposed; while the checkout is unchanged the server reuses
// its analysis, so a hover or a code lens after the first costs a few milliseconds. A child that exits fails the
// calls in flight and is started again by the next call; a command that cannot be found is remembered, so the
// editor asks once and stays quiet.

"use strict";

const { spawn } = require("child_process");

const INITIALIZE_TIMEOUT = 30_000; // the handshake answers at once; a slow machine still gets a wide margin
const CALL_TIMEOUT = 180_000; // the first call analyses the whole repository; a large one takes seconds, not minutes

class ServerError extends Error {
  constructor(message, code) {
    super(message);
    this.name = "ServerError";
    this.code = code; // "ENOENT" when the command is not there, "EXIT" when the child stopped, else a JSON-RPC code
  }
}

class Client {
  /**
   * @param {string[]} command the executable and its leading arguments, for example ["tessri"] or ["python3", "-m", "tessri"]
   * @param {string} root the checkout the child serves
   * @param {{log?: (line: string) => void}} [options]
   */
  constructor(command, root, options = {}) {
    this.command = command;
    this.root = root;
    this.log = options.log || (() => {});
    this.child = null;
    this.ready = null; // the handshake's promise while a child is up
    this.pending = new Map(); // id -> {resolve, reject, timer}
    this.nextId = 1;
    this.buffer = "";
    this.missing = null; // the spawn error once the command was not found: no retries until the command changes
    this.serverInfo = null;
  }

  /** The command line the child runs, for messages. */
  get commandLine() {
    return [...this.command, "mcp", "--root", this.root].join(" ");
  }

  start() {
    if (this.ready) return this.ready;
    if (this.missing) return Promise.reject(this.missing);
    const [exe, ...lead] = this.command;
    let child;
    try {
      child = spawn(exe, [...lead, "mcp", "--root", this.root], { cwd: this.root, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
    } catch (err) {
      return Promise.reject(this._gone(err));
    }
    this.child = child;
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => this._onData(chunk));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => chunk.split(/\r?\n/).filter(Boolean).forEach((line) => this.log(`[server] ${line}`)));
    child.on("error", (err) => {
      if (this.child === child) this._failAll(this._gone(err));
    });
    child.on("exit", (code, signal) => {
      if (this.child !== child) return; // a child already replaced or disposed: its calls were failed then
      this.child = null;
      this.ready = null;
      this._failAll(new ServerError(`\`${this.commandLine}\` exited${code !== null ? ` with code ${code}` : signal ? ` on ${signal}` : ""}`, "EXIT"));
    });
    this.log(`starting ${this.commandLine}`);
    this.ready = this._request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "tessri-vscode", version: "0.1.0" } }, INITIALIZE_TIMEOUT).then((result) => {
      this.serverInfo = result && result.serverInfo ? result.serverInfo : null;
      this._send({ jsonrpc: "2.0", method: "notifications/initialized" });
      return result;
    });
    this.ready.catch(() => {}); // reported to the caller that awaits it
    return this.ready;
  }

  /**
   * One tool call. Resolves to the server's result object: `content` (one text part), `structuredContent` when
   * the call succeeded and `isError`. Rejects with a ServerError when the server cannot be run or answers with a
   * protocol error (an unknown tool, an argument of the wrong type).
   */
  async call(name, args = {}) {
    await this.start();
    return this._request("tools/call", { name, arguments: args }, CALL_TIMEOUT);
  }

  /** The server's tool list, for checking what it offers. */
  async tools() {
    await this.start();
    const result = await this._request("tools/list", {}, INITIALIZE_TIMEOUT);
    return result.tools;
  }

  dispose() {
    const child = this.child;
    this.child = null;
    this.ready = null;
    this._failAll(new ServerError("the Tessri server was stopped", "EXIT"));
    if (child) {
      try {
        child.stdin.end();
      } catch (_) {
        // already gone
      }
      const timer = setTimeout(() => {
        try {
          child.kill();
        } catch (_) {
          // already gone
        }
      }, 2000);
      child.on("exit", () => clearTimeout(timer));
    }
  }

  _gone(err) {
    const notFound = err && err.code === "ENOENT";
    const message = notFound ? `\`${this.command[0]}\` was not found: install Tessri (\`pip install tessri\`) or set \`tessri.command\`` : `\`${this.commandLine}\` could not be started: ${err && err.message ? err.message : err}`;
    const failure = new ServerError(message, notFound ? "ENOENT" : "SPAWN");
    this.log(message);
    if (notFound) this.missing = failure;
    this.child = null;
    this.ready = null;
    return failure;
  }

  _send(message) {
    if (!this.child || !this.child.stdin.writable) throw new ServerError(`\`${this.commandLine}\` is not running`, "EXIT");
    this.child.stdin.write(JSON.stringify(message) + "\n");
  }

  _request(method, params, timeout) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new ServerError(`\`${method}\` did not answer within ${Math.round(timeout / 1000)} seconds`, "TIMEOUT"));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this._send({ jsonrpc: "2.0", id, method, params });
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  _onData(chunk) {
    this.buffer += chunk;
    let at;
    while ((at = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, at).trim();
      this.buffer = this.buffer.slice(at + 1);
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch (_) {
        this.log(`[server] not JSON: ${line.slice(0, 200)}`);
        continue;
      }
      const waiting = this.pending.get(message.id);
      if (!waiting) continue; // a notification, or an answer nobody waits for any more
      this.pending.delete(message.id);
      clearTimeout(waiting.timer);
      if (message.error) waiting.reject(new ServerError(message.error.message || "server error", message.error.code));
      else waiting.resolve(message.result);
    }
  }

  _failAll(error) {
    for (const [id, waiting] of this.pending) {
      clearTimeout(waiting.timer);
      waiting.reject(error);
      this.pending.delete(id);
    }
  }
}

module.exports = { Client, ServerError };
