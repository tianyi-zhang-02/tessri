"""`tessri integration`: install, update, status and remove with a receipt, never touching what the user wrote."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import pathlib
from pathlib import Path
from unittest import mock

from helpers import TempRepo, write_tree

from tessri import integration, templates
from tessri.cli import main
from tessri.integration import BEGIN, END, LOCK, PROFILES, RECEIPT, IntegrationError, run, status

PROJECT = {"src/app.py": "import src.lib\n", "src/lib.py": "x = 1\n", "README.md": "# demo\n", ".gitignore": "dist/\n"}
SKILL = ".claude/skills/tessri/SKILL.md"
CODEX = ".agents/skills/tessri/SKILL.md"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` with its bytes, for before/after comparisons."""
    out = {}
    for base, dirs, files in os.walk(root):
        for name in files:
            p = Path(base) / name
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


class Project(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, PROJECT)

    def receipt(self) -> dict:
        return json.loads((self.root / RECEIPT).read_text())

    def actions(self, doc: dict) -> dict[str, str]:
        return {a["profile"]: a["action"] for a in doc["actions"]}

    def conflicts(self, doc: dict) -> dict[str, str]:
        return {c["profile"]: c["reason"] for c in doc["conflicts"]}


class InstallTest(Project):
    def test_dry_run_plans_everything_and_writes_nothing(self):
        before = tree(self.root)
        doc = run(self.root, "install", ["claude", "agents"], dry_run=True)
        self.assertEqual(self.actions(doc), {"claude": "create", "agents": "create"})
        self.assertEqual((doc["dry_run"], doc["applied"], doc["receipt"]["action"], doc["conflicts"]), (True, False, "create", []))
        self.assertEqual(tree(self.root), before)
        self.assertFalse((self.root / LOCK).exists())

    def test_install_writes_only_its_targets_and_a_receipt(self):
        before = tree(self.root)
        doc = run(self.root, "install", ["claude", "codex", "agents"])
        self.assertEqual((doc["applied"], doc["conflicts"]), (True, []))
        after = tree(self.root)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)  # nothing that existed changed
        self.assertEqual(set(after) - set(before), {SKILL, CODEX, "AGENTS.md", RECEIPT})
        self.assertEqual(after[SKILL].decode(), templates.SKILL)
        self.assertEqual(after[CODEX].decode(), templates.SKILL)
        self.assertTrue(after["AGENTS.md"].startswith(BEGIN.encode()) and after["AGENTS.md"].rstrip(b"\n").endswith(END.encode()))
        rec = self.receipt()
        self.assertEqual((rec["manifest_version"], rec["profiles"]), (1, ["claude", "codex", "agents"]))
        by = {t["profile"]: t for t in rec["targets"]}
        self.assertEqual(by["claude"]["dirs_created"], [".claude", ".claude/skills", ".claude/skills/tessri"])
        self.assertTrue(by["claude"]["created"] and by["agents"]["created"])
        self.assertEqual(by["agents"]["span"].encode(), after["AGENTS.md"])
        self.assertNotIn(str(self.root), (self.root / RECEIPT).read_text())  # no machine paths in the receipt
        self.assertIn("claude: start a new Claude Code session", " ".join(doc["notes"]))

    def test_repeated_install_changes_no_byte(self):
        run(self.root, "install", ["claude", "agents"])
        before = tree(self.root)
        doc = run(self.root, "install", ["claude", "agents"])
        self.assertEqual(self.actions(doc), {"claude": "unchanged", "agents": "unchanged"})
        self.assertEqual((doc["receipt"]["action"], doc["notes"]), ("unchanged", []))
        self.assertEqual(tree(self.root), before)
        self.assertEqual(before["AGENTS.md"].count(BEGIN.encode()), 1)

    def test_install_adds_a_profile_to_an_existing_receipt(self):
        run(self.root, "install", ["claude"])
        doc = run(self.root, "install", ["codex"])
        self.assertEqual(self.actions(doc), {"codex": "create"})
        self.assertEqual(self.receipt()["profiles"], ["claude", "codex"])

    def test_install_needs_a_profile(self):
        with self.assertRaises(IntegrationError):
            run(self.root, "install", None)
        code, out, err = run_cli("integration", "install", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--agent", err)

    def test_existing_skill_is_a_conflict_even_when_identical(self):
        write_tree(self.root, {SKILL: templates.SKILL})
        before = tree(self.root)
        doc = run(self.root, "install", ["claude", "agents"])
        self.assertEqual(self.conflicts(doc), {"claude": "unmanaged"})
        self.assertEqual(self.actions(doc), {"agents": "create"})  # planned, but not applied
        self.assertEqual((doc["applied"], tree(self.root)), (False, before))
        self.assertFalse((self.root / RECEIPT).exists())

    def test_a_block_under_our_markers_that_no_receipt_installed_is_a_conflict(self):
        write_tree(self.root, {"AGENTS.md": f"# demo\n\n{BEGIN}\nwritten by hand\n{END}\n"})
        before = tree(self.root)
        doc = run(self.root, "install", ["agents"])
        self.assertEqual(self.conflicts(doc), {"agents": "markers"})
        self.assertEqual(tree(self.root), before)

    def test_span_appended_to_crlf_file_without_trailing_newline(self):
        original = "# Agents\r\n\r\nKeep me é中".encode("utf-8")
        (self.root / "AGENTS.md").write_bytes(original)
        mode = 0o640
        os.chmod(self.root / "AGENTS.md", mode)
        doc = run(self.root, "install", ["agents"])
        self.assertEqual(self.actions(doc), {"agents": "update"})
        data = (self.root / "AGENTS.md").read_bytes()
        self.assertTrue(data.startswith(original + b"\r\n\r\n" + BEGIN.encode() + b"\r\n"))
        self.assertNotIn(b"\n\n", data.replace(b"\r\n", b""))  # the block itself uses CRLF
        self.assertEqual(os.stat(self.root / "AGENTS.md").st_mode & 0o777, mode)
        self.assertFalse(self.receipt()["targets"][0]["created"])
        run(self.root, "remove", None)
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), original)
        self.assertEqual(os.stat(self.root / "AGENTS.md").st_mode & 0o777, mode)
        self.assertFalse((self.root / RECEIPT).exists())

    def test_span_after_trailing_newline_leaves_one_blank_line(self):
        (self.root / "AGENTS.md").write_bytes(b"# Agents\n")
        run(self.root, "install", ["agents"])
        self.assertTrue((self.root / "AGENTS.md").read_bytes().startswith(b"# Agents\n\n" + BEGIN.encode()))

    @unittest.skipIf(sys.platform == "win32", "symlinks")
    def test_symlinked_parent_is_refused_without_touching_the_referent(self):
        elsewhere = self.root.parent / (self.root.name + "-elsewhere")
        elsewhere.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(elsewhere, ignore_errors=True))
        (self.root / ".claude").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(IntegrationError, "symlink"):
            run(self.root, "install", ["claude", "agents"])
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertFalse((self.root / RECEIPT).exists() or (self.root / "AGENTS.md").exists())
        code, out, err = run_cli("integration", "install", str(self.root), "--agent", "claude", "--format", "json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(".claude", err)

    @unittest.skipIf(sys.platform == "win32", "symlinks")
    def test_dangling_symlink_target_is_refused_before_any_read(self):
        (self.root / "AGENTS.md").symlink_to(self.root / "nowhere.md")
        real_read = integration._read

        def guarded(path):
            if path.name == "AGENTS.md":
                raise AssertionError("read through a link")
            return real_read(path)

        with mock.patch.object(integration, "_read", guarded):
            with self.assertRaisesRegex(IntegrationError, "symlink"):
                run(self.root, "install", ["agents"])
        self.assertFalse((self.root / "nowhere.md").exists())

    def test_user_file_with_a_temp_like_name_survives(self):
        mine = self.root / ".claude/skills/tessri/.SKILL.md.tessri-tmp"
        write_tree(self.root, {mine.relative_to(self.root).as_posix(): "mine\n"})
        run(self.root, "install", ["claude"])
        self.assertEqual((mine.read_text(), (self.root / SKILL).read_text()), ("mine\n", templates.SKILL))
        run(self.root, "remove", None)
        self.assertEqual(mine.read_text(), "mine\n")  # the directory it lives in is kept too
        self.assertFalse((self.root / SKILL).exists())


class UpdateTest(Project):
    def setUp(self):
        super().setUp()
        (self.root / "AGENTS.md").write_text("# Agents\n\nHouse rules.\n")
        run(self.root, "install", ["claude", "agents"])

    def test_update_is_a_no_op_when_current(self):
        before = tree(self.root)
        doc = run(self.root, "update", None)
        self.assertEqual(self.actions(doc), {"claude": "unchanged", "agents": "unchanged"})
        self.assertEqual(tree(self.root), before)

    def test_update_refreshes_an_outdated_skill_and_block(self):
        with mock.patch.object(templates, "SKILL", templates.SKILL + "\nNew paragraph.\n"), mock.patch.object(templates, "AGENTS_BLOCK", "## Repository health (tessri)\n\nNew text.\n"):
            self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"claude": "installed-outdated", "agents": "installed-outdated"})
            doc = run(self.root, "update", None)
            self.assertEqual(self.actions(doc), {"claude": "update", "agents": "update"})
            self.assertTrue((self.root / SKILL).read_text().endswith("New paragraph.\n"))
            agents = (self.root / "AGENTS.md").read_bytes()
            self.assertTrue(agents.startswith(b"# Agents\n\nHouse rules.\n\n" + BEGIN.encode()))
            self.assertIn(b"New text.", agents)
            self.assertEqual(agents.count(BEGIN.encode()), 1)
            self.assertEqual({r["state"] for r in status(self.root)["targets"]}, {"installed-current"})

    def test_edits_outside_the_block_survive_an_update(self):
        agents = self.root / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + b"\nMy own section after the block.\n")
        with mock.patch.object(templates, "AGENTS_BLOCK", "## Repository health (tessri)\n\nNew text.\n"):
            doc = run(self.root, "update", ["agents"])
        self.assertEqual(self.actions(doc), {"agents": "update"})
        data = agents.read_bytes()
        self.assertTrue(data.startswith(b"# Agents\n\nHouse rules.\n\n") and data.endswith(b"\nMy own section after the block.\n"))
        self.assertIn(b"New text.", data)

    def test_edited_skill_is_a_conflict_and_nothing_is_written(self):
        skill = self.root / SKILL
        skill.write_text(skill.read_text() + "my note\n")
        before = tree(self.root)
        with mock.patch.object(templates, "AGENTS_BLOCK", "## Repository health (tessri)\n\nNew text.\n"):
            doc = run(self.root, "update", None)
        self.assertEqual(self.conflicts(doc), {"claude": "modified"})
        self.assertEqual(self.actions(doc), {"agents": "update"})
        self.assertEqual((doc["applied"], tree(self.root)), (False, before))  # one conflict blocks the other target too

    def test_edited_block_is_a_conflict(self):
        agents = self.root / "AGENTS.md"
        agents.write_bytes(agents.read_bytes().replace(b"tessri scan", b"tessri SCAN", 1))
        doc = run(self.root, "update", None)
        self.assertEqual(self.conflicts(doc), {"agents": "modified"})
        self.assertEqual(status(self.root)["targets"][1]["state"], "user-modified")

    def test_missing_skill_is_recreated(self):
        (self.root / SKILL).unlink()
        (self.root / SKILL).parent.rmdir()
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}["claude"], "missing")
        doc = run(self.root, "update", ["claude"])
        self.assertEqual(self.actions(doc), {"claude": "create"})
        self.assertEqual((self.root / SKILL).read_text(), templates.SKILL)
        self.assertEqual(self.receipt()["targets"][0]["dirs_created"], [".claude", ".claude/skills", ".claude/skills/tessri"])

    def test_unrecorded_profile_is_an_error(self):
        with self.assertRaises(IntegrationError):
            run(self.root, "update", ["codex"])
        code, out, _ = run_cli("integration", "update", str(self.root), "--agent", "codex", "--format", "json")
        self.assertEqual((code, out), (2, ""))


class RemoveTest(Project):
    def test_install_then_remove_restores_the_project(self):
        (self.root / "AGENTS.md").write_bytes(b"# Agents\n\nHouse rules.")
        before = tree(self.root)
        run(self.root, "install", ["claude", "codex", "agents"])
        doc = run(self.root, "remove", None)
        self.assertEqual(self.actions(doc), {"claude": "remove", "codex": "remove", "agents": "remove"})
        self.assertEqual((doc["receipt"]["action"], doc["notes"]), ("remove", []))
        self.assertEqual(tree(self.root), before)
        self.assertFalse((self.root / ".claude").exists() or (self.root / ".agents").exists())

    def test_remove_keeps_directories_it_did_not_create(self):
        write_tree(self.root, {".claude/settings.json": "{}\n"})
        run(self.root, "install", ["claude"])
        self.assertEqual(self.receipt()["targets"][0]["dirs_created"], [".claude/skills", ".claude/skills/tessri"])
        run(self.root, "remove", None)
        self.assertEqual(sorted(p.name for p in (self.root / ".claude").iterdir()), ["settings.json"])

    def test_remove_keeps_a_directory_that_gained_other_files(self):
        run(self.root, "install", ["claude"])
        write_tree(self.root, {".claude/skills/other/SKILL.md": "---\nname: other\n---\n"})
        run(self.root, "remove", None)
        self.assertFalse((self.root / SKILL).exists())
        self.assertFalse((self.root / ".claude/skills/tessri").exists())
        self.assertTrue((self.root / ".claude/skills/other/SKILL.md").exists())

    def test_subset_removal_keeps_the_rest(self):
        run(self.root, "install", ["claude", "codex"])
        doc = run(self.root, "remove", ["claude"])
        self.assertEqual(self.actions(doc), {"claude": "remove"})
        self.assertFalse((self.root / SKILL).exists())
        self.assertEqual((self.root / CODEX).read_text(), templates.SKILL)
        self.assertEqual(self.receipt()["profiles"], ["codex"])

    def test_edited_target_is_kept_and_stays_recorded(self):
        run(self.root, "install", ["claude", "agents"])
        (self.root / SKILL).write_text("mine now\n")
        before = tree(self.root)
        doc = run(self.root, "remove", None)
        self.assertEqual(self.conflicts(doc), {"claude": "modified"})
        self.assertEqual((doc["applied"], tree(self.root)), (False, before))
        self.assertEqual(self.receipt()["profiles"], ["claude", "agents"])

    def test_missing_target_is_forgotten_and_its_empty_directories_reclaimed(self):
        run(self.root, "install", ["claude"])
        (self.root / SKILL).unlink()
        doc = run(self.root, "remove", None)
        self.assertEqual((self.actions(doc), doc["receipt"]["action"]), ({"claude": "forget"}, "remove"))
        self.assertFalse((self.root / RECEIPT).exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_forget_keeps_a_created_directory_that_is_no_longer_empty(self):
        run(self.root, "install", ["claude"])
        (self.root / SKILL).unlink()
        write_tree(self.root, {".claude/skills/other.md": "x\n"})
        run(self.root, "remove", None)
        self.assertFalse((self.root / ".claude/skills/tessri").exists())
        self.assertTrue((self.root / ".claude/skills/other.md").exists())

    def test_removing_a_profile_that_is_not_recorded_is_a_no_op(self):
        run(self.root, "install", ["claude", "codex"])
        run(self.root, "remove", ["codex"])
        before = tree(self.root)
        doc = run(self.root, "remove", ["codex"])
        self.assertEqual((doc["actions"], doc["conflicts"], doc["receipt"]["action"]), ([], [], "unchanged"))
        self.assertEqual(tree(self.root), before)
        self.assertEqual(self.receipt()["profiles"], ["claude"])
        code, _, _ = run_cli("integration", "remove", str(self.root), "--agent", "codex")
        self.assertEqual(code, 0)
        run(self.root, "remove", None)
        self.assertEqual(run_cli("integration", "remove", str(self.root), "--agent", "codex")[0], 0)

    def test_created_agents_file_with_user_additions_is_kept(self):
        run(self.root, "install", ["agents"])
        agents = self.root / "AGENTS.md"
        agents.write_bytes(agents.read_bytes() + b"\nMine.\n")
        run(self.root, "remove", None)
        self.assertEqual(agents.read_bytes(), b"\nMine.\n")

    def test_pre_existing_agents_file_is_never_deleted(self):
        (self.root / "AGENTS.md").write_bytes(b"")
        run(self.root, "install", ["agents"])
        run(self.root, "remove", None)
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), b"")

    def test_remove_without_a_receipt_is_a_no_op(self):
        write_tree(self.root, {SKILL: templates.SKILL, "AGENTS.md": f"{BEGIN}\n{templates.AGENTS_BLOCK}{END}\n"})  # familiar files, no receipt
        before = tree(self.root)
        for profiles in (None, ["claude"]):
            doc = run(self.root, "remove", profiles)
            self.assertEqual((doc["actions"], doc["conflicts"], doc["receipt"]["action"]), ([], [], "unchanged"))
        self.assertEqual(tree(self.root), before)
        code, out, _ = run_cli("integration", "remove", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("Nothing to do.", out)


class StatusTest(Project):
    def test_nothing_installed(self):
        doc = status(self.root)
        self.assertEqual((doc["installed"], doc["targets"], doc["attention"]), (False, [], False))
        code, out, _ = run_cli("integration", "status", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("No Tessri integration receipt", out)

    def test_files_at_the_profiles_paths_that_no_receipt_records_are_unmanaged(self):
        write_tree(self.root, {SKILL: templates.SKILL, "AGENTS.md": f"{BEGIN}\n{templates.AGENTS_BLOCK}{END}\n", ".tessri.toml": "active_days = 7\n"})
        doc = status(self.root)
        self.assertEqual(doc["installed"], False)
        self.assertEqual({r["profile"]: r["state"] for r in doc["targets"]}, {"claude": "unmanaged", "agents": "unmanaged"})

    def test_states(self):
        run(self.root, "install", ["claude", "codex", "agents"])
        doc = status(self.root)
        self.assertEqual(({r["state"] for r in doc["targets"]}, doc["attention"], doc["installed_by"]), ({"installed-current"}, False, integration.__version__))
        (self.root / SKILL).write_text("edited\n")
        (self.root / CODEX).unlink()
        doc = status(self.root)
        self.assertEqual({r["profile"]: r["state"] for r in doc["targets"]}, {"claude": "user-modified", "codex": "missing", "agents": "installed-current"})
        self.assertTrue(doc["attention"])
        code, out, _ = run_cli("integration", "status", str(self.root), "--format", "json")
        self.assertEqual((code, json.loads(out)["kind"]), (0, "integration-status"))


class ReceiptTest(Project):
    def write_receipt(self, text: str) -> None:
        (self.root / RECEIPT).write_text(text)

    def test_corrupt_receipt_blocks_every_operation(self):
        run(self.root, "install", ["claude"])
        self.write_receipt("{not json")
        before = tree(self.root)
        for op, profiles in (("install", ["codex"]), ("update", None), ("remove", None)):
            with self.assertRaises(IntegrationError):
                run(self.root, op, profiles)
        with self.assertRaises(IntegrationError):
            status(self.root)
        self.assertEqual(tree(self.root), before)
        code, out, err = run_cli("integration", "status", str(self.root), "--format", "json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not valid JSON", err)

    def test_unsupported_version(self):
        self.write_receipt(json.dumps({"manifest_version": 99, "targets": []}))
        with self.assertRaisesRegex(IntegrationError, "manifest_version 99"):
            status(self.root)

    def test_forged_target_path(self):
        target = {"profile": "claude", "path": "../outside.md", "kind": "file", "sha256": "0" * 64, "created": True, "dirs_created": []}
        self.write_receipt(json.dumps({"manifest_version": 1, "targets": [target]}))
        with self.assertRaisesRegex(IntegrationError, "only .claude/skills/tessri/SKILL.md"):
            run(self.root, "remove", None)

    def test_forged_directory_and_duplicate_profile(self):
        good = {"profile": "claude", "path": SKILL, "kind": "file", "sha256": "0" * 64, "created": True, "dirs_created": ["src"]}
        self.write_receipt(json.dumps({"manifest_version": 1, "targets": [good]}))
        with self.assertRaisesRegex(IntegrationError, "not a parent"):
            status(self.root)
        good["dirs_created"] = []
        self.write_receipt(json.dumps({"manifest_version": 1, "targets": [good, dict(good)]}))
        with self.assertRaisesRegex(IntegrationError, "recorded twice"):
            status(self.root)

    def test_span_must_match_its_hash(self):
        target = {"profile": "agents", "path": "AGENTS.md", "kind": "span", "sha256": "0" * 64, "created": True, "dirs_created": [], "span": f"{BEGIN}\nx\n{END}\n"}
        self.write_receipt(json.dumps({"manifest_version": 1, "targets": [target]}))
        with self.assertRaisesRegex(IntegrationError, "does not match its hash"):
            status(self.root)

    @unittest.skipIf(sys.platform == "win32", "symlinks")
    def test_symlinked_receipt_is_an_error(self):
        (self.root / "real.json").write_text(json.dumps({"manifest_version": 1, "targets": []}))
        (self.root / RECEIPT).symlink_to(self.root / "real.json")
        with self.assertRaisesRegex(IntegrationError, "symlink"):
            run(self.root, "install", ["claude"])
        self.assertFalse((self.root / SKILL).exists())


class ConcurrencyTest(Project):
    def test_existing_lock_is_a_reported_conflict_and_is_kept(self):
        (self.root / LOCK).write_text("12345\n")
        before = tree(self.root)
        doc = run(self.root, "install", ["claude"])
        self.assertEqual([c["reason"] for c in doc["conflicts"]], ["busy"])
        self.assertEqual(tree(self.root), before)
        self.assertEqual((self.root / LOCK).read_text(), "12345\n")
        code, _, _ = run_cli("integration", "install", str(self.root), "--agent", "claude")
        self.assertEqual(code, 1)

    def test_lock_is_released_and_dry_run_takes_none(self):
        run(self.root, "install", ["claude"], dry_run=True)
        self.assertFalse((self.root / LOCK).exists())
        run(self.root, "install", ["claude"])
        self.assertFalse((self.root / LOCK).exists())

    def test_lock_write_failure_leaves_no_lock_behind(self):
        with mock.patch.object(integration.os, "write", side_effect=OSError(28, "No space left on device")):
            with self.assertRaisesRegex(IntegrationError, "cannot write"):
                run(self.root, "install", ["claude"])
        self.assertFalse((self.root / LOCK).exists())
        self.assertFalse((self.root / SKILL).exists())

    def test_input_changed_between_plan_and_apply_is_a_conflict(self):
        real_plan = integration.plan
        calls = []

        def racing_plan(root, op, profiles):
            calls.append(1)
            if len(calls) == 2:  # the recheck sees a file that appeared after the first plan
                write_tree(root, {SKILL: "someone else's\n"})
            return real_plan(root, op, profiles)

        with mock.patch.object(integration, "plan", racing_plan):
            doc = run(self.root, "install", ["claude"])
        self.assertIn("changed", [c["reason"] for c in doc["conflicts"]])
        self.assertEqual((doc["applied"], (self.root / SKILL).read_text()), (False, "someone else's\n"))
        self.assertFalse((self.root / RECEIPT).exists() or (self.root / LOCK).exists())


class RollbackTest(Project):
    def failing_codex_write(self):
        real = integration._atomic_write

        def flaky(path, data, mode):
            if ".agents" in path.parts:  # the second target's write fails after the first one succeeded
                raise OSError(28, "No space left on device", str(path))
            return real(path, data, mode)

        return mock.patch.object(integration, "_atomic_write", flaky)

    def test_failure_on_a_later_target_rolls_the_earlier_one_back(self):
        (self.root / "AGENTS.md").write_bytes(b"# Agents\n")
        before = tree(self.root)
        with self.failing_codex_write():
            with self.assertRaisesRegex(IntegrationError, "No space left on device; every earlier change was rolled back"):
                run(self.root, "install", ["claude", "codex", "agents"])
        self.assertEqual(tree(self.root), before)
        self.assertFalse((self.root / ".claude").exists() or (self.root / ".agents").exists())
        self.assertFalse((self.root / LOCK).exists())
        with self.failing_codex_write():
            code, out, err = run_cli("integration", "install", str(self.root), "--agent", "claude", "--agent", "codex", "--format", "json")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("rolled back", err)

    def test_unreadable_target_is_an_error_before_any_write(self):
        (self.root / ".agents").write_text("not a directory\n")  # the codex target cannot even be read
        before = tree(self.root)
        with self.assertRaisesRegex(IntegrationError, "cannot read"):
            run(self.root, "install", ["claude", "codex"])
        self.assertEqual(tree(self.root), before)


class CliTextTest(Project):
    def test_dry_run_text(self):
        code, out, _ = run_cli("integration", "install", "--repo", str(self.root), "--agent", "claude", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would create  .claude/skills/tessri/SKILL.md (claude)", out)
        self.assertIn(f"would create  {RECEIPT}", out)
        self.assertIn("Dry run: nothing was written.", out)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".gitignore", "README.md", "src"])

    def test_conflict_text_and_exit_code(self):
        write_tree(self.root, {CODEX: "foreign\n"})
        code, out, _ = run_cli("integration", "install", str(self.root), "--agent", "codex")
        self.assertEqual(code, 1)
        self.assertIn("conflict      .agents/skills/tessri/SKILL.md (codex): a file already exists", out)
        self.assertIn("nothing was written", out)

    def test_missing_or_non_directory_project_exits_2(self):
        for path in (str(self.root / "nope"), str(self.root / "README.md")):
            code, out, err = run_cli("integration", "status", path)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("not a directory", err)

    def test_skill_profiles_share_one_source(self):
        self.assertEqual(PROFILES["claude"].content(), PROFILES["codex"].content())
        self.assertNotIn(".tessri/report.json", templates.SKILL)
        self.assertNotIn("uvx", templates.SKILL)
        self.assertIn("unavailable", templates.SKILL)
        self.assertNotIn("--fail-on block     #", templates.SKILL)  # the routine example does not gate
        self.assertIn("do not start every task with a full scan", templates.SKILL)
        self.assertLess(templates.SKILL.index("tessri impact <path>"), templates.SKILL.index("## Run it"))


class SeedAndReportTest(Project):
    """`config` seeds `.tessri.toml`, which is the user's from the moment it is written; `report` is a managed
    workflow file like a skill."""

    CONFIG = ".tessri.toml"
    WORKFLOW = ".github/workflows/tessri-report.yml"

    def states(self) -> dict[str, str]:
        return {r["profile"]: r["state"] for r in status(self.root)["targets"]}

    def test_install_writes_the_starter_configuration_and_the_workflow(self):
        doc = run(self.root, "install", ["config", "report"])
        self.assertTrue(doc["applied"])
        self.assertEqual(self.actions(doc), {"config": "create", "report": "create"})
        self.assertEqual((self.root / self.CONFIG).read_text(), templates.CONFIG)
        workflow = (self.root / self.WORKFLOW).read_text()
        self.assertEqual(workflow, templates.REPORT_WORKFLOW)
        self.assertIn(f"pip install tessri=={integration.__version__}\n", workflow)
        self.assertEqual({t["profile"]: t["kind"] for t in self.receipt()["targets"]}, {"config": "seed", "report": "file"})
        self.assertEqual(len(doc["notes"]), 2)
        for note in doc["notes"]:
            self.assertNotIn("running host", note)  # neither is read by an agent
        self.assertEqual(self.states(), {"config": "installed-current", "report": "installed-current"})
        code, out, _ = run_cli("scan", str(self.root), "--format", "json")  # the seeded configuration is read like any other
        self.assertEqual((code, json.loads(out)["settings"]["active_days"]), (0, 90))

    def test_an_existing_configuration_is_a_conflict(self):
        write_tree(self.root, {self.CONFIG: "active_days = 7\n"})
        doc = run(self.root, "install", ["config"])
        self.assertEqual((self.conflicts(doc), doc["applied"]), ({"config": "unmanaged"}, False))
        self.assertFalse((self.root / RECEIPT).exists())

    def test_an_edited_configuration_is_yours(self):
        run(self.root, "install", ["config", "claude"])
        (self.root / self.CONFIG).write_text("active_days = 7\n")
        self.assertEqual(self.states()["config"], "installed-current")  # the seed has done its job
        doc = run(self.root, "update", None)
        self.assertEqual((self.actions(doc), doc["applied"]), ({"config": "unchanged", "claude": "unchanged"}, True))
        self.assertEqual((self.root / self.CONFIG).read_text(), "active_days = 7\n")
        doc = run(self.root, "remove", None)
        self.assertEqual((self.actions(doc), doc["applied"]), ({"config": "forget", "claude": "remove"}, True))
        self.assertEqual((self.root / self.CONFIG).read_text(), "active_days = 7\n")
        self.assertFalse((self.root / RECEIPT).exists())
        self.assertEqual(status(self.root)["targets"], [])  # the user's configuration is not an unmanaged target

    def test_an_untouched_configuration_is_removed_and_a_deleted_one_forgotten(self):
        run(self.root, "install", ["config"])
        doc = run(self.root, "remove", None)
        self.assertEqual(self.actions(doc), {"config": "remove"})
        self.assertFalse((self.root / self.CONFIG).exists())
        run(self.root, "install", ["config"])
        (self.root / self.CONFIG).unlink()
        self.assertEqual(self.states(), {"config": "missing"})
        doc = run(self.root, "update", None)
        self.assertEqual(self.actions(doc), {"config": "forget"})
        self.assertFalse((self.root / self.CONFIG).exists())
        self.assertFalse((self.root / RECEIPT).exists())

    def test_the_review_workflow_is_a_managed_file_too(self):
        doc = run(self.root, "install", ["review"])
        self.assertEqual(self.actions(doc), {"review": "create"})
        path = self.root / ".github/workflows/tessri-review.yml"
        self.assertEqual(path.read_text(), templates.REVIEW_WORKFLOW)
        self.assertNotIn("running host", doc["notes"][0])
        for text in (templates.REVIEW_WORKFLOW, templates.REPORT_WORKFLOW):
            self.assertIn(f"pip install tessri=={integration.__version__}\n", text)  # pinned to the Tessri that installed it
            self.assertNotIn("__VERSION__", text)
        self.assertIn("on:\n  pull_request:\n", templates.REVIEW_WORKFLOW)
        self.assertIn("pull-requests: write", templates.REVIEW_WORKFLOW)
        self.assertNotIn("security-events: write\n", templates.REVIEW_WORKFLOW.replace("# `security-events: write`", ""))  # the upload is opt-in
        self.assertIn('--since "origin/$BASE"', templates.REVIEW_WORKFLOW)
        self.assertNotIn("origin/main", templates.REVIEW_WORKFLOW)  # the base is the event's, never an assumed name
        self.assertIn("--fail-on never", templates.REVIEW_WORKFLOW)
        doc = run(self.root, "remove", None)
        self.assertEqual(self.actions(doc), {"review": "remove"})
        self.assertFalse((self.root / ".github").exists())

    def test_the_workflow_is_managed_like_a_skill(self):
        run(self.root, "install", ["report"])
        path = self.root / self.WORKFLOW
        path.write_text("edited\n")
        self.assertEqual(self.states(), {"report": "user-modified"})
        doc = run(self.root, "update", None)
        self.assertEqual((self.conflicts(doc), doc["applied"]), ({"report": "modified"}, False))
        path.write_text(templates.REPORT_WORKFLOW)
        doc = run(self.root, "remove", None)
        self.assertEqual(self.actions(doc), {"report": "remove"})
        self.assertFalse((self.root / ".github").exists())


def comment_script() -> str:
    """The shell of the review workflow's Comment step, as the runner would get it."""
    lines = templates.REVIEW_WORKFLOW.splitlines()
    start = lines.index("      - name: Comment")
    run_at = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    body = []
    for line in lines[run_at + 1 :]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


@unittest.skipIf(shutil.which("bash") is None, "the comment step is a bash script")
class ReviewCommentTest(unittest.TestCase):
    """The Comment step posts one comment that starts with the marker and updates it in place afterwards. A stub `gh`
    records what it is asked and answers the listing with the ids the test chooses."""

    STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
case "$*" in
  *"--paginate"*) printf '%s' "$GH_EXISTING" ;;
esac
"""

    def post(self, existing: str) -> tuple[list[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            (work / "bin").mkdir()
            stub = work / "bin/gh"
            stub.write_text(self.STUB)
            stub.chmod(0o755)
            (work / "tessri-brief.md").write_text("# Review brief: demo\n\nthe page\n")
            env = {
                **os.environ,
                "PATH": f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}",
                "GH_LOG": str(work / "log"),
                "GH_EXISTING": existing,
                "BASE": "main",
                "REPO": "o/r",
                "NUMBER": "12",
                "HEAD_SHA": "0123456789abcdef",
                "RUN_URL": "https://example.test/runs/1",
            }
            res = subprocess.run(["bash", "-eo", "pipefail", "-c", comment_script()], cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            return (work / "log").read_text().splitlines(), (work / "tessri-comment.md").read_text()

    def test_the_first_run_posts_and_the_next_updates_in_place(self):
        calls, comment = self.post(existing="")
        self.assertEqual(comment, "<!-- tessri:review -->\n# Review brief: demo\n\nthe page\n\n_`tessri brief --since origin/main` at 012345678, by [this run](https://example.test/runs/1); updated on every push._\n")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("api repos/o/r/issues/12/comments --paginate --jq "))
        self.assertIn('startswith("<!-- tessri:review -->")', calls[0])
        self.assertEqual(calls[1], "api --method POST repos/o/r/issues/12/comments -F body=@tessri-comment.md --silent")
        calls, _ = self.post(existing="7\n9\n")  # the first comment with the marker is the one
        self.assertEqual(calls[1], "api --method PATCH repos/o/r/issues/comments/7 -F body=@tessri-comment.md --silent")


if __name__ == "__main__":
    unittest.main()


class ServerProfilesTest(Project):
    """The `mcp` and `vscode` profiles add one entry to a JSON file hosts read; `copilot` is a file of its own."""

    MCP = ".mcp.json"
    VSCODE = ".vscode/mcp.json"
    COPILOT = ".github/instructions/tessri.instructions.md"

    def test_install_into_an_empty_project_creates_the_files(self):
        doc = run(self.root, "install", ["mcp", "vscode", "copilot"])
        self.assertEqual(self.actions(doc), {"mcp": "create", "vscode": "create", "copilot": "create"})
        self.assertEqual(json.loads((self.root / self.MCP).read_text()), {"mcpServers": {"tessri": {"command": "tessri", "args": ["mcp"]}}})
        self.assertEqual(json.loads((self.root / self.VSCODE).read_text()), {"servers": {"tessri": {"type": "stdio", "command": "tessri", "args": ["mcp"]}}})
        copilot = (self.root / self.COPILOT).read_text()
        self.assertTrue(copilot.startswith('---\napplyTo: "**"\n---\n\n# Tessri\n'))
        self.assertIn("tessri_impact", copilot)
        by = {t["profile"]: t for t in self.receipt()["targets"]}
        self.assertEqual((by["mcp"]["kind"], by["mcp"]["created"], json.loads(by["mcp"]["span"])), ("key", True, {"command": "tessri", "args": ["mcp"]}))
        self.assertEqual(by["vscode"]["dirs_created"], [".vscode"])
        self.assertEqual(by["copilot"]["dirs_created"], [".github", ".github/instructions"])
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"mcp": "installed-current", "vscode": "installed-current", "copilot": "installed-current"})

    def test_an_existing_configuration_gets_one_entry_and_keeps_the_rest(self):
        write_tree(self.root, {self.MCP: '{"mcpServers": {"other": {"command": "x"}}}\n'})
        doc = run(self.root, "install", ["mcp"])
        self.assertEqual(self.actions(doc), {"mcp": "update"})
        self.assertEqual(json.loads((self.root / self.MCP).read_text()), {"mcpServers": {"other": {"command": "x"}, "tessri": {"command": "tessri", "args": ["mcp"]}}})
        self.assertFalse(self.receipt()["targets"][0]["created"])
        run(self.root, "remove", None)
        self.assertEqual(json.loads((self.root / self.MCP).read_text()), {"mcpServers": {"other": {"command": "x"}}})
        self.assertFalse((self.root / RECEIPT).exists())

    def test_a_created_file_that_held_only_our_entry_is_removed_with_its_directory(self):
        run(self.root, "install", ["vscode"])
        run(self.root, "remove", None)
        self.assertFalse((self.root / ".vscode").exists())

    def test_an_existing_entry_or_an_unreadable_file_is_a_conflict(self):
        write_tree(self.root, {self.MCP: '{"mcpServers": {"tessri": {"command": "mine"}}}\n', self.VSCODE: '{\n  // comments are allowed here, but not JSON\n  "servers": {}\n}\n'})
        doc = run(self.root, "install", ["mcp", "vscode"])
        self.assertEqual(self.conflicts(doc), {"mcp": "markers", "vscode": "unmanaged"})
        detail = next(c["detail"] for c in doc["conflicts"] if c["profile"] == "vscode")
        self.assertIn('add the entry by hand: {"servers": {"tessri": {"type": "stdio", "command": "tessri", "args": ["mcp"]}}}', detail)
        self.assertFalse((self.root / RECEIPT).exists())
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"mcp": "unmanaged"})  # a file without our entry is nobody's business

    def test_an_edited_entry_is_yours(self):
        run(self.root, "install", ["mcp"])
        write_tree(self.root, {self.MCP: '{"mcpServers": {"tessri": {"command": "tessri", "args": ["mcp", "--root", "."]}}}\n'})
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"mcp": "user-modified"})
        self.assertEqual(self.conflicts(run(self.root, "update", None)), {"mcp": "modified"})
        self.assertEqual(self.conflicts(run(self.root, "remove", None)), {"mcp": "modified"})
        self.assertTrue((self.root / RECEIPT).exists())

    def test_update_is_a_no_op_when_current_and_recreates_a_missing_file(self):
        run(self.root, "install", ["vscode"])
        self.assertEqual(self.actions(run(self.root, "update", None)), {"vscode": "unchanged"})
        (self.root / self.VSCODE).unlink()
        self.assertEqual(self.actions(run(self.root, "update", None)), {"vscode": "create"})
        self.assertEqual(json.loads((self.root / self.VSCODE).read_text())["servers"]["tessri"]["command"], "tessri")

    def test_status_says_what_each_host_has_and_what_is_next(self):
        hosts = {h["host"]: h for h in status(self.root)["hosts"]}
        self.assertEqual(hosts["Claude Code"], {"host": "Claude Code", "instructions": None, "server": None, "next": "tessri integration install --agent claude; tessri integration install --agent mcp", "hooks": None})
        run(self.root, "install", ["claude", "agents", "mcp"])
        doc = status(self.root)
        hosts = {h["host"]: h for h in doc["hosts"]}
        self.assertEqual(hosts["Claude Code"], {"host": "Claude Code", "instructions": SKILL, "server": self.MCP, "next": None, "hooks": None})
        self.assertNotIn("hooks", hosts["Copilot coding agent"])  # no hooks to install for a host that runs none
        self.assertEqual((hosts["Codex"]["instructions"], hosts["Codex"]["server"]), ("AGENTS.md", None))
        self.assertIn("run `codex mcp add tessri -- tessri mcp`", hosts["Codex"]["next"])
        self.assertIn('"tools": ["*"]', hosts["Copilot coding agent"]["next"])
        self.assertEqual(hosts["editors reading .vscode/mcp.json"]["next"], "tessri integration install --agent vscode")
        from tessri.integration import text

        self.assertIn(f"Claude Code: instructions {SKILL}; server .mcp.json; hooks none\n", text(doc))
        self.assertIn("Codex: instructions AGENTS.md; server none; hooks none; next: run `codex mcp add tessri -- tessri mcp`", text(doc))


class HookProfilesTest(Project):
    """The `claude-hooks` and `codex-hooks` profiles add one matcher group per event to a hooks file a host reads."""

    CLAUDE = ".claude/settings.json"
    CODEX_HOOKS = ".codex/hooks.json"
    MINE = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    INSTALLED = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "tessri hook", "timeout": 60}]}], "Stop": [{"hooks": [{"type": "command", "command": "tessri hook", "timeout": 120}]}]}}

    def read(self, rel: str) -> dict:
        return json.loads((self.root / rel).read_text())

    def test_install_into_an_empty_project_creates_both_files(self):
        doc = run(self.root, "install", ["claude-hooks", "codex-hooks"])
        self.assertEqual(self.actions(doc), {"claude-hooks": "create", "codex-hooks": "create"})
        self.assertEqual(self.read(self.CLAUDE), self.INSTALLED)
        self.assertEqual(self.read(self.CODEX_HOOKS), self.INSTALLED)
        by = {t["profile"]: t for t in self.receipt()["targets"]}
        self.assertEqual((by["claude-hooks"]["kind"], by["claude-hooks"]["created"], by["claude-hooks"]["dirs_created"]), ("hooks", True, [".claude"]))
        self.assertEqual(json.loads(by["codex-hooks"]["span"]), templates.HOOKS)
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"claude-hooks": "installed-current", "codex-hooks": "installed-current"})
        self.assertTrue(doc["notes"][0].startswith("claude-hooks: Claude Code runs them from your next session"), doc["notes"])
        self.assertTrue(doc["notes"][1].endswith("a changed hook has to be trusted again; the files being there does not prove a running host has seen them."), doc["notes"])

    def test_your_settings_and_hooks_around_ours_are_kept_and_restored(self):
        mine = {"permissions": {"allow": ["Bash(git *)"]}, "hooks": {"PostToolUse": [self.MINE]}}
        write_tree(self.root, {self.CLAUDE: json.dumps(mine, indent=2) + "\n"})
        doc = run(self.root, "install", ["claude-hooks"])
        self.assertEqual(self.actions(doc), {"claude-hooks": "update"})
        now = self.read(self.CLAUDE)
        self.assertEqual(now["permissions"], mine["permissions"])
        self.assertEqual(now["hooks"]["PostToolUse"], [self.MINE, templates.HOOKS["PostToolUse"]])
        self.assertEqual(now["hooks"]["Stop"], [templates.HOOKS["Stop"]])
        self.assertFalse(self.receipt()["targets"][0]["created"])
        run(self.root, "remove", None)
        self.assertEqual(self.read(self.CLAUDE), mine)
        self.assertFalse((self.root / RECEIPT).exists())

    def test_a_created_file_that_held_only_our_hooks_goes_with_its_directory(self):
        run(self.root, "install", ["codex-hooks"])
        run(self.root, "remove", None)
        self.assertFalse((self.root / ".codex").exists())

    def test_our_hooks_already_there_or_an_unreadable_file_are_conflicts(self):
        write_tree(self.root, {self.CLAUDE: json.dumps({"hooks": {"Stop": [templates.HOOKS["Stop"]]}}) + "\n", self.CODEX_HOOKS: '{"hooks": {"Stop": "no"}}\n'})
        doc = run(self.root, "install", ["claude-hooks", "codex-hooks"])
        self.assertEqual(self.conflicts(doc), {"claude-hooks": "markers", "codex-hooks": "unmanaged"})
        detail = next(c["detail"] for c in doc["conflicts"] if c["profile"] == "codex-hooks")
        self.assertIn('add the hooks by hand: {"hooks": {"PostToolUse": [{"matcher": "Edit|Write"', detail)
        self.assertFalse((self.root / RECEIPT).exists())
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"claude-hooks": "unmanaged"})  # a hooks file without ours is nobody's business

    def test_an_edited_group_is_yours(self):
        run(self.root, "install", ["claude-hooks"])
        doc = self.read(self.CLAUDE)
        doc["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 5
        write_tree(self.root, {self.CLAUDE: json.dumps(doc) + "\n"})
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"claude-hooks": "user-modified"})
        self.assertEqual(self.conflicts(run(self.root, "update", None)), {"claude-hooks": "modified"})
        self.assertEqual(self.conflicts(run(self.root, "remove", None)), {"claude-hooks": "modified"})
        self.assertTrue((self.root / RECEIPT).exists())

    def test_update_is_a_no_op_when_current_recreates_a_missing_file_and_refreshes_outdated_groups(self):
        run(self.root, "install", ["codex-hooks"])
        self.assertEqual(self.actions(run(self.root, "update", None)), {"codex-hooks": "unchanged"})
        (self.root / self.CODEX_HOOKS).unlink()
        self.assertEqual(self.actions(run(self.root, "update", None)), {"codex-hooks": "create"})
        self.assertEqual(self.read(self.CODEX_HOOKS), self.INSTALLED)
        doc = self.read(self.CODEX_HOOKS)
        doc["hooks"]["PostToolUse"].insert(0, self.MINE)  # a group of your own next to ours is not an edit of ours
        write_tree(self.root, {self.CODEX_HOOKS: json.dumps(doc) + "\n"})
        newer = {"PostToolUse": {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "tessri hook", "timeout": 90}]}, "Stop": templates.HOOKS["Stop"]}
        with mock.patch.object(templates, "HOOKS", newer):
            self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"codex-hooks": "installed-outdated"})
            self.assertEqual(self.actions(run(self.root, "update", None)), {"codex-hooks": "update"})
            now = self.read(self.CODEX_HOOKS)
            self.assertEqual(now["hooks"]["PostToolUse"], [self.MINE, newer["PostToolUse"]])
            self.assertEqual(now["hooks"]["Stop"], [newer["Stop"]])
            self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"codex-hooks": "installed-current"})
        self.assertEqual({r["profile"]: r["state"] for r in status(self.root)["targets"]}, {"codex-hooks": "installed-outdated"})

    def test_status_names_the_hooks_file_per_host(self):
        run(self.root, "install", ["claude-hooks"])
        hosts = {h["host"]: h for h in status(self.root)["hosts"]}
        self.assertEqual(hosts["Claude Code"]["hooks"], self.CLAUDE)
        self.assertIsNone(hosts["Codex"]["hooks"])
        self.assertNotIn("hooks", hosts["editors reading .vscode/mcp.json"])
        code, out, _ = run_cli("integration", "status", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("; hooks .claude/settings.json", out)
        self.assertIn("Codex: instructions none; server none; hooks none", out)

    def test_a_receipt_whose_hooks_do_not_match_their_hash_is_refused(self):
        run(self.root, "install", ["codex-hooks"])
        receipt = self.receipt()
        receipt["targets"][0]["span"] = json.dumps({"Stop": templates.HOOKS["Stop"]})
        (self.root / RECEIPT).write_text(json.dumps(receipt))
        with self.assertRaises(IntegrationError) as caught:
            status(self.root)
        self.assertIn("does not match its hash", str(caught.exception))
