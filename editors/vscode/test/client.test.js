"use strict";

// Against the real server: `python3 -m tessri mcp --root <this repository>` (TESSRI_TEST_COMMAND overrides the
// command). Python 3.11+ and git are the test's only needs; the editor is not involved.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { Client, ServerError } = require("../lib/client");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const COMMAND = (process.env.TESSRI_TEST_COMMAND || "python3 -m tessri").split(/\s+/);
process.env.TESSRI_CACHE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "tessri-vscode-test-"));

test("the client speaks to the server: tools, a call, a mistake, a protocol error, concurrency and a restart", async (t) => {
  const log = [];
  const client = new Client(COMMAND, ROOT, { log: (line) => log.push(line) });
  t.after(() => client.dispose());

  const tools = await client.tools();
  assert.deepEqual(
    tools.map((x) => x.name),
    ["tessri_repos", "tessri_scan", "tessri_why", "tessri_impact", "tessri_graph", "tessri_triage", "tessri_check", "tessri_brief"],
  );
  assert.equal(client.serverInfo.name, "tessri");

  const why = await client.call("tessri_why", { path: "tessri/cli.py" });
  assert.equal(why.isError, false);
  assert.equal(why.structuredContent.path, "tessri/cli.py");
  assert.match(why.content[0].text, /^tessri\/cli\.py/);

  const missing = await client.call("tessri_why", { path: "nope/none.py" });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not a file in the analysed set/);

  await assert.rejects(client.call("tessri_nothing", {}), (err) => err instanceof ServerError && err.code === -32602 && /unknown tool/.test(err.message));
  await assert.rejects(client.call("tessri_impact", { target: 3 }), (err) => err instanceof ServerError && /must be string/.test(err.message));

  const [a, b] = await Promise.all([client.call("tessri_impact", { target: "tessri/triage.py" }), client.call("tessri_impact", { target: "tessri/mentions.py" })]);
  assert.equal(a.structuredContent.target, "tessri/triage.py");
  assert.equal(b.structuredContent.target, "tessri/mentions.py");

  const first = client.child;
  client.dispose();
  const again = await client.call("tessri_why", { path: "tessri/cli.py" });
  assert.equal(again.isError, false);
  assert.notEqual(client.child, first);
  assert.ok(log.some((line) => line.startsWith("starting ")));
});

test("a command that is not there is reported once and remembered", async () => {
  const client = new Client(["tessri-is-not-installed-here-7f3a"], ROOT);
  await assert.rejects(client.call("tessri_why", { path: "x" }), (err) => err instanceof ServerError && err.code === "ENOENT" && /was not found/.test(err.message));
  await assert.rejects(client.call("tessri_why", { path: "x" }), (err) => err.code === "ENOENT");
  assert.equal(client.child, null);
  client.dispose();
});

test("a server that dies fails the calls in flight with the exit, and the next call starts it again", async (t) => {
  const client = new Client(COMMAND, ROOT);
  t.after(() => client.dispose());
  await client.tools();
  const pending = client.call("tessri_scan", {});
  client.child.kill("SIGKILL");
  await assert.rejects(pending, (err) => err instanceof ServerError && err.code === "EXIT");
  const after = await client.call("tessri_why", { path: "tessri/cli.py" });
  assert.equal(after.isError, false);
});
