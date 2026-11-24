"""The Claude Code and Codex plugins at the repository root: the manifest each host reads, the marketplace file
that lets each install Tessri from this repository, the hooks they share, and the launcher all of them run."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tessri import __version__, templates

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "tessri"
HOOK_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/bin/tessri" hook'  # Claude Code substitutes the variable; Codex sets it in the hook's environment
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
# agent-plugins.org, 1.0.0: both schemas say `additionalProperties: false`
PLUGIN_KEYS = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords", "extensions"}
STDIO_KEYS = {"type", "command", "args", "env", "cwd"}


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class ManifestTest(unittest.TestCase):
    def test_both_manifests_describe_one_plugin_at_tessris_version(self):
        claude, portable = load(".claude-plugin/plugin.json"), load("plugin.json")
        for manifest in (claude, portable):
            self.assertEqual(manifest["name"], "tessri")
            self.assertEqual(manifest["version"], __version__)
            self.assertEqual(manifest["license"], "MIT")
            self.assertEqual(manifest["repository"], "https://github.com/tianyi-zhang-02/tessri")
            self.assertLessEqual(set(manifest["author"]), {"name", "url"})  # no email, anywhere Tessri writes
            self.assertNotIn("@", json.dumps(manifest))
        self.assertEqual(claude["description"], portable["description"])
        self.assertEqual(claude["keywords"], portable["keywords"])

    def test_the_portable_manifest_keeps_to_the_agent_plugins_schema(self):
        portable = load("plugin.json")
        self.assertEqual(portable["$schema"], PLUGIN_SCHEMA)
        self.assertLessEqual(set(portable), PLUGIN_KEYS)
        openai = portable["extensions"]["com.openai"]
        self.assertEqual(openai["hooks"], "./hooks/hooks.json")
        self.assertEqual(openai["interface"]["displayName"], "Tessri")

    def test_claude_code_starts_the_launcher_on_the_project(self):
        servers = load(".claude-plugin/plugin.json")["mcpServers"]
        self.assertEqual(servers, {"tessri": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/bin/tessri", "mcp", "--root", "${CLAUDE_PROJECT_DIR}"]}})

    def test_codex_starts_the_launcher_as_a_contained_stdio_command(self):
        doc = load("mcp.json")
        self.assertEqual(doc["$schema"], MCP_SCHEMA)
        (server,) = doc["mcpServers"].values()
        self.assertLessEqual(set(server), STDIO_KEYS)
        self.assertEqual((server["type"], server["command"], server["args"]), ("stdio", "./bin/tessri", ["mcp"]))
        # a `.mcp.json` at the root would also be this repository's project servers in Claude Code, with the plugin's variables unexpanded
        self.assertFalse((ROOT / ".mcp.json").exists())


class MarketplaceTest(unittest.TestCase):
    def test_each_host_finds_the_plugin_at_the_repository_root(self):
        claude, codex = load(".claude-plugin/marketplace.json"), load(".agents/plugins/marketplace.json")
        self.assertEqual((claude["name"], codex["name"]), ("tessri", "tessri"))
        (entry,) = claude["plugins"]
        self.assertEqual((entry["name"], entry["source"]), ("tessri", "./"))
        (entry,) = codex["plugins"]
        self.assertEqual((entry["name"], entry["source"]), ("tessri", {"source": "local", "path": "./"}))
        self.assertEqual(set(entry["policy"]), {"installation", "authentication"})  # what Codex wants on every entry
        self.assertIn("category", entry)
        self.assertNotIn("@", json.dumps(claude) + json.dumps(codex))


class HooksTest(unittest.TestCase):
    def test_the_plugin_hooks_are_the_integration_hooks_run_through_the_launcher(self):
        groups = load("hooks/hooks.json")["hooks"]
        self.assertEqual(set(groups), set(templates.HOOKS))
        for event, template in templates.HOOKS.items():
            (group,) = groups[event]
            expected = {**template, "hooks": [{**h, "command": h["command"].replace("tessri hook", HOOK_COMMAND)} for h in template["hooks"]]}
            self.assertEqual(group, expected, event)


class LauncherTest(unittest.TestCase):
    """`bin/tessri` is `tessri` from this checkout, wherever it is run from and whatever else is installed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        self.env["TESSRI_CACHE_DIR"] = str(self.tmp / "cache")

    def run_python(self, *args, stdin=None):
        return subprocess.run([sys.executable, *args], cwd=self.tmp, input=stdin, capture_output=True, text=True, timeout=120, env=self.env)

    def test_it_runs_this_checkouts_tessri_from_any_directory(self):
        res = self.run_python(str(LAUNCHER), "--version")
        self.assertEqual((res.returncode, res.stdout.strip(), res.stderr), (0, f"tessri {__version__}", ""))
        probe = (
            "import runpy, sys\n"
            "sys.argv = ['tessri', '--version']\n"
            "try:\n"
            f"    runpy.run_path({str(LAUNCHER)!r}, run_name='__main__')\n"
            "except SystemExit:\n"
            "    pass\n"
            "import tessri\n"
            "print(tessri.__file__)\n"
        )
        res = self.run_python("-c", probe)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(Path(res.stdout.strip().splitlines()[-1]).resolve(), (ROOT / "tessri" / "__init__.py").resolve())

    def test_the_hook_and_the_server_answer_through_it(self):
        event = {"hook_event_name": "Stop", "session_id": "plugin-test", "cwd": str(self.tmp)}  # a directory without git: nothing to say
        res = self.run_python(str(LAUNCHER), "hook", stdin=json.dumps(event))
        self.assertEqual((res.returncode, res.stdout, res.stderr), (0, "", ""))
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "tessri_repos", "arguments": {}}},
        ]
        res = self.run_python(str(LAUNCHER), "mcp", "--root", str(ROOT), stdin="".join(json.dumps(m) + "\n" for m in messages))
        self.assertEqual(res.returncode, 0, res.stderr)
        replies = [json.loads(line) for line in res.stdout.splitlines() if line.strip()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertEqual(replies[1]["result"]["structuredContent"]["repos"][0]["root"], str(ROOT))

    def test_it_is_executable_in_git_for_the_host_that_runs_it_directly(self):
        try:
            res = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", "bin/tessri"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is not available")
        if res.returncode != 0 or not res.stdout.strip():
            self.skipTest("not a checkout")
        self.assertTrue(res.stdout.startswith("100755 "), res.stdout)
        self.assertTrue(LAUNCHER.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"))


if __name__ == "__main__":
    unittest.main()
