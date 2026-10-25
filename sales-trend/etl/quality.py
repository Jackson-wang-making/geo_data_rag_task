"""Pure Python quality and normalization helpers for the XLSX ETL."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any

import pandas as pd

RAW_COLUMNS: tuple[str, ...] = (
    "product_id",
    "title",
    "sales_count",
    "timestamp",
    "user_id",
    "category",
    "source",
)

VALID_SOURCES: frozenset[str] = frozenset(("app", "marketplace", "website"))

# Acceptance contract for the supplied sample workbook.
EXPECTED_SAMPLE_METRICS: dict[str, Any] = {
    "raw_count": 300,
    "accepted_count": 288,
    "explicit_count": 119,
    "explicit_sales": 1117,
    "explicit_product_count": 12,
    "platform_sales": {"app": 368, "marketplace": 372, "website": 377},
}


@dataclass(frozen=True)
class QualityMetrics:
    raw_count: int
    duplicate_count: int
    distinct_count: int
    rejected_count: int
    accepted_count: int
    explicit_count: int
    explicit_sales: int
    explicit_product_count: int
    platform_sales: dict[str, int]
    reject_reasons: dict[str, int]
    min_timestamp: datetime | None
    max_timestamp: datetime | None
    min_business_date: date | None
    max_business_date: date | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_count": self.raw_count,
            "duplicate_count": self.duplicate_count,
            "distinct_count": self.distinct_count,
            "rejected_count": self.rejected_count,
            "accepted_count": self.accepted_count,
            "explicit_count": self.explicit_count,
            "explicit_sales": self.explicit_sales,
            "explicit_product_count": self.explicit_product_count,
            "platform_sales": dict(sorted(self.platform_sales.items())),
            "reject_reasons": dict(sorted(self.reject_reasons.items())),
            "min_timestamp": self.min_timestamp.isoformat() if self.min_timestamp else None,
            "max_timestamp": self.max_timestamp.isoformat() if self.max_timestamp else None,
            "min_business_date": (
                self.min_business_date.isoformat() if self.min_business_date else None
            ),
            "max_business_date": (
                self.max_business_date.isoformat() if self.max_business_date else None
            ),
        }


@dataclass(frozen=True)
class PreparedSales:
    """Validated, de-duplicated rows plus batch quality metrics."""

    accepted: pd.DataFrame
    metrics: QualityMetrics


def normalize_text(value: Any) -> str:
    """Lowercase, remove apostrophes, and collapse non-alphanumerics to spaces."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).lower().replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: Any) -> str:
    """Return the token-sorted title representation used by PostgreSQL."""
    tokens = normalize_text(value).split()
    return " ".join(sorted(tokens))


def is_explicit_maxi_dress(title: Any, category: Any) -> bool:
    """Apply the explicit-only maxi dress rule."""
    if normalize_text(category) != "dress":
        return False
    tokens = set(normalize_text(title).split())
    return "maxi" in tokens and "dress" in tokens


def _text_series(series: pd.Series) -> pd.Series:
    return series.where(series.notna(), "").astype(str).str.strip()


def assess_quality(raw: pd.DataFrame) -> PreparedSales:
    """Validate source rows and calculate the batch quality contract.

    Duplicate metrics are based on the exact seven source fields. Rejection
    metrics are calculated after exact de-duplication so every distinct row is
    counted once.
    """
    missing = [column for column in RAW_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"workbook is missing required columns: {missing}")

    frame = raw.loc[:, list(RAW_COLUMNS)].copy()
    raw_count = len(frame)
    distinct = frame.drop_duplicates(subset=list(RAW_COLUMNS), keep="first").copy()
    duplicate_count = raw_count - len(distinct)

    reasons: list[list[str]] = [[] for _ in range(len(distinct))]

    def add_reason(mask: pd.Series, reason: str) -> None:
        for position in mask.to_numpy().nonzero()[0]:
            reasons[int(position)].append(reason)

    product_numeric = pd.to_numeric(distinct["product_id"], errors="coerce")
    add_reason(
        product_numeric.isna() | ((product_numeric % 1) != 0),
        "invalid_product_id",
    )

    title_text = _text_series(distinct["title"])
    add_reason(title_text.eq(""), "empty_title")

    sales_numeric = pd.to_numeric(distinct["sales_count"], errors="coerce")
    add_reason(
        sales_numeric.isna()
        | ((sales_numeric % 1) != 0)
        | (sales_numeric < 0),
        "invalid_sales_count",
    )

    timestamps = pd.to_datetime(distinct["timestamp"], errors="coerce")
    add_reason(timestamps.isna(), "invalid_timestamp")

    category_text = _text_series(distinct["category"]).str.lower()
    add_reason(category_text.eq(""), "empty_category")

    source_text = _text_series(distinct["source"]).str.lower()
    add_reason(~source_text.isin(VALID_SOURCES), "invalid_source")

    reject_counter = Counter(
        reason for row_reasons in reasons for reason in row_reasons
    )
    valid_positions = [index for index, row_reasons in enumerate(reasons) if not row_reasons]
    accepted = distinct.iloc[valid_positions].copy()

    if len(accepted):
        accepted["product_id"] = product_numeric.iloc[valid_positions].astype("int64")
        accepted["sales_count"] = sales_numeric.iloc[valid_positions].astype("int64")
        accepted["timestamp"] = timestamps.iloc[valid_positions]
        accepted["category"] = category_text.iloc[valid_positions]
        accepted["source"] = source_text.iloc[valid_positions]
        accepted["title_norm"] = accepted["title"].map(normalize_title)
        accepted["is_maxi_dress"] = [
            is_explicit_maxi_dress(title, category)
            for title, category in zip(accepted["title"], accepted["category"])
        ]
        accepted["business_date"] = accepted["timestamp"].dt.date
    else:
        for column in ("title_norm", "is_maxi_dress", "business_date"):
            accepted[column] = pd.Series(index=accepted.index, dtype="object")

    explicit = accepted.loc[accepted["is_maxi_dress"].fillna(False)]
    platform_sales = {
        str(source): int(amount)
        for source, amount in explicit.groupby("source", dropna=False)["sales_count"].sum().items()
    }

    min_timestamp = (
        accepted["timestamp"].min().to_pydatetime() if len(accepted) else None
    )
    max_timestamp = (
        accepted["timestamp"].max().to_pydatetime() if len(accepted) else None
    )
    min_business_date = (
        min(accepted["business_date"]) if len(accepted) else None
    )
    max_business_date = (
        max(accepted["business_date"]) if len(accepted) else None
    )

    metrics = QualityMetrics(
        raw_count=raw_count,
        duplicate_count=duplicate_count,
        distinct_count=len(distinct),
        rejected_count=len(distinct) - len(accepted),
        accepted_count=len(accepted),
        explicit_count=len(explicit),
        explicit_sales=int(explicit["sales_count"].sum()) if len(explicit) else 0,
        explicit_product_count=int(explicit["product_id"].nunique()) if len(explicit) else 0,
        platform_sales=platform_sales,
        reject_reasons=dict(reject_counter),
        min_timestamp=min_timestamp,
        max_timestamp=max_timestamp,
        min_business_date=min_business_date,
        max_business_date=max_business_date,
    )
    return PreparedSales(accepted=accepted, metrics=metrics)


def verify_sample_metrics(
    metrics: QualityMetrics,
    expected: dict[str, Any] | None = None,
) -> list[str]:
    """Return human-readable mismatches against the supplied sample contract."""
    expected_values = expected or EXPECTED_SAMPLE_METRICS
    actual = metrics.as_dict()
    mismatches: list[str] = []
    for key, expected_value in expected_values.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")
    return mismatches