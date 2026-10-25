from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import CoverageRecord, SeriesRecord, TitleRecord


def _bucket(day: date, granularity: str) -> date:
    if granularity == "day":
        return day
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


class FakeSalesTrendRepository:
    def __init__(self) -> None:
        self.series_records = [
            SeriesRecord(date(2024, 1, 1), "app", 10),
            SeriesRecord(date(2024, 1, 1), "marketplace", 4),
            SeriesRecord(date(2024, 1, 1), "website", 19),
            SeriesRecord(date(2024, 1, 2), "app", 13),
        ]
        self.title_records = [
            TitleRecord(date(2024, 1, 1), "app", 101, "dress maxi white", 6),
            TitleRecord(date(2024, 1, 1), "app", 102, "dress maxi black", 4),
            TitleRecord(date(2024, 1, 1), "website", 201, "dress maxi blue", 19),
        ]
        self.calls: list[tuple] = []

    def get_series(self, start_date, end_date, platforms, granularity):
        self.calls.append(
            ("series", start_date, end_date, list(platforms), granularity)
        )
        grouped: dict[tuple[date, str], int] = defaultdict(int)
        for record in self.series_records:
            if (
                start_date <= record.date <= end_date
                and record.platform in platforms
            ):
                grouped[(_bucket(record.date, granularity), record.platform)] += (
                    record.sales_count
                )
        return [
            SeriesRecord(bucket, platform, sales_count)
            for (bucket, platform), sales_count in sorted(grouped.items())
        ]

    def get_titles_page(
        self, start_date, end_date, platforms, granularity, limit, offset
    ):
        self.calls.append(
            (
                "titles",
                start_date,
                end_date,
                list(platforms),
                granularity,
                limit,
                offset,
            )
        )
        grouped: dict[tuple[date, str, int, str], int] = defaultdict(int)
        for record in self.title_records:
            if (
                start_date <= record.date <= end_date
                and record.platform in platforms
            ):
                key = (
                    _bucket(record.date, granularity),
                    record.platform,
                    record.product_id,
                    record.title,
                )
                grouped[key] += record.sales_count
        rows = [
            TitleRecord(bucket, platform, product_id, title, sales_count)
            for (bucket, platform, product_id, title), sales_count in sorted(
                grouped.items()
            )
        ]
        return rows[offset : offset + limit], len(rows)

    def get_coverage(self):
        return CoverageRecord(
            min_date=min(record.date for record in self.series_records),
            max_date=max(record.date for record in self.series_records),
        )


@pytest.fixture
def api() -> tuple[TestClient, FakeSalesTrendRepository]:
    repository = FakeSalesTrendRepository()
    client = TestClient(create_app(repository=repository))
    return client, repository


def test_defaults_fill_all_dates_and_platforms_without_title_null(api):
    client, repository = api
    response = client.get(
        "/v1/sales/trends",
        params={"start_date": "2024-01-01", "end_date": "2024-01-03"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"]["category"] == "maxi dress"
    assert payload["query"]["platforms"] == ["website", "app", "marketplace"]
    assert payload["query"]["granularity"] == "day"
    assert payload["query"]["resolved_granularity"] == "day"
    assert len(payload["data"]["series"]) == 9
    assert payload["data"]["total_sales"] == 46
    assert payload["data"]["totals"] == [
        {"platform": "website", "sales_count": 19},
        {"platform": "app", "sales_count": 23},
        {"platform": "marketplace", "sales_count": 4},
    ]
    assert "titles" not in payload["data"]
    assert "pagination" not in payload["data"]
    assert all("title" not in point for point in payload["data"]["series"])
    zero_point = next(
        point
        for point in payload["data"]["series"]
        if point["date"] == "2024-01-03" and point["platform"] == "app"
    )
    assert zero_point["sales_count"] == 0
    assert repository.calls[0] == (
        "series",
        date(2024, 1, 1),
        date(2024, 1, 3),
        ["website", "app", "marketplace"],
        "day",
    )


def test_fill_missing_false_returns_only_observed_date_platform_rows(api):
    client, _ = api
    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "platform": "app",
            "fill_missing": "false",
        },
    )

    assert response.status_code == 200
    points = response.json()["data"]["series"]
    assert [(point["date"], point["sales_count"]) for point in points] == [
        ("2024-01-01", 10),
        ("2024-01-02", 13),
    ]


def test_category_and_platforms_are_normalized_and_deduplicated(api):
    client, _ = api
    response = client.get(
        "/v1/sales/trends",
        params=[
            ("start_date", "2024-01-01"),
            ("end_date", "2024-01-01"),
            ("category", "MAXI--DRESS"),
            ("platform", " APP "),
            ("platform", "website"),
            ("platform", "app"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"]["category"] == "maxi dress"
    assert payload["query"]["platforms"] == ["app", "website"]
    assert len(payload["data"]["series"]) == 2


def test_week_and_month_granularity_group_calendar_periods(api):
    client, _ = api
    week_response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "platform": "app",
            "granularity": "week",
        },
    )
    month_response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-02-29",
            "platform": "app",
            "granularity": "month",
        },
    )

    assert week_response.status_code == 200
    assert month_response.status_code == 200
    assert week_response.json()["query"]["resolved_granularity"] == "week"
    assert week_response.json()["data"]["series"][0]["date"] == "2024-01-01"
    assert week_response.json()["data"]["series"][-1]["date"] == "2024-01-29"
    assert [row["date"] for row in month_response.json()["data"]["series"]] == [
        "2024-01-01",
        "2024-02-01",
    ]


def test_auto_switches_away_from_day_for_long_ranges(api):
    client, _ = api
    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2025-01-01",
            "platform": "app",
            "granularity": "auto",
        },
    )

    assert response.status_code == 200
    assert response.json()["query"]["granularity"] == "auto"
    assert response.json()["query"]["resolved_granularity"] == "week"


def test_titles_are_paginated_and_do_not_leak_into_series(api):
    client, repository = api
    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "include_titles": "true",
            "page": 2,
            "page_size": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["data"]["titles"]) == 1
    assert payload["data"]["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total": 3,
        "has_more": False,
    }
    assert all(point["title"] for point in payload["data"]["titles"])
    assert all("title" not in point for point in payload["data"]["series"])
    assert repository.calls[1] == (
        "titles",
        date(2024, 1, 1),
        date(2024, 1, 2),
        ["website", "app", "marketplace"],
        "day",
        2,
        2,
    )


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        (
            {"start_date": "2024-01-01", "end_date": "2024-01-02", "category": "long dress"},
            400,
            "UNSUPPORTED_CATEGORY",
        ),
        (
            {"start_date": "2024-01-01", "end_date": "2024-01-02", "platform": "shop"},
            400,
            "INVALID_PLATFORM",
        ),
        (
            {"start_date": "2024-01-01", "end_date": "2024-01-02", "timezone": "UTC"},
            400,
            "INVALID_TIMEZONE",
        ),
        (
            {"start_date": "2024/01/01", "end_date": "2024-01-02"},
            400,
            "INVALID_DATE_FORMAT",
        ),
        (
            {"start_date": "2024-01-03", "end_date": "2024-01-02"},
            400,
            "INVALID_DATE_RANGE",
        ),
        (
            {
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
                "include_titles": "true",
                "page_size": 501,
            },
            422,
            "RANGE_TOO_LARGE",
        ),
        (
            {"start_date": "2024-01-01", "end_date": "2024-01-02", "granularity": "year"},
            400,
            "INVALID_GRANULARITY",
        ),
    ],
)
def test_contract_errors_use_coherent_envelope(api, params, status, code):
    client, _ = api
    response = client.get("/v1/sales/trends", params=params)

    assert response.status_code == status
    payload = response.json()
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]
    assert "detail" not in payload


def test_day_granularity_accepts_long_ranges(api):
    client, _ = api
    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2025-01-01",
            "granularity": "day",
            "platform": "app",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"]["resolved_granularity"] == "day"
    assert len(payload["data"]["series"]) == 367  # 2024 is a leap year


def test_day_granularity_rejects_oversized_points(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr("app.services.sales_trends.MAX_SERIES_POINTS", 10)

    response = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "granularity": "day",
            "platform": "app",
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "RANGE_TOO_LARGE"
    assert payload["error"]["details"]["max_points"] == 10
    assert payload["error"]["details"]["requested_points"] == 31


def test_week_and_month_granularity_enforce_points_guard(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr("app.services.sales_trends.MAX_SERIES_POINTS", 10)

    week = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-02-01",
            "granularity": "week",
        },
    )
    month = client.get(
        "/v1/sales/trends",
        params={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "granularity": "month",
        },
    )

    assert week.status_code == 422
    assert week.json()["error"]["code"] == "RANGE_TOO_LARGE"
    assert month.status_code == 422
    assert month.json()["error"]["code"] == "RANGE_TOO_LARGE"
