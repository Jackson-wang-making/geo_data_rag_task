from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.normalization import (
    is_explicit_maxi_dress,
    normalize_text,
    normalize_title,
)
from app.repository import TABLE_NAME


def test_text_normalization_matches_the_explicit_v1_rule():
    assert normalize_text(" MAXI--DRESS ") == "maxi dress"
    assert normalize_text("Women's Maxi-Dress Floral") == (
        "womens maxi dress floral"
    )
    assert normalize_title("Women's Maxi-Dress Floral") == (
        "dress floral maxi womens"
    )
    assert normalize_title("Maxi Denim Dress") == normalize_title(
        "Denim Maxi Dress"
    )
    assert is_explicit_maxi_dress("MAXI DRESS White", "dress")
    assert is_explicit_maxi_dress("Women's Maxi-Dress", "DRESS")
    assert not is_explicit_maxi_dress("Elegant Long Dress", "dress")
    assert not is_explicit_maxi_dress("Maxi Skirt", "skirt")


def test_repository_targets_application_table_and_limits_titles():
    assert TABLE_NAME == "app.maxi_dress_daily"

    from app import repository

    source = __import__("inspect").getsource(repository)
    assert "app.maxi_dress_daily" in source
    assert "stat_date BETWEEN %s AND %s" in source
    assert "source = ANY(%s)" in source
    assert "LIMIT %s OFFSET %s" in source
    assert "title IS NOT NULL" in source


def test_openapi_contract_is_available_without_database_connection():
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert "/v1/sales/trends" in spec["paths"]
    parameter_names = {
        parameter["name"]
        for parameter in spec["paths"]["/v1/sales/trends"]["get"]["parameters"]
    }
    assert {
        "category",
        "start_date",
        "end_date",
        "platform",
        "granularity",
        "include_titles",
        "page_size",
        "fill_missing",
        "timezone",
    } <= parameter_names

    series_schema = spec["components"]["schemas"]["SeriesPoint"]
    assert set(series_schema["properties"]) == {
        "date",
        "platform",
        "sales_count",
    }
    assert "title" not in series_schema["properties"]


def test_missing_parameters_use_error_envelope_without_opening_database():
    client = TestClient(create_app())
    response = client.get("/v1/sales/trends")

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "INVALID_QUERY"
    assert payload["error"]["details"]["errors"]


def test_get_coverage_reads_precomputed_table_not_raw():
    from app import repository

    source = __import__("inspect").getsource(repository)
    assert "FROM app.coverage_meta" in source
    assert "FROM raw.sales_data" not in source


def test_repository_uses_a_lazy_connection_pool():
    import pytest

    from app import repository
    from app.errors import RepositoryUnavailableError
    from app.repository import PostgresSalesTrendRepository

    source = __import__("inspect").getsource(repository)
    assert "from psycopg_pool import ConnectionPool" in source
    assert "ConnectionPool(" in source
    assert "min_size=1" in source
    assert "max_size=10" in source
    assert "timeout=5" in source
    assert "with self._pool().connection() as connection" in source

    repo = PostgresSalesTrendRepository(None)
    assert repo._pool_obj is None  # construction stays side-effect free
    with pytest.raises(RepositoryUnavailableError):
        repo._pool()
