#!/usr/bin/env python3
"""Run the local delivery guardrails: compile, tests, and secret scan.

Usage:
    .venv/Scripts/python.exe scripts/check.py

The script never reads `.env`; `check_secrets.py` reports paths and pattern
names only, never the matched value.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    "app.py",
    "trendee_rag",
    "scripts",
]


def missing_sources(root: Path, sources: list[str]) -> list[str]:
    """compileall exits 0 for a nonexistent path, so check the list explicitly."""
    return [source for source in sources if not (root / source).exists()]


def run(label: str, command: list[str]) -> bool:
    print(f"\n== {label} ==")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"FAILED: {label} (exit {result.returncode})")
        return False
    print(f"OK: {label}")
    return True


def main() -> int:
    missing = missing_sources(ROOT, SOURCES)
    if missing:
        print("\n== compile ==")
        print("FAILED: compile (missing source paths: " + ", ".join(missing) + ")")
        print("\nCHECK_FAILED: compile")
        return 1

    checks = [
        ("compile", [sys.executable, "-m", "compileall", "-q", *SOURCES]),
        ("tests", [sys.executable, "-m", "pytest", "-q"]),
        ("secret-scan", [sys.executable, "scripts/check_secrets.py"]),
    ]
    failures = [label for label, command in checks if not run(label, command)]
    if failures:
        print("\nCHECK_FAILED: " + ", ".join(failures))
        return 1
    print("\nCHECK_OK: compile, tests, and secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
