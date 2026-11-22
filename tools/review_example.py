"""Build the small review example used by the site and README, in an isolated temporary repository.

    python tools/review_example.py --out /tmp/tessri-example

The fixture's two unittest cases really run. They exercise billing, not the unchanged reporting importer.
This is a teaching example, not a production incident or evidence that reviews are faster.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tessri import brief, briefhtml, config  # noqa: E402

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc).timestamp()
TEST_CASES = 2
BASE = {
    ".gitignore": "__pycache__/\n",
    "billing/__init__.py": "",
    "billing/invoices.py": "from util.money import cents\n\n\ndef total(value):\n    return cents(value)\n",
    "billing/tax.py": "def rate():\n    return 0.2\n",
    "reports/__init__.py": "",
    "reports/summary.py": "from util.money import cents\n\n\ndef summarize(value):\n    return cents(value)\n",
    "util/__init__.py": "",
    "util/money.py": "def cents(value):\n    return round(value * 100)\n",
    "svc/main.go": "package main\n\nfunc main() {}\n",
    "tests/test_invoices.py": "import unittest\nfrom billing import invoices\n\n\nclass InvoicesTest(unittest.TestCase):\n    def test_total(self):\n        self.assertEqual(invoices.total(3), 300)\n",
}


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")


def _git(root: Path, *args: str, day: str | None = None, author: str = "Alice Adams") -> None:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
    if day:
        env.update(GIT_AUTHOR_DATE=day, GIT_COMMITTER_DATE=day, GIT_AUTHOR_NAME=author, GIT_COMMITTER_NAME=author,
                   GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_EMAIL="fixture@example.invalid")
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={root / '.git' / 'disabled-hooks'}",
                    *args], cwd=root, env=env, check=True, capture_output=True)


def generate() -> dict:
    """Return an actual brief, with machine-local temporary paths normalized for publication."""
    with tempfile.TemporaryDirectory(prefix="tessri-example-") as temp:
        root = Path(temp) / "demo-brief"
        root.mkdir()
        old_cache = os.environ.get("TESSRI_CACHE_DIR")
        os.environ["TESSRI_CACHE_DIR"] = str(Path(temp) / "cache")
        try:
            _git(root, "init", "-q", "-b", "main")
            _git(root, "config", "user.name", "Dana Doe")
            _git(root, "config", "user.email", "fixture@example.invalid")
            _git(root, "config", "core.autocrlf", "false")
            _write(root, BASE)
            _git(root, "add", ".")
            _git(root, "commit", "-qm", "feat: billing and reporting", day="2025-10-02T12:00:00+0000")
            _write(root, {"legacy/rates.py": "def old_rate():\n    return 0.2\n"})
            _git(root, "add", ".")
            _git(root, "commit", "-qm", "feat: legacy rate", day="2026-01-10T12:00:00+0000", author="Bob Brown")
            for day, text in [("2026-10-11T12:00:00+0000", "# fixed rounding\n"), ("2026-11-01T12:00:00+0000", "# kept rate explicit\n")]:
                _write(root, {"billing/tax.py": BASE["billing/tax.py"] + text})
                _git(root, "add", ".")
                _git(root, "commit", "-qm", "fix: tax rate", day=day)
            _git(root, "checkout", "-qb", "refactor")
            _write(root, {
                "billing/invoices.py": "def cents(value):\n    return round(value * 100)\n\n\ndef total(value):\n    return cents(value)\n",
                "billing/tax.py": BASE["billing/tax.py"] + "# kept rate explicit\n\n\ndef gross(value):\n    return value * (1 + rate())\n",
                "billing/helpers.py": "def fmt(value):\n    return str(value)\n",
                "legacy/rates.py": "def old_rate():\n    return 0.19\n",
                "svc/main.go": "package main\n\nfunc main() { println(1) }\n",
            })
            (root / "util/money.py").unlink()
            (root / "util/__init__.py").unlink()
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", "refactor: move money into billing", day="2026-11-20T10:00:00+0000", author="Carol Chen")
            tests = BASE["tests/test_invoices.py"].replace("from billing import invoices", "from billing import invoices, tax")
            tests += "\n    def test_gross(self):\n        self.assertEqual(tax.gross(100), 120)\n"
            _write(root, {"tests/test_invoices.py": tests})
            _git(root, "add", ".")
            _git(root, "commit", "-qm", "test: billing totals", day="2026-11-20T11:00:00+0000", author="Carol Chen")
            run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True, encoding="utf-8")
            if run.returncode or f"Ran {TEST_CASES} tests" not in run.stderr:
                raise RuntimeError("The teaching fixture's checks did not pass: " + run.stderr)
            _write(root, {"tests/test_invoices.py": tests + "\n# An uncommitted annotation; HEAD does not identify these contents.\n"})
            result = brief.compute(root, config.load(root), "main", now=NOW,
                                   ran=[f"python -m unittest discover -s tests: {TEST_CASES} passed (exit 0), run by the example generator"])
            for obj in (result, result["triage"], result["check"]):
                obj["meta"]["repo"]["root"] = "<worked-example>/demo-brief"
            return result
        finally:
            if old_cache is None:
                os.environ.pop("TESSRI_CACHE_DIR", None)
            else:
                os.environ["TESSRI_CACHE_DIR"] = old_cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="a new or empty directory for the example")
    args = parser.parse_args()
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        parser.error("--out must be a new or empty directory")
    result = generate()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in {
        "index.html": briefhtml.render(result, example=True),
        "brief.json": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        "brief.md": brief.markdown(result),
    }.items():
        (args.out / name).write_text(text, encoding="utf-8", newline="")
    print(f"Worked example written to {args.out.resolve()}")


if __name__ == "__main__":
    main()
