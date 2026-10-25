"""Sales trend validation, aggregation, filling, and response assembly."""

from __future__ import annotations

import calendar
import os
import re
from collections import defaultdict
from datetime import date as Date
from datetime import timedelta

from app.errors import DomainError
from app.models import (
    Coverage,
    Pagination,
    PlatformTotal,
    SeriesPoint,
    TitlePoint,
    TrendData,
    TrendMeta,
    TrendQueryEcho,
    TrendResponse,
)
from app.normalization import normalize_text
from app.repository import SalesTrendRepository

SUPPORTED_PLATFORMS = ("website", "app", "marketplace")
DEFAULT_PLATFORMS = list(SUPPORTED_PLATFORMS)
SUPPORTED_GRANULARITIES = frozenset({"day", "week", "month", "auto"})
ALLOWED_TIMEZONE = "Asia/Shanghai"
DAY_MAX_DAYS = 366
AUTO_WEEK_MAX_DAYS = DAY_MAX_DAYS * 4
MAX_SERIES_POINTS = int(os.getenv("MAX_SERIES_POINTS", "100000"))
PAGE_SIZE_MAX = 500
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str, field: str) -> Date:
    if not _ISO_DATE.fullmatch(value):
        raise DomainError(
            400,
            "INVALID_DATE_FORMAT",
            f"{field} must use YYYY-MM-DD format",
            {"field": field, "value": value},
        )
    try:
        return Date.fromisoformat(value)
    except ValueError as exc:
        raise DomainError(
            400,
            "INVALID_DATE_FORMAT",
            f"{field} must be a valid calendar date",
            {"field": field, "value": value},
        ) from exc


def _normalize_platforms(values: list[str] | None) -> list[str]:
    requested = values if values else DEFAULT_PLATFORMS
    normalized: list[str] = []
    seen: set[str] = set()
    for value in requested:
        platform = value.strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise DomainError(
                400,
                "INVALID_PLATFORM",
                f"Unsupported platform: {value}",
                {"platform": value, "allowed": list(SUPPORTED_PLATFORMS)},
            )
        if platform not in seen:
            seen.add(platform)
            normalized.append(platform)
    return normalized


def _resolve_granularity(
    requested: str, start_date: Date, end_date: Date, platform_count: int
) -> str:
    granularity = requested.strip().lower()
    if granularity not in SUPPORTED_GRANULARITIES:
        raise DomainError(
            400,
            "INVALID_GRANULARITY",
            f"Unsupported granularity: {requested}",
            {"allowed": ["day", "week", "month", "auto"]},
        )

    day_count = (end_date - start_date).days + 1
    if granularity == "auto":
        if day_count <= DAY_MAX_DAYS:
            return "day"
        if day_count <= AUTO_WEEK_MAX_DAYS:
            return "week"
        return "month"

    if granularity == "day":
        requested_points = day_count * platform_count
        if requested_points > MAX_SERIES_POINTS:
            raise DomainError(
                422,
                "RANGE_TOO_LARGE",
                "day granularity would return too many points",
                {
                    "max_points": MAX_SERIES_POINTS,
                    "requested_points": requested_points,
                },
            )
    return granularity


def _iter_periods(start_date: Date, end_date: Date, granularity: str):
    if granularity == "day":
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)
        return

    if granularity == "week":
        current = start_date - timedelta(days=start_date.weekday())
        step = timedelta(days=7)
        while current <= end_date:
            yield current
            current += step
        return

    current = start_date.replace(day=1)
    while current <= end_date:
        yield current
        if current.month == 12:
            current = Date(current.year + 1, 1, 1)
        else:
            current = Date(current.year, current.month + 1, 1)


def _period_key(value: Date, granularity: str) -> Date:
    if granularity == "day":
        return value
    if granularity == "week":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _is_complete_quarter(min_date: Date | None, max_date: Date | None) -> bool:
    if min_date is None or max_date is None:
        return False
    starts = (1, 4, 7, 10)
    for year in range(min_date.year, max_date.year + 1):
        for month in starts:
            quarter_start = Date(year, month, 1)
            last_month = month + 2
            quarter_end = Date(
                year, last_month, calendar.monthrange(year, last_month)[1]
            )
            if min_date <= quarter_start and max_date >= quarter_end:
                return True
    return False


class SalesTrendService:
    def __init__(self, repository: SalesTrendRepository) -> None:
        self.repository = repository

    def get_trends(
        self,
        *,
        start_date: str,
        end_date: str,
        category: str = "maxi dress",
        platforms: list[str] | None = None,
        granularity: str = "day",
        timezone: str = "Asia/Shanghai",
        fill_missing: bool = True,
        include_titles: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> TrendResponse:
        normalized_category = normalize_text(category)
        if normalized_category != "maxi dress":
            raise DomainError(
                400,
                "UNSUPPORTED_CATEGORY",
                "category must normalize to 'maxi dress'",
                {"category": normalized_category},
            )

        parsed_start = _parse_date(start_date, "start_date")
        parsed_end = _parse_date(end_date, "end_date")
        if parsed_start > parsed_end:
            raise DomainError(
                400,
                "INVALID_DATE_RANGE",
                "start_date must be on or before end_date",
            )

        if timezone.strip() != ALLOWED_TIMEZONE:
            raise DomainError(
                400,
                "INVALID_TIMEZONE",
                f"timezone must be {ALLOWED_TIMEZONE}",
                {"timezone": timezone},
            )

        normalized_platforms = _normalize_platforms(platforms)
        resolved_granularity = _resolve_granularity(
            granularity, parsed_start, parsed_end, len(normalized_platforms)
        )

        if page < 1:
            raise DomainError(400, "INVALID_PAGE", "page must be at least 1")
        if page_size < 1:
            raise DomainError(
                400, "INVALID_PAGE_SIZE", "page_size must be at least 1"
            )
        if page_size > PAGE_SIZE_MAX:
            raise DomainError(
                422,
                "RANGE_TOO_LARGE",
                f"page_size must not exceed {PAGE_SIZE_MAX}",
                {"max_page_size": PAGE_SIZE_MAX, "page_size": page_size},
            )

        records = self.repository.get_series(
            parsed_start,
            parsed_end,
            normalized_platforms,
            resolved_granularity,
        )
        series = self._build_series(
            records,
            parsed_start,
            parsed_end,
            normalized_platforms,
            resolved_granularity,
            fill_missing,
        )

        totals_by_platform: dict[str, int] = defaultdict(int)
        for record in records:
            if record.platform in normalized_platforms:
                totals_by_platform[record.platform] += int(record.sales_count)
        totals = [
            PlatformTotal(
                platform=platform,
                sales_count=totals_by_platform[platform],
            )
            for platform in normalized_platforms
        ]

        title_points: list[TitlePoint] | None = None
        pagination: Pagination | None = None
        if include_titles:
            offset = (page - 1) * page_size
            title_records, title_total = self.repository.get_titles_page(
                parsed_start,
                parsed_end,
                normalized_platforms,
                resolved_granularity,
                page_size,
                offset,
            )
            title_points = [
                TitlePoint(
                    date=record.date,
                    platform=record.platform,
                    product_id=record.product_id,
                    title=record.title,
                    sales_count=int(record.sales_count),
                )
                for record in title_records
                if record.title and record.title.strip()
            ]
            pagination = Pagination(
                page=page,
                page_size=page_size,
                total=title_total,
                has_more=offset + len(title_points) < title_total,
            )

        coverage_record = self.repository.get_coverage()
        coverage = Coverage(
            min_date=coverage_record.min_date,
            max_date=coverage_record.max_date,
            is_complete_quarter=_is_complete_quarter(
                coverage_record.min_date, coverage_record.max_date
            ),
        )

        return TrendResponse(
            query=TrendQueryEcho(
                category=normalized_category,
                start_date=parsed_start,
                end_date=parsed_end,
                platforms=normalized_platforms,
                granularity=granularity.strip().lower(),
                resolved_granularity=resolved_granularity,
                timezone=ALLOWED_TIMEZONE,
                fill_missing=fill_missing,
                include_titles=include_titles,
                page=page,
                page_size=page_size,
            ),
            data=TrendData(
                series=series,
                totals=totals,
                total_sales=sum(totals_by_platform.values()),
                titles=title_points,
                pagination=pagination,
            ),
            meta=TrendMeta(
                coverage=coverage,
            ),
        )

    @staticmethod
    def _build_series(
        records,
        start_date: Date,
        end_date: Date,
        platforms: list[str],
        granularity: str,
        fill_missing: bool,
    ) -> list[SeriesPoint]:
        platform_rank = {platform: index for index, platform in enumerate(platforms)}
        values: dict[tuple[Date, str], int] = defaultdict(int)
        for record in records:
            if record.platform not in platform_rank:
                continue
            bucket = _period_key(record.date, granularity)
            values[(bucket, record.platform)] += int(record.sales_count)

        if fill_missing:
            keys = [
                (period, platform)
                for period in _iter_periods(start_date, end_date, granularity)
                for platform in platforms
            ]
        else:
            keys = sorted(
                values,
                key=lambda item: (item[0], platform_rank[item[1]]),
            )

        return [
            SeriesPoint(
                date=period,
                platform=platform,
                sales_count=values.get((period, platform), 0),
            )
            for period, platform in keys
        ]
