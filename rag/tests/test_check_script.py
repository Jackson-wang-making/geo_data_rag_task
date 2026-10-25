"""The delivery check must fail when a source path disappears."""

from __future__ import annotations

import importlib.util
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"
SPEC = importlib.util.spec_from_file_location("delivery_check", CHECK)
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_existing_sources_are_accepted(tmp_path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")

    assert check.missing_sources(tmp_path, ["app.py"]) == []


def test_missing_source_is_reported(tmp_path):
    missing = check.missing_sources(tmp_path, ["app.py", "trendee_rag"])

    assert missing == ["app.py", "trendee_rag"]
