"""`tessri mcp`: each tool returns what the command line prints, as text and as the JSON object; a mistake in the
arguments is a tool result in the command's sentence; both protocol revisions are spoken; standard output carries
nothing but responses."""

import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from helpers import TempRepo, git, write_tree

ROOT = Path(__file__).resolve().parents[1]

from tessri import mcp
from tessri.cli import main
from tessri.mcp import CURRENT, INSTRUCTIONS, LEGACY, SUPPORTED, TOOLS, Server

ALICE = ("Alice", "alice@example.com")
TREE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "import pkg.util\n",
    "pkg/util.py": "x = 1\n",
    "pkg/dead.py": "y = 2\n",
    "scripts/run.py": "import pkg.core\n",
    "tests/test_core.py": "import pkg.core\n",
    ".tessri.toml": 'entry = ["scripts/run.py"]\n',
}


def request(rid, method, params=None, version=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None or version:
        msg["params"] = dict(params or {})
    if version:
        msg["params"]["_meta"] = {mcp.VERSION_KEY: version, "io.modelcontextprotocol/clientCapabilities": {}}
    return msg


def call(server, name, arguments=None, rid=1, version=None):
    return server.handle(request(rid, "tools/call", {"name": name, "arguments": arguments or {}}, version))


STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def untimed(text):
    return STAMP.sub("<stamp>", text)


def unstamped(doc):
    """The object without the moments it was made at, which differ between two runs."""
    if isinstance(doc, dict):
        return {k: unstamped(v) for k, v in doc.items() if k != "generated_at"}  # at any depth: a brief embeds triage and check
    if isinstance(doc, list):
        return [unstamped(v) for v in doc]
    return doc


class Repo(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, TREE)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "start", when=time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(time.time() - 40 * 86400)), author=ALICE)
        write_tree(self.root, {"pkg/util.py": "x = 1\nz = 2\n"})  # uncommitted work, so triage and check have a change to look at
        self.server = Server([self.root])

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main([*argv, "--repo", str(self.root)] if argv[0] in ("why", "impact", "triage", "check", "brief") else [argv[0], str(self.root), *argv[1:]])
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()


class LegacyProtocolTest(Repo):
    def test_initialize_lists_and_calls(self):
        init = self.server.handle(request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}))
        result = init["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"]["name"], "tessri")
        self.assertEqual(result["instructions"], INSTRUCTIONS)
        self.assertNotIn("resultType", result)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.server.handle(request(2, "ping"))["result"], {})
        listed = self.server.handle(request(3, "tools/list"))["result"]["tools"]
        self.assertEqual([t["name"] for t in listed], ["tessri_repos", "tessri_scan", "tessri_why", "tessri_impact", "tessri_graph", "tessri_triage", "tessri_check", "tessri_brief"])
        answer = call(self.server, "tessri_why", {"path": "pkg/core.py"}, rid=4)["result"]
        self.assertFalse(answer["isError"])
        self.assertNotIn("resultType", answer)
        self.assertEqual(answer["content"], [{"type": "text", "text": self.cli("why", "pkg/core.py")}])
        self.assertEqual(unstamped(answer["structuredContent"]), unstamped(json.loads(self.cli("why", "pkg/core.py", "--format", "json"))))

    def test_an_unknown_handshake_version_gets_the_newest_legacy_one(self):
        result = self.server.handle(request(1, "initialize", {"protocolVersion": CURRENT}))["result"]
        self.assertEqual(result["protocolVersion"], LEGACY[0])


class CurrentProtocolTest(Repo):
    def test_discover_and_call_without_a_handshake(self):
        found = self.server.handle(request("d-1", "server/discover", version=CURRENT))["result"]
        self.assertEqual(found["resultType"], "complete")
        self.assertEqual(found["supportedVersions"], list(SUPPORTED))
        self.assertEqual(found["capabilities"], {"tools": {}})
        self.assertEqual(found["_meta"][mcp.SERVER_KEY]["name"], "tessri")
        self.assertEqual((found["instructions"], found["cacheScope"]), (INSTRUCTIONS, "public"))
        self.assertIsInstance(found["ttlMs"], int)
        listed = self.server.handle(request(2, "tools/list", version=CURRENT))["result"]
        self.assertEqual(listed["resultType"], "complete")
        answer = call(self.server, "tessri_repos", rid=3, version=CURRENT)["result"]
        self.assertEqual(answer["resultType"], "complete")
        self.assertEqual(answer["structuredContent"]["repos"][0]["name"], self.root.name)

    def test_a_version_this_server_does_not_speak_is_refused(self):
        error = self.server.handle(request(1, "tools/list", version="1900-01-01"))["error"]
        self.assertEqual(error["code"], -32022)
        self.assertEqual(error["data"], {"supported": list(SUPPORTED), "requested": "1900-01-01"})
        self.assertIn(CURRENT, error["data"]["supported"])
        self.assertIn("2025-11-25", error["data"]["supported"])


class ToolsTest(Repo):
    def test_every_tool_returns_what_the_command_line_prints(self):
        cases = {
            "tessri_scan": ({}, ("scan",), ("scan", "--format", "json")),
            "tessri_why": ({"path": "pkg/core.py"}, ("why", "pkg/core.py"), ("why", "pkg/core.py", "--format", "json")),
            "tessri_impact": ({"target": "pkg/util.py", "edges": "imports"}, ("impact", "pkg/util.py", "--edges", "imports"), ("impact", "pkg/util.py", "--edges", "imports", "--format", "json")),
            "tessri_graph": ({}, ("graph",), ("graph", "--format", "json")),
            "tessri_triage": ({}, ("triage",), ("triage", "--format", "json")),
            "tessri_check": ({}, ("check",), ("check", "--format", "json")),
            "tessri_brief": ({"ran": ["unittest: 3 tests OK (exit 0)"]}, ("brief", "--ran", "unittest: 3 tests OK (exit 0)"), ("brief", "--ran", "unittest: 3 tests OK (exit 0)", "--format", "json")),
        }
        for name, (arguments, text_argv, json_argv) in cases.items():
            with self.subTest(name):
                answer = call(self.server, name, arguments)["result"]
                self.assertFalse(answer["isError"])
                self.assertEqual(untimed(answer["content"][0]["text"]), untimed(self.cli(*text_argv)))
                self.assertEqual(unstamped(answer["structuredContent"]), unstamped(json.loads(self.cli(*json_argv))))

    def test_a_test_report_is_read_under_the_root_or_by_its_full_path(self):
        write_tree(self.root, {"pkg/test_util.py": "import pkg.util\n"})  # uncommitted too, so it is in the tree the server reads
        (self.root / "junit.xml").write_text('<testsuites><testsuite name="s"><testcase classname="pkg.test_util" name="test_x"/></testsuite></testsuites>')
        answer = call(self.server, "tessri_impact", {"target": "pkg/util.py", "report": ["junit.xml"]})["result"]
        self.assertFalse(answer["isError"], answer)
        held = answer["structuredContent"]["tests"]["report"]
        self.assertEqual((held["sources"], held["ran"]), ([str(self.root / "junit.xml")], {"pkg/test_util.py": "passed"}))
        self.assertEqual(unstamped(answer["structuredContent"]), unstamped(json.loads(self.cli("impact", "pkg/util.py", "--report", str(self.root / "junit.xml"), "--format", "json"))))
        answer = call(self.server, "tessri_brief", {"report": [str(self.root / "junit.xml")]})["result"]
        self.assertFalse(answer["isError"], answer)
        self.assertEqual(answer["structuredContent"]["validation"]["report"]["cases"], 1)
        answer = call(self.server, "tessri_brief", {"report": ["nowhere.xml"]})["result"]
        self.assertTrue(answer["isError"])
        self.assertIn("nowhere.xml", answer["content"][0]["text"])

    def test_every_object_says_what_it_is(self):
        for name, arguments in (("tessri_scan", {}), ("tessri_why", {"path": "pkg/core.py"}), ("tessri_impact", {"target": "pkg"}), ("tessri_graph", {}), ("tessri_triage", {}), ("tessri_check", {}), ("tessri_brief", {}), ("tessri_repos", {})):
            with self.subTest(name):
                doc = call(self.server, name, arguments)["result"]["structuredContent"]
                self.assertEqual(doc["schema_version"], 1)
                self.assertIsInstance(doc["kind"], str)
        self.assertEqual(call(self.server, "tessri_scan")["result"]["structuredContent"]["kind"], "scan")
        self.assertEqual(call(self.server, "tessri_impact", {"target": "pkg"})["result"]["structuredContent"]["kind"], "directory")

    def test_a_file_level_graph_has_the_json_as_its_text(self):
        answer = call(self.server, "tessri_graph", {"level": "file"})["result"]
        self.assertEqual(answer["structuredContent"]["kind"], "file-graph")
        self.assertEqual(json.loads(answer["content"][0]["text"]), answer["structuredContent"])

    def test_repos(self):
        answer = call(self.server, "tessri_repos")["result"]
        repo = answer["structuredContent"]["repos"][0]
        self.assertEqual((repo["name"], repo["root"]), (self.root.name, str(self.root)))
        self.assertEqual((repo["git"]["available"], repo["git"]["commits"], repo["git"]["shallow"], repo["git"]["reason"]), (True, 1, False, None))
        self.assertRegex(repo["git"]["head"], r"^[0-9a-f]{40}$")
        self.assertIn(f"- {self.root.name}: {self.root} (1 commits, head {repo['git']['head'][:7]})", answer["content"][0]["text"])

    def test_mistakes_are_tool_results_in_the_commands_words(self):
        cases = {
            ("tessri_why", "path", "nope.py"): "`nope.py` is not a file in the analysed set (excluded, binary or unknown type?)",
            ("tessri_impact", "target", "nothing/"): "`nothing` is not a file in the analysed set (excluded, binary or unknown type?)",
            ("tessri_triage", "since", "nope"): "`nope` is not a commit, branch or tag in this repository",
            ("tessri_check", "since", "nope"): "`nope` is not a commit, branch or tag in this repository",
            ("tessri_brief", "since", "nope"): "`nope` is not a commit, branch or tag in this repository",
            ("tessri_scan", "root", "/nowhere/at/all"): "`/nowhere/at/all` is not a root this server was started with; `tessri_repos` lists them",
        }
        for (name, key, value), sentence in cases.items():
            with self.subTest(name):
                answer = call(self.server, name, {key: value})["result"]
                self.assertEqual(answer, {"content": [{"type": "text", "text": sentence}], "isError": True})
        write_tree(self.root, {"pkg/sub/__init__.py": ""})
        answer = call(self.server, "tessri_why", {"path": "__init__.py"})["result"]
        self.assertEqual(answer["content"][0]["text"], "`__init__.py` is ambiguous: pkg/__init__.py, pkg/sub/__init__.py")
        self.assertTrue(answer["isError"])

    def test_bad_requests_are_protocol_errors(self):
        self.assertEqual(call(self.server, "tessri_nope")["error"]["code"], -32602)
        self.assertEqual(self.server.handle(request(1, "resources/list"))["error"]["code"], -32601)
        for name, arguments, problem in (
            ("tessri_why", {}, "`path` is required"),
            ("tessri_why", {"path": 3}, "`path` must be string"),
            ("tessri_impact", {"target": "pkg", "edges": "weird"}, "`edges` must be one of all, imports"),
            ("tessri_impact", {"target": "pkg", "hops": 0}, "`hops` must be at least 1"),
            ("tessri_scan", {"limit": 3}, "unknown argument `limit`; the tool takes root, full"),
            ("tessri_brief", {"ran": "unittest: OK"}, "`ran` must be array"),
            ("tessri_brief", {"ran": ["unittest: OK", 0]}, "`ran` must be an array of strings"),
            ("tessri_repos", {"root": "x"}, "unknown argument `root`; the tool takes none"),
        ):
            with self.subTest(name, problem=problem):
                error = call(self.server, name, arguments)["error"]
                self.assertEqual((error["code"], error["message"]), (-32602, f"{name}: {problem}"))
        self.assertEqual(self.server.handle({"id": 9, "method": "ping"})["error"]["code"], -32600)  # no jsonrpc field
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "result": {}, "id": 1}))  # a response to nothing
        self.assertIsNone(self.server.handle([1, 2]))

    def test_schemas_and_annotations(self):
        for tool in TOOLS:
            with self.subTest(tool.name):
                listing = tool.listing()
                schema = listing["inputSchema"]
                self.assertEqual((schema["type"], schema["additionalProperties"]), ("object", False))
                self.assertTrue(set(schema["required"]) <= set(schema["properties"]))
                defaults = {k: v["default"] for k, v in schema["properties"].items() if "default" in v}
                self.assertIsNone(mcp.validate(tool, {**defaults, **{k: "x" for k in schema["required"]}}))
                self.assertEqual(listing["annotations"], {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
                self.assertTrue(listing["title"] and listing["description"].endswith("."))


class ReuseTest(Repo):
    """An analysis is reused while the checkout's fingerprint holds; any change to what the analysis reads, or an
    hour, makes the next call read afresh."""

    def setUp(self):
        super().setUp()
        self.calls = 0
        real = mcp.analyze

        def counted(*args, **kwargs):
            self.calls += 1
            return real(*args, **kwargs)

        patcher = unittest.mock.patch.object(mcp, "analyze", counted)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, name="tessri_why", arguments=None):
        if arguments is None:
            arguments = {"path": "pkg/core.py"} if name == "tessri_why" else {}
        return call(self.server, name, arguments)["result"]

    def test_an_unchanged_checkout_is_analysed_once(self):
        first = self.ask()
        second = self.ask("tessri_impact", {"target": "pkg/util.py"})
        third = self.ask("tessri_scan")
        self.assertEqual(self.calls, 1)
        self.assertEqual(first["structuredContent"]["meta"]["generated_at"], third["structuredContent"]["meta"]["generated_at"])
        self.assertFalse(second["isError"])

    def test_every_kind_of_change_is_seen(self):
        self.ask()
        write_tree(self.root, {"pkg/util.py": "x = 1\nz = 2\nimport pkg.dead\n"})  # a tracked, already dirty file edited again
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.ask("tessri_why", {"path": "pkg/dead.py"})["structuredContent"]["graph"]["dependents"], ["pkg/util.py"])
        self.assertEqual(self.calls, 2)
        write_tree(self.root, {"pkg/fresh.py": "w = 1\n"})  # an untracked file appears
        self.assertIn("pkg/fresh.py", self.ask("tessri_scan")["content"][0]["text"])
        self.assertEqual(self.calls, 3)
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "more", author=ALICE)  # HEAD moves, the tree is clean
        self.ask()
        self.assertEqual(self.calls, 4)
        write_tree(self.root, {".tessri.toml": 'entry = ["scripts/run.py"]\nkeep = ["pkg/dead.py"]\n'})  # the configuration changes
        self.assertIn("keep", self.ask("tessri_why", {"path": "pkg/dead.py"})["structuredContent"]["verdict"]["entry_points"])
        self.assertEqual(self.calls, 5)
        self.ask()
        self.assertEqual(self.calls, 5)

    def test_an_analysis_older_than_an_hour_is_not_reused(self):
        self.ask()
        self.server.clock = lambda: time.time() + mcp.REUSE_SECONDS + 1
        self.ask()
        self.assertEqual(self.calls, 2)

    def test_a_change_query_always_reads_afresh(self):
        self.ask("tessri_triage")
        self.ask("tessri_check")
        self.ask("tessri_brief")
        self.assertEqual(self.calls, 0)  # they analyse through their own path, which is not kept

    def test_without_git_nothing_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:  # its own directory: inside the fixture it would be part of that repository
            plain = Path(tmp).resolve()
            write_tree(plain, {"a.py": "x = 1\n"})
            server = Server([plain])
            call(server, "tessri_scan")
            call(server, "tessri_scan")
            self.assertEqual((self.calls, server.kept), (2, {}))


class SeveralCheckoutsTest(TempRepo):
    def setUp(self):
        super().setUp()
        self.a, self.b, self.c = self.root / "app", self.root / "lib" / "app", self.root / "lib"
        write_tree(self.a, {"a.py": "x = 1\n"})
        write_tree(self.b, {"b.py": "y = 2\n"})
        self.server = Server([self.a, self.b, self.c])

    def test_roots_are_named_and_a_tool_names_one(self):
        repos = call(self.server, "tessri_repos")["result"]["structuredContent"]["repos"]
        self.assertEqual([r["name"] for r in repos], ["app", "app-2", "lib"])
        self.assertEqual(repos[0]["git"], {"available": False, "reason": "not-a-repository", "head": None, "shallow": None, "commits": None})
        by_name = call(self.server, "tessri_scan", {"root": "app-2"})["result"]["structuredContent"]
        by_path = call(self.server, "tessri_scan", {"root": str(self.b)})["result"]["structuredContent"]
        self.assertEqual(by_name["meta"]["repo"]["root"], str(self.b))
        self.assertEqual(by_path["meta"]["repo"]["root"], str(self.b))

    def test_root_is_required_with_several(self):
        answer = call(self.server, "tessri_scan")["result"]
        self.assertEqual(answer, {"content": [{"type": "text", "text": "`root` is required: this server serves 3 checkouts; `tessri_repos` lists them"}], "isError": True})

    def test_a_root_that_went_away(self):
        server = Server([self.a, self.root / "gone"])
        answer = call(server, "tessri_scan", {"root": "gone"})["result"]
        self.assertEqual(answer["content"][0]["text"], f"{self.root / 'gone'}: not a directory")


class ProcessTest(Repo):
    def test_stdout_carries_only_responses_and_eof_ends_the_server(self):
        lines = [
            json.dumps(request(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "not json at all",
            json.dumps(request(2, "tools/call", {"name": "tessri_scan", "arguments": {}})),
            json.dumps(request("x", "server/discover", version=CURRENT)),
        ]
        env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, "-m", "tessri", "mcp", "--root", str(self.root)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120, cwd=self.root, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r.get("id") for r in responses], [1, None, 2, "x"])
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["result"]["structuredContent"]["kind"], "scan")
        self.assertEqual(responses[3]["result"]["supportedVersions"][0], CURRENT)

    def test_a_missing_root_is_refused_before_serving(self):
        with self.assertRaises(SystemExit) as caught:
            main(["mcp", "--root", str(self.root / "nowhere")])
        self.assertEqual(str(caught.exception), f"tessri: {self.root / 'nowhere'}: not a directory")


if __name__ == "__main__":
    unittest.main()
