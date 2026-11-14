"""`tessri hook`: what a host's lifecycle hook gets back after an edit and when the agent stops."""

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempRepo, git, write_tree
from tessri import cli, hook

PROJECT = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def f():\n    return 1\n",
    "pkg/app.py": "from pkg import core\n\nprint(core.f())\n",
    "pkg/cli.py": "from pkg.core import f\n\nprint(f())\n",
    "pkg/alone.py": "X = 1\n",
    "tests/test_core.py": "from pkg.core import f\n\n\ndef test_f():\n    assert f() == 1\n",
}
ALICE = ("Alice", "alice@example.com")


class HookRepo(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, PROJECT)
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "start", author=ALICE)  # today, so that Alice is an active owner
        state = Path(self._tmp.name) / "state"
        patcher = mock.patch.object(hook, "STATE_DIR", state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def edit(self, rel: str, session: str = "s1", tool: str = "Edit", **extra) -> dict:
        return {"hook_event_name": "PostToolUse", "session_id": session, "cwd": str(self.root), "tool_name": tool, "tool_input": {"file_path": str(self.root / rel), **extra}}

    def stop(self, session: str = "s1", active: bool = False) -> dict:
        return {"hook_event_name": "Stop", "session_id": session, "cwd": str(self.root), "stop_hook_active": active}


class AfterEditTest(HookRepo):
    def test_an_edit_tells_the_agent_what_the_file_reaches(self):
        answer = hook.respond(self.edit("pkg/core.py"))
        self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        text = answer["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(text.startswith("Tessri, on `pkg/core.py`: 2 code files depend on it, 2 directly (`pkg/app.py`, `pkg/cli.py`); 1 test file reaches it (`tests/test_core.py`), candidates to run, not runs."), text)
        self.assertIn("maintained by Alice 100%.", text)
        self.assertTrue(text.endswith("`tessri impact pkg/core.py`."), text)
        self.assertNotIn("alice@", text)
        self.assertEqual(set(answer), {"hookSpecificOutput"})  # no decision, nothing blocks

    def test_each_file_is_spoken_about_once_per_session(self):
        self.assertIsNotNone(hook.respond(self.edit("pkg/core.py")))
        self.assertIsNone(hook.respond(self.edit("pkg/core.py")))
        self.assertIsNone(hook.respond(self.edit("pkg/core.py", tool="Write", content="x")))
        self.assertIsNotNone(hook.respond(self.edit("pkg/core.py", session="another session")))
        self.assertEqual(len(list(hook.STATE_DIR.glob("*.json"))), 2)

    def test_without_a_session_id_nothing_is_remembered(self):
        event = self.edit("pkg/core.py")
        del event["session_id"]
        self.assertIsNotNone(hook.respond(event))
        self.assertIsNotNone(hook.respond(event))
        self.assertFalse(hook.STATE_DIR.exists())

    def test_a_file_nothing_depends_on_is_passed_over_in_silence(self):
        self.assertIsNone(hook.respond(self.edit("pkg/alone.py")))
        write_tree(self.root, {"pkg/new.py": "Y = 2\n"})
        self.assertIsNone(hook.respond(self.edit("pkg/new.py", tool="Write", content="Y = 2\n")))

    def test_a_codex_patch_names_its_files_in_the_command(self):
        patch = "*** Begin Patch\n*** Update File: pkg/core.py\n@@\n-    return 1\n+    return 2\n*** Add File: pkg/alone.py\n+X = 1\n*** End Patch\n"
        event = {"hook_event_name": "PostToolUse", "session_id": "codex", "cwd": str(self.root), "tool_name": "apply_patch", "tool_input": {"command": patch}}
        text = hook.respond(event)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Tessri, on `pkg/core.py`:", text)
        self.assertNotIn("pkg/alone.py", text)  # touched too, but nothing depends on it

    def test_a_file_outside_the_project_or_gone_or_unknown_is_ignored(self):
        self.assertIsNone(hook.respond(self.edit("pkg/core.py", **{"file_path": "/etc/hosts"})))
        self.assertIsNone(hook.respond(self.edit("pkg/missing.py")))
        event = self.edit("pkg/core.py")
        event["tool_input"] = {"command": "ls"}
        self.assertIsNone(hook.respond(event))
        event["tool_input"] = "not an object"
        self.assertIsNone(hook.respond(event))

    def test_the_project_is_the_git_top_level_above_the_cwd(self):
        event = self.edit("pkg/core.py")
        event["cwd"] = str(self.root / "pkg")
        self.assertIn("`pkg/core.py`", hook.respond(event)["hookSpecificOutput"]["additionalContext"])

    def test_other_events_say_nothing(self):
        self.assertIsNone(hook.respond({"hook_event_name": "SessionStart", "session_id": "s1", "cwd": str(self.root)}))
        self.assertIsNone(hook.respond({"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": str(self.root), "tool_input": {"file_path": str(self.root / "pkg/core.py")}}))
        self.assertIsNone(hook.respond({"session_id": "s1", "cwd": str(self.root)}))


class AtStopTest(HookRepo):
    def test_a_clean_tree_and_a_harmless_change_say_nothing(self):
        self.assertIsNone(hook.respond(self.stop()))
        write_tree(self.root, {"pkg/core.py": "def f():\n    return 2\n"})
        self.assertIsNone(hook.respond(self.stop()))

    def test_the_person_hears_what_the_uncommitted_work_did_once(self):
        (self.root / "pkg/core.py").unlink()
        answer = hook.respond(self.stop())
        self.assertEqual(set(answer), {"systemMessage"})
        text = answer["systemMessage"]
        self.assertTrue(text.startswith("Tessri, on the uncommitted work: `pkg/core.py` was deleted but is still imported (`pkg/app.py`, `pkg/cli.py`, `tests/test_core.py`)"), text)
        self.assertTrue(text.endswith("The evidence: `tessri check --since HEAD`; the page to hand over: `tessri brief --since HEAD`."), text)
        self.assertIsNone(hook.respond(self.stop()))
        self.assertIsNotNone(hook.respond(self.stop(session="s2")))

    def test_stop_hook_block_hands_the_findings_to_the_agent_first(self):
        write_tree(self.root, {".tessri.toml": 'stop_hook = "block"\n'})
        (self.root / "pkg/core.py").unlink()
        first = hook.respond(self.stop())
        self.assertEqual(first["decision"], "block")
        self.assertIn("`pkg/core.py` was deleted but is still imported", first["reason"])
        self.assertNotIn("systemMessage", first)
        second = hook.respond(self.stop(active=True))  # the host continued once; what is still open goes to the person
        self.assertEqual(set(second), {"systemMessage"})
        self.assertIsNone(hook.respond(self.stop(active=True)))
        self.assertIsNone(hook.respond(self.stop()))

    def test_a_directory_without_git_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:  # not inside the test repository, whose top level the hook would find
            plain = Path(tmp) / "plain"
            write_tree(plain, {"a.py": "import b\n", "b.py": ""})
            self.assertIsNone(hook.respond({"hook_event_name": "Stop", "session_id": "s", "cwd": str(plain)}))
            spoken = hook.respond({"hook_event_name": "PostToolUse", "session_id": "s", "cwd": str(plain), "tool_input": {"file_path": str(plain / "b.py")}})
            text = spoken["hookSpecificOutput"]["additionalContext"]  # impact needs no history, so an edit still speaks
            self.assertTrue(text.startswith("Tessri, on `b.py`: 1 code file depends on it, 1 directly (`a.py`); no test file reaches it."), text)
            self.assertNotIn("maintained by", text)


class RunTest(HookRepo):
    def run_hook(self, stdin: str, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["hook", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_the_command_prints_the_answer_or_nothing(self):
        code, out, err = self.run_hook(json.dumps(self.edit("pkg/core.py")), "--repo", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        code, out, err = self.run_hook(json.dumps(self.edit("pkg/alone.py")), "--repo", str(self.root))
        self.assertEqual((code, out, err), (0, "", ""))

    def test_bad_input_or_a_bad_configuration_is_one_line_and_exit_1(self):
        code, out, err = self.run_hook("not json\n")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "tessri hook: stdin is not a JSON object (the host's event)\n")
        write_tree(self.root, {".tessri.toml": 'stop_hook = "maybe"\n'})
        code, out, err = self.run_hook(json.dumps(self.stop()), "--repo", str(self.root))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("`stop_hook` must be one of 'inform', 'block'", err)
        code, _, err = self.run_hook(json.dumps(self.stop()), "--repo", str(self.root / "nope"))
        self.assertEqual(code, 1)
        self.assertIn("not a directory", err)

    def test_the_command_takes_the_root_as_repo_only(self):
        self.assertEqual(cli.build_parser().parse_args(["hook", "--repo", "x"]).repo, "x")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["hook", "x"])


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.repo.setUp()
        self.addCleanup(self.repo._tmp.cleanup)
        patcher = mock.patch.object(hook, "STATE_DIR", self.repo.root / "state")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_old_sessions_are_forgotten_and_broken_files_ignored(self):
        now = time.time()
        hook.STATE_DIR.mkdir()
        stale = hook.STATE_DIR / "old.json"
        stale.write_text("{}")
        os.utime(stale, (now - 10 * 86400, now - 10 * 86400))
        broken = hook.STATE_DIR / (hook.Memory("s", now).path.name)
        broken.write_text("{not json")
        memory = hook.Memory("s", now)
        self.assertFalse(memory.seen("edits", "a.py"))
        memory.note("edits", "a.py")
        memory.save()
        self.assertFalse(stale.exists())
        self.assertEqual(json.loads(broken.read_text()), {"edits": ["a.py"]})
        self.assertTrue(hook.Memory("s", now).seen("edits", "a.py"))

    def test_the_file_name_is_a_hash_of_the_session_never_the_id(self):
        memory = hook.Memory("abc/../../etc/passwd", time.time())
        self.assertEqual(memory.path.parent, hook.STATE_DIR)
        self.assertNotIn("passwd", memory.path.name)
        self.assertIsNone(hook.Memory(None, time.time()).path)
        self.assertIsNone(hook.Memory(42, time.time()).path)


if __name__ == "__main__":
    unittest.main()
