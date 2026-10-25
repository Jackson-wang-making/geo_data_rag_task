from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd
import pytest

from etl.loader import read_sales_workbook
from etl.quality import (
    assess_quality,
    is_explicit_maxi_dress,
    normalize_text,
    normalize_title,
    verify_sample_metrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKBOOK = PROJECT_ROOT / "data" / "sample_sales.xlsx"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MAXI DRESS WHITE", "maxi dress white"),
        ("Women's Maxi-Dress Floral", "womens maxi dress floral"),
        ("  denim---maxi  dress  ", "denim maxi dress"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_title_sorts_tokens() -> None:
    assert normalize_title("MAXI DRESS WHITE") == "dress maxi white"
    assert normalize_title("Women's Maxi-Dress Floral") == "dress floral maxi womens"


@pytest.mark.parametrize(
    ("title", "category", "expected"),
    [
        ("MAXI DRESS WHITE", "dress", True),
        ("Women's Maxi-Dress Floral", " Dress ", True),
        ("Elegant Long Dress", "dress", False),
        ("Maxi Skirt", "skirt", False),
        ("Summer Mini Dress", "dress", False),
        ("T-shirt Dress", "shirt", False),
    ],
)
def test_explicit_only_maxi_dress_rule(
    title: str,
    category: str,
    expected: bool,
) -> None:
    assert is_explicit_maxi_dress(title, category) is expected


def test_sample_workbook_quality_contract() -> None:
    raw = read_sales_workbook(SAMPLE_WORKBOOK)
    prepared = assess_quality(raw)

    assert prepared.metrics.raw_count == 300
    assert prepared.metrics.duplicate_count == 12
    assert prepared.metrics.distinct_count == 288
    assert prepared.metrics.rejected_count == 0
    assert prepared.metrics.accepted_count == 288
    assert prepared.metrics.explicit_count == 119
    assert prepared.metrics.explicit_sales == 1117
    assert prepared.metrics.explicit_product_count == 12
    assert prepared.metrics.platform_sales == {
        "app": 368,
        "marketplace": 372,
        "website": 377,
    }
    assert verify_sample_metrics(prepared.metrics) == []


def test_chinese_workbook_path_is_supported(tmp_path: Path) -> None:
    chinese_path = tmp_path / "样例销售数据.xlsx"
    shutil.copyfile(SAMPLE_WORKBOOK, chinese_path)

    raw = read_sales_workbook(chinese_path)

    assert len(raw) == 300
    assert list(raw.columns) == [
        "product_id",
        "title",
        "sales_count",
        "timestamp",
        "user_id",
        "category",
        "source",
    ]


def test_quality_rejects_invalid_rows_after_exact_deduplication() -> None:
    raw = pd.DataFrame(
        [
            [2001, "Maxi Dress Floral", 5, "2024-01-01 07:00:00", "U1", "dress", "app"],
            [2001, "Maxi Dress Floral", 5, "2024-01-01 07:00:00", "U1", "dress", "app"],
            [2002, "Elegant Long Dress", 3, "2024-01-02 08:00:00", "U2", "dress", "website"],
            [2003, "Maxi Dress Black", -1, "2024-01-03 09:00:00", "U3", "dress", "app"],
            [2004, "Maxi Skirt", 2, "2024-01-04 10:00:00", "U4", "skirt", "unknown"],
        ],
        columns=[
            "product_id",
            "title",
            "sales_count",
            "timestamp",
            "user_id",
            "category",
            "source",
        ],
    )

    prepared = assess_quality(raw)

    assert prepared.metrics.raw_count == 5
    assert prepared.metrics.duplicate_count == 1
    assert prepared.metrics.distinct_count == 4
    assert prepared.metrics.rejected_count == 2
    assert prepared.metrics.accepted_count == 2
    assert prepared.metrics.explicit_count == 1
    assert prepared.metrics.explicit_sales == 5
    assert prepared.metrics.platform_sales == {"app": 5}
    assert prepared.metrics.reject_reasons == {
        "invalid_sales_count": 1,
        "invalid_source": 1,
    }


def test_quality_rejects_titles_with_empty_normalized_form() -> None:
    raw = pd.DataFrame(
        [
            [3001, "Maxi Dress Floral", 5, "2024-01-01 07:00:00", "U1", "dress", "app"],
            [3002, "优雅连衣裙", 3, "2024-01-02 08:00:00", "U2", "dress", "website"],
        ],
        columns=[
            "product_id",
            "title",
            "sales_count",
            "timestamp",
            "user_id",
            "category",
            "source",
        ],
    )

    prepared = assess_quality(raw)

    assert prepared.metrics.raw_count == 2
    assert prepared.metrics.accepted_count == 1
    assert prepared.metrics.rejected_count == 1
    assert prepared.metrics.reject_reasons == {"empty_title_norm": 1}
    assert list(prepared.accepted["title"]) == ["Maxi Dress Floral"]