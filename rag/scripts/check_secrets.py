#!/usr/bin/env python3
"""Fail closed when a likely secret appears in workspace text files.

The scanner deliberately never reads `.env` and never prints the matched value:
it reports only the path, line number, and pattern name. Files it cannot inspect
(oversized, unreadable, undecodable, or unexpectedly binary) are reported as
`SECRET_SCAN_INCOMPLETE` with a non-zero exit instead of being silently skipped.
`scripts/check.py` runs this before delivery.
"""

from __future__ import annotations

import argparse
import codecs
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRS = {
    ".git",
    ".omx",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "artifacts",
    "data",
    "dist",
    "node_modules",
    "out",
    "venv",
    "__pycache__",
}
BINARY_SUFFIXES = {
    ".7z",
    ".bin",
    ".db",
    ".docx",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".npy",
    ".npz",
    ".otf",
    ".pdf",
    ".png",
    ".pptx",
    ".pt",
    ".pyc",
    ".rar",
    ".safetensors",
    ".sqlite",
    ".tar",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".zip",
}
MAX_BYTES = 2_000_000

# Keep these patterns narrow enough to avoid blocking on prose, but broad enough
# to catch the credential shapes used by common providers. A placeholder such as
# `<your-api-key-here>` is ignored rather than treated as a real secret.
PATTERNS = (
    ("openai_like_key", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{16,})\b")),
    (
        "generic_api_key",
        re.compile(
            r"(?i)\b(?:[A-Za-z0-9]+[_-])*"
            r"(?:api[_-]?key|apikey|access[_-]?token|secret[_-]?key)"
            r"\b\s*[:=]\s*['\"]?([A-Za-z0-9._~+/=-]{16,})"
        ),
    ),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("google_api_key", re.compile(r"\b(AIza[0-9A-Za-z_-]{30,})\b")),
    ("aws_access_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
)
_PLACEHOLDER = re.compile(
    r"(?i)^(?:your|my|example|sample|placeholder|changeme|replace|dummy|fake|test|none|null|xxx|\.\.\.)"
    r"|^<[^>]*>$|^\$\{[^}]*\}$"
)


def _is_excluded_file(name: str) -> bool:
    if name == "check_secrets.py":
        return True
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


def _is_reparse(path: Path) -> bool:
    """Symlinks and Windows junctions must not pull in files outside the root."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def iter_text_files(root: Path, issues: list[tuple[str, int, str]]):
    """Yield candidate text files; prune excluded directories before descent."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            if name in EXCLUDED_DIRS:
                continue
            directory = base / name
            if _is_reparse(directory):
                issues.append((directory.relative_to(root).as_posix(), 0, "symlink_directory_skipped"))
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if _is_excluded_file(name):
                continue
            if _is_reparse(path):
                issues.append((relative, 0, "symlink_file_skipped"))
                continue
            if path.suffix.lower() in BINARY_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                issues.append((relative, 0, "unreadable"))
                continue
            if size > MAX_BYTES:
                issues.append((relative, 0, "too_large"))
                continue
            yield path


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("NUL bytes in a text file")
    return text


def find_secrets(root: Path):
    findings: list[tuple[str, int, str]] = []
    issues: list[tuple[str, int, str]] = []
    for path in iter_text_files(root, issues):
        relative = path.relative_to(root).as_posix()
        try:
            text = _read_text(path)
        except UnicodeDecodeError:
            issues.append((relative, 0, "undecodable"))
            continue
        except OSError:
            issues.append((relative, 0, "unreadable"))
            continue
        except ValueError:
            issues.append((relative, 0, "binary_content"))
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                if _PLACEHOLDER.search(match.group(1)):
                    continue
                findings.append((relative, line_number, name))
                break
    return findings, issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="workspace root to scan (default: repository root)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"SECRET_SCAN_ERROR: not a directory: {root}")
        return 2

    findings, issues = find_secrets(root)
    if findings:
        print(f"SECRET_SCAN_FOUND: {len(findings)} likely secret(s)")
        for path, line_number, name in findings:
            # Do not print the matching line or value.
            print(f"  {path}:{line_number} [{name}]")
    if issues:
        print(f"SECRET_SCAN_INCOMPLETE: {len(issues)} file(s) could not be inspected")
        for path, line_number, name in issues:
            print(f"  {path}:{line_number} [{name}]")
    if findings:
        return 1
    if issues:
        return 2
    print(f"SECRET_SCAN_OK: no likely secrets in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
