"""The release notes of one version, after checking that it is the version the code states.

`python tools/release_notes.py 0.3.0 --out notes.md` writes the `## 0.3.0 (date)` section of CHANGELOG.md followed by
the install line, and fails with the reason when `tessri.__version__` or the `version` in pyproject.toml is another
number or when the changelog has no dated section for it. The release workflow runs it before anything is built, so a
tag that does not match the code publishes nothing."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(Exception):
    pass


def versions(root: Path) -> dict[str, str]:
    """The version each place in the code states, by place."""
    init = (root / "tessri" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    with (root / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f).get("project", {})
    return {"tessri/__init__.py": found.group(1) if found else "", "pyproject.toml": str(project.get("version", ""))}


def section(changelog: str, version: str) -> str:
    """The body of the `## version (date)` section, up to the next heading of that level."""
    heading = re.compile(rf"^## {re.escape(version)} \(\d{{4}}-\d{{2}}-\d{{2}}\)[ \t]*$", re.M)
    found = heading.search(changelog)
    if not found:
        raise ReleaseError(f"CHANGELOG.md has no `## {version} (date)` section: head the version's section with the number and the day it is tagged")
    rest = changelog[found.end() :]
    following = re.search(r"^## ", rest, re.M)
    body = rest[: following.start()] if following else rest
    if not body.strip():
        raise ReleaseError(f"the `## {version}` section of CHANGELOG.md is empty")
    return body.strip() + "\n"


def notes(root: Path, version: str) -> str:
    """The changelog section of `version` and the install line, once the code is known to state that version."""
    stated = versions(root)
    wrong = {place: v for place, v in stated.items() if v != version}
    if wrong:
        where = ", ".join(f"{place} says {v or 'nothing'}" for place, v in wrong.items())
        raise ReleaseError(f"the tag says {version} but {where}: bump the version in the code first")
    body = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    return f"{body}\n```\npip install tessri=={version}\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The release notes of one version, from CHANGELOG.md, after checking that the code states the same version.")
    parser.add_argument("version", help="the version being released: the tag without its v")
    parser.add_argument("--out", help="write the notes to this file instead of printing them")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        text = notes(Path(args.root), args.version)
    except (ReleaseError, OSError) as exc:
        print(f"release_notes: {exc}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
