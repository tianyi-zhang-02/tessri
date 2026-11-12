"""A release is a tag that matches the code: the notes script refuses a version the code does not state or the
changelog has no dated section for, and otherwise hands the release workflow that section with the install line."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import release_notes  # noqa: E402  (tools/ is not a package)

CHANGELOG = """# Changelog

## Unreleased

- not yet

## 0.3.0 (2026-11-06)

- the first thing
- the second thing, with `code`

## 0.2.0 (2026-11-04)

- older
"""


class ReleaseNotesTest(unittest.TestCase):
    def tree(self, version: str, changelog: str = CHANGELOG) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "tessri").mkdir()
        (root / "tessri" / "__init__.py").write_text(f'"""Doc."""\n\n__version__ = "{version}"\n', encoding="utf-8")
        (root / "pyproject.toml").write_text(f'[project]\nname = "tessri"\nversion = "{version}"\n', encoding="utf-8")
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        return root

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_notes.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_section_of_the_version_and_the_install_line_and_nothing_else(self):
        root = self.tree("0.3.0")
        code, out, err = self.run_main("0.3.0", "--root", str(root))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "- the first thing\n- the second thing, with `code`\n\n```\npip install tessri==0.3.0\n```\n")
        code, out, _ = self.run_main("0.3.0", "--root", str(root), "--out", str(root / "notes.md"))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("the first thing", (root / "notes.md").read_text(encoding="utf-8"))

    def test_a_tag_the_code_does_not_state_is_refused_with_both_numbers(self):
        root = self.tree("0.3.0")
        code, out, err = self.run_main("0.4.0", "--root", str(root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the tag says 0.4.0 but tessri/__init__.py says 0.3.0, pyproject.toml says 0.3.0", err)

    def test_a_version_without_a_dated_changelog_section_is_refused(self):
        root = self.tree("0.4.0", CHANGELOG.replace("## Unreleased", "## 0.4.0"))  # the heading without the day does not count
        code, _, err = self.run_main("0.4.0", "--root", str(root))
        self.assertEqual(code, 2)
        self.assertIn("no `## 0.4.0 (date)` section", err)

    def test_this_repository_states_one_version(self):
        stated = release_notes.versions(ROOT)
        self.assertEqual(len(set(stated.values())), 1, stated)
