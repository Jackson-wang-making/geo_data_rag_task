"""Text normalization rules shared by validation and classification.

These functions intentionally mirror std.normalize_text and
std.normalize_title from the database schema. Keeping the Python rule
identical lets the API validate category without opening a database
connection at import time.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """Normalize text exactly as the v1 database rule does."""

    without_apostrophes = (value or "").replace("'", "")
    lowered = without_apostrophes.lower()
    collapsed = _NON_ALNUM.sub(" ", lowered)
    return _WHITESPACE.sub(" ", collapsed).strip()


def normalize_title(value: str | None) -> str:
    """Normalize a title and sort its tokens for stable identity matching."""

    tokens = [token for token in normalize_text(value).split(" ") if token]
    return " ".join(sorted(tokens))


def is_explicit_maxi_dress(title: str | None, category: str | None) -> bool:
    """Apply the explicit maxi + dress title rule.

    long dress and every other synonym are intentionally unsupported.
    """

    if (category or "").strip().lower() != "dress":
        return False
    tokens = set(normalize_text(title).split())
    return {"maxi", "dress"}.issubset(tokens)
