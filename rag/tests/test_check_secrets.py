"""The secret scanner must fail closed without echoing the matched value."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"


def run_scan(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_clean_tree_passes(tmp_path):
    (tmp_path / "README.md").write_text("no credentials here", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 0
    assert "SECRET_SCAN_OK" in result.stdout


def test_likely_key_fails_without_echoing_value(tmp_path):
    fake_key = "sk-" + "a" * 24
    (tmp_path / "config.txt").write_text(f"LLM_API_KEY={fake_key}", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 1
    assert "SECRET_SCAN_FOUND" in result.stdout
    assert "config.txt" in result.stdout
    assert fake_key not in result.stdout
    assert fake_key not in result.stderr


def test_dotenv_is_never_scanned(tmp_path):
    fake_key = "sk-" + "b" * 24
    (tmp_path / ".env").write_text(f"LLM_API_KEY={fake_key}", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 0
    assert fake_key not in result.stdout


def test_utf16_file_is_decoded_and_scanned(tmp_path):
    fake_key = "sk-" + "c" * 24
    (tmp_path / "notes.txt").write_bytes(f"LLM_API_KEY={fake_key}".encode("utf-16"))

    result = run_scan(tmp_path)

    assert result.returncode == 1
    assert "SECRET_SCAN_FOUND" in result.stdout
    assert "notes.txt" in result.stdout
    assert fake_key not in result.stdout


def test_oversized_text_file_fails_closed(tmp_path):
    fake_key = "sk-" + "d" * 24
    (tmp_path / "large.txt").write_text("x" * 2_000_001 + f"\nLLM_API_KEY={fake_key}\n", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 2
    assert "SECRET_SCAN_INCOMPLETE" in result.stdout
    assert "large.txt" in result.stdout
    assert fake_key not in result.stdout


def test_generic_api_key_assignment_is_detected(tmp_path):
    fake_key = "q" * 24
    (tmp_path / "config.yaml").write_text("api_key: " + fake_key + "\n", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 1
    assert "SECRET_SCAN_FOUND" in result.stdout
    assert "config.yaml" in result.stdout
    assert fake_key not in result.stdout


def test_documented_placeholder_is_not_a_secret(tmp_path):
    (tmp_path / "config.yaml").write_text("api_key: your-api-key-here\n", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 0
    assert "SECRET_SCAN_OK" in result.stdout
