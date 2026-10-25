from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.normalization import normalize_text, normalize_title
from etl.loader import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKBOOK = PROJECT_ROOT / "data" / "sample_sales.xlsx"


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set; integration test skipped")
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg is not installed; integration test skipped")
    try:
        with psycopg.connect(url, connect_timeout=3):
            return url
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")


@pytest.mark.integration
def test_end_to_end_loader_idempotency_and_api() -> None:
    db_url = _database_url()

    first = load_workbook(
        workbook_path=SAMPLE_WORKBOOK,
        database_url=db_url,
        verify_sample=True,
    )
    assert first["quality"]["raw_count"] == 300
    assert first["quality"]["duplicate_count"] == 12
    assert first["quality"]["accepted_count"] == 288
    assert first["quality"]["explicit_count"] == 119
    assert first["quality"]["explicit_sales"] == 1117
    assert first["quality"]["explicit_product_count"] == 12
    assert first["quality"]["platform_sales"] == {
        "app": 368,
        "marketplace": 372,
        "website": 377,
    }
    assert first["refresh"]["sales_count"] == 1117

    second = load_workbook(
        workbook_path=SAMPLE_WORKBOOK,
        database_url=db_url,
        verify_sample=True,
    )
    assert second["raw_rows_inserted"] == 0
    assert second["quality"]["explicit_sales"] == 1117
    assert second["refresh"]["sales_count"] == 1117

    client = TestClient(create_app())
    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "platform": ["app", "website"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["total_sales"] == 42
    assert payload["data"]["totals"] == [
        {"platform": "app", "sales_count": 23},
        {"platform": "website", "sales_count": 19},
    ]
    assert payload["meta"]["coverage"]["min_date"] == "2024-01-01"
    assert payload["meta"]["coverage"]["max_date"] == "2024-03-13"

    titles = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "platform": ["app", "website"],
            "include_titles": "true",
            "page_size": 10,
        },
    )
    assert titles.status_code == 200
    assert titles.json()["data"]["titles"]
    assert all(item["title"] for item in titles.json()["data"]["titles"])

    invalid = client.get(
        "/v1/sales/trends",
        params={"start_date": "2024-01-01", "end_date": "2024-01-03", "category": "long dress"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "UNSUPPORTED_CATEGORY"


@pytest.mark.integration
def test_coverage_is_precomputed() -> None:
    db_url = _database_url()
    import psycopg

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT min_date, max_date "
                "FROM app.coverage_meta WHERE scope = 'raw_source'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0].isoformat() == "2024-01-01"
            assert row[1].isoformat() == "2024-03-13"


@pytest.mark.integration
def test_python_and_sql_normalization_are_in_parity() -> None:
    db_url = _database_url()
    import psycopg

    fixtures = [
        "MAXI DRESS WHITE",
        "Women's Maxi-Dress Floral",
        "Maxi Denim Dress",
        "Maxi Skirt",
        "Elegant Long Dress",
    ]
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for fixture in fixtures:
                cur.execute(
                    "SELECT std.normalize_text(%s), std.normalize_title(%s)",
                    (fixture, fixture),
                )
                sql_text, sql_title = cur.fetchone()
                assert sql_text == normalize_text(fixture)
                assert sql_title == normalize_title(fixture)
