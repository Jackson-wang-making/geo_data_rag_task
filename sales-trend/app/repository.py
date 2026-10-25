"""Repository boundary and PostgreSQL implementation."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from typing import Protocol

from app.errors import RepositoryUnavailableError

TABLE_NAME = "app.maxi_dress_daily"
STATEMENT_TIMEOUT_MS = 5_000

_BUCKET_SQL = {
    "day": "stat_date",
    "week": "date_trunc('week', stat_date)::date",
    "month": "date_trunc('month', stat_date)::date",
}


@dataclass(frozen=True, slots=True)
class SeriesRecord:
    date: Date
    platform: str
    sales_count: int


@dataclass(frozen=True, slots=True)
class TitleRecord:
    date: Date
    platform: str
    product_id: int
    title: str
    sales_count: int


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    min_date: Date | None
    max_date: Date | None


class SalesTrendRepository(Protocol):
    """Data access required by the trend service."""

    def get_series(
        self,
        start_date: Date,
        end_date: Date,
        platforms: list[str],
        granularity: str,
    ) -> list[SeriesRecord]: ...

    def get_titles_page(
        self,
        start_date: Date,
        end_date: Date,
        platforms: list[str],
        granularity: str,
        limit: int,
        offset: int,
    ) -> tuple[list[TitleRecord], int]: ...

    def get_coverage(self) -> CoverageRecord: ...


def _as_date(value: Date | datetime | str | None) -> Date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, Date):
        return value
    return Date.fromisoformat(value)


def _bucket_expression(granularity: str) -> str:
    try:
        return _BUCKET_SQL[granularity]
    except KeyError as exc:  # defensive: service validates first
        raise ValueError(f"unsupported granularity: {granularity}") from exc


class PostgresSalesTrendRepository:
    """Lazy PostgreSQL repository.

    Construction and import are side-effect free. A connection is opened only
    when a request invokes a repository method, so the FastAPI app can be
    imported without a live database or database driver.
    """

    def __init__(self, database_url: str | None) -> None:
        self.database_url = database_url
        self._pool_obj = None
        self._pool_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "PostgresSalesTrendRepository":
        return cls(os.getenv("DATABASE_URL"))

    def _pool(self):
        if self._pool_obj is None:
            with self._pool_lock:
                if self._pool_obj is None:
                    if not self.database_url:
                        raise RepositoryUnavailableError("DATABASE_URL is not configured")

                    try:
                        from psycopg_pool import ConnectionPool
                    except ImportError as exc:
                        raise RepositoryUnavailableError(
                            "The psycopg_pool driver is not installed"
                        ) from exc

                    try:
                        self._pool_obj = ConnectionPool(
                            self.database_url,
                            min_size=1,
                            max_size=10,
                            timeout=5,
                            open=True,
                        )
                    except Exception as exc:
                        raise RepositoryUnavailableError(
                            "PostgreSQL is unavailable"
                        ) from exc
        return self._pool_obj

    def _fetchall(self, sql: str, params: tuple[object, ...]) -> list[tuple]:
        try:
            with self._pool().connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"
                    )
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
        except RepositoryUnavailableError:
            raise
        except Exception as exc:
            raise RepositoryUnavailableError("PostgreSQL query failed") from exc

    def get_series(
        self,
        start_date: Date,
        end_date: Date,
        platforms: list[str],
        granularity: str,
    ) -> list[SeriesRecord]:
        bucket = _bucket_expression(granularity)
        sql = f"""
            SELECT
                {bucket}::date AS period_date,
                source AS platform,
                COALESCE(SUM(sales_count), 0)::bigint AS sales_count
            FROM {TABLE_NAME}
            WHERE stat_date BETWEEN %s AND %s
              AND source = ANY(%s)
            GROUP BY period_date, source
            ORDER BY period_date, source
        """
        rows = self._fetchall(sql, (start_date, end_date, platforms))
        return [
            SeriesRecord(
                date=_as_date(row[0]),
                platform=str(row[1]),
                sales_count=int(row[2]),
            )
            for row in rows
        ]

    def get_titles_page(
        self,
        start_date: Date,
        end_date: Date,
        platforms: list[str],
        granularity: str,
        limit: int,
        offset: int,
    ) -> tuple[list[TitleRecord], int]:
        bucket = _bucket_expression(granularity)
        where_clause = """
            stat_date BETWEEN %s AND %s
            AND source = ANY(%s)
            AND title IS NOT NULL
            AND btrim(title) <> ''
        """
        count_sql = f"""
            SELECT COUNT(*)
            FROM (
                SELECT 1
                FROM {TABLE_NAME}
                WHERE {where_clause}
                GROUP BY {bucket}, source, product_id, title
            ) AS title_groups
        """
        page_sql = f"""
            SELECT
                {bucket}::date AS period_date,
                source AS platform,
                product_id,
                title,
                COALESCE(SUM(sales_count), 0)::bigint AS sales_count
            FROM {TABLE_NAME}
            WHERE {where_clause}
            GROUP BY {bucket}, source, product_id, title
            ORDER BY period_date, source, product_id, title
            LIMIT %s OFFSET %s
        """
        params = (start_date, end_date, platforms)
        count_rows = self._fetchall(count_sql, params)
        total = int(count_rows[0][0]) if count_rows else 0
        rows = self._fetchall(page_sql, (*params, limit, offset))
        items = [
            TitleRecord(
                date=_as_date(row[0]),
                platform=str(row[1]),
                product_id=int(row[2]),
                title=str(row[3]),
                sales_count=int(row[4]),
            )
            for row in rows
        ]
        return items, total

    def get_coverage(self) -> CoverageRecord:
        # Coverage is raw source coverage precomputed by the ETL, not
        # maxi-dress result coverage. Reading app.coverage_meta keeps this
        # hot path from scanning raw.sales_data on every request.
        sql = """
            SELECT min_date, max_date
            FROM app.coverage_meta
            WHERE scope = 'raw_source'
        """
        rows = self._fetchall(sql, ())
        if not rows:
            return CoverageRecord(min_date=None, max_date=None)
        return CoverageRecord(
            min_date=_as_date(rows[0][0]),
            max_date=_as_date(rows[0][1]),
        )

