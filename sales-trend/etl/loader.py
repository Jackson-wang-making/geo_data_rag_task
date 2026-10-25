"""Idempotent XLSX loader for the sales-trend PostgreSQL warehouse."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etl.quality import (
    RAW_COLUMNS,
    PreparedSales,
    QualityMetrics,
    assess_quality,
    verify_sample_metrics,
)

LOGGER = logging.getLogger("sales_trend.etl")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL_DIR = PROJECT_ROOT / "sql"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/sales_trend"
DEFAULT_WORKBOOK_CANDIDATES = (PROJECT_ROOT / "data" / "sample_sales.xlsx",)
DEFAULT_WORKBOOK_SEARCH_DIRS = (
    PROJECT_ROOT.parent,
    PROJECT_ROOT,
    PROJECT_ROOT / "data",
)
RAW_STAGE_COLUMNS = (
    "product_id",
    "title",
    "sales_count",
    "timestamp",
    "user_id",
    "category",
    "source",
)

RAW_INSERT_SQL = """
WITH inserted AS (
    INSERT INTO raw.sales_data (
        product_id, title, sales_count, "timestamp", user_id, category, source
    )
    SELECT
        s.product_id, s.title, s.sales_count, s."timestamp",
        s.user_id, s.category, s.source
    FROM _etl_raw_stage AS s
    WHERE NOT EXISTS (
        SELECT 1
        FROM raw.sales_data AS existing
        WHERE existing.product_id IS NOT DISTINCT FROM s.product_id
          AND existing.title IS NOT DISTINCT FROM s.title
          AND existing.sales_count IS NOT DISTINCT FROM s.sales_count
          AND existing."timestamp" IS NOT DISTINCT FROM s."timestamp"
          AND existing.user_id IS NOT DISTINCT FROM s.user_id
          AND existing.category IS NOT DISTINCT FROM s.category
          AND existing.source IS NOT DISTINCT FROM s.source
    )
    RETURNING 1
)
SELECT count(*)::bigint FROM inserted;
"""


class QualityGateError(RuntimeError):
    """Raised when the workbook or database violates the acceptance contract."""


def resolve_workbook_path(workbook: str | Path | None = None) -> Path:
    """Resolve a workbook path, including paths containing Chinese characters."""
    if workbook:
        supplied = Path(workbook).expanduser()
        candidates = [supplied] if supplied.is_absolute() else [
            Path.cwd() / supplied,
            PROJECT_ROOT / supplied,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        searched = ", ".join(str(candidate.resolve()) for candidate in candidates)
        raise FileNotFoundError(f"workbook not found; searched: {searched}")

    for directory in DEFAULT_WORKBOOK_SEARCH_DIRS:
        for candidate in sorted(directory.glob("*.xlsx")):
            if candidate.is_file() and not candidate.name.startswith("~$"):
                return candidate.resolve()
    for candidate in DEFAULT_WORKBOOK_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    searched_dirs = ", ".join(str(directory) for directory in DEFAULT_WORKBOOK_SEARCH_DIRS)
    raise FileNotFoundError(
        f"no default workbook found; searched XLSX files under: {searched_dirs}"
    )


def read_sales_workbook(path: Path, sheet_name: str = "sample_sales_data") -> pd.DataFrame:
    """Read the sample sheet and enforce the seven-column source contract."""
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        if sheet_name not in workbook.sheet_names:
            raise ValueError(
                f"sheet {sheet_name!r} not found in {path}; "
                f"available sheets: {workbook.sheet_names}"
            )
        frame = pd.read_excel(workbook, sheet_name=sheet_name, engine="openpyxl")

    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in RAW_COLUMNS if column not in frame.columns]
    unexpected = [column for column in frame.columns if column not in RAW_COLUMNS]
    if missing or unexpected:
        raise ValueError(
            f"unexpected workbook columns; missing={missing}, unexpected={unexpected}"
        )
    return frame.loc[:, list(RAW_COLUMNS)].copy()


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False


def _nullable_int(value: Any) -> int | None:
    if _is_null(value):
        return None
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number) or number % 1 != 0:
        return None
    return int(number)


def _nullable_timestamp(value: Any) -> datetime | None:
    if _is_null(value):
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.to_pydatetime().replace(tzinfo=None)


def _nullable_text(value: Any) -> str | None:
    if _is_null(value):
        return None
    return str(value)


def _storage_rows(frame: pd.DataFrame) -> Iterable[tuple[Any, ...]]:
    for row in frame.loc[:, list(RAW_COLUMNS)].itertuples(index=False, name=None):
        yield (
            _nullable_int(row[0]),
            _nullable_text(row[1]),
            _nullable_int(row[2]),
            _nullable_timestamp(row[3]),
            _nullable_text(row[4]),
            _nullable_text(row[5]),
            _nullable_text(row[6]),
        )


def apply_schema(conn: Any, sql_dir: Path) -> None:
    """Apply idempotent schema/function files before loading data."""
    if not sql_dir.is_dir():
        raise FileNotFoundError(f"SQL directory not found: {sql_dir}")
    for sql_path in sorted(sql_dir.glob("*.sql")):
        # The loader executes the standardization statement after raw rows exist.
        if sql_path.name.startswith("004_"):
            continue
        conn.execute(sql_path.read_text(encoding="utf-8"))


def insert_raw_rows(conn: Any, raw: pd.DataFrame) -> int:
    """Insert all source rows once, preserving duplicates within one batch.

    A temporary table keeps the operation set-based. On a rerun every exact row
    already exists, so no additional raw rows are inserted.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('raw.sales_data.load', 0))")
        cur.execute(
            """
            CREATE TEMP TABLE _etl_raw_stage (
                product_id bigint,
                title text,
                sales_count integer,
                "timestamp" timestamp,
                user_id text,
                category text,
                source text
            ) ON COMMIT DROP
            """
        )
        with cur.copy(
            'COPY _etl_raw_stage (product_id, title, sales_count, "timestamp", '
            "user_id, category, source) FROM STDIN"
        ) as copy:
            for row in _storage_rows(raw):
                copy.write_row(row)
        cur.execute(RAW_INSERT_SQL)
        return int(cur.fetchone()[0])


def standardize_rows(conn: Any, sql_dir: Path) -> None:
    standardize_sql = (sql_dir / "004_standardize.sql").read_text(encoding="utf-8")
    conn.execute(standardize_sql)


def database_quality_metrics(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT count(*)::bigint FROM raw.sales_data) AS raw_count,
                count(*)::bigint AS accepted_count,
                count(*) FILTER (WHERE is_maxi_dress)::bigint AS explicit_count,
                COALESCE(
                    sum(sales_count) FILTER (WHERE is_maxi_dress), 0
                )::bigint AS explicit_sales,
                count(DISTINCT product_id) FILTER (
                    WHERE is_maxi_dress
                )::bigint AS explicit_product_count
            FROM std.sales_clean
            """
        )
        quality_row = cur.fetchone()
        cur.execute(
            """
            SELECT source, sum(sales_count)::bigint
            FROM std.sales_clean
            WHERE is_maxi_dress
            GROUP BY source
            ORDER BY source
            """
        )
        platform_sales = {str(source): int(amount) for source, amount in cur.fetchall()}
    return {
        "raw_count": int(quality_row[0]),
        "accepted_count": int(quality_row[1]),
        "explicit_count": int(quality_row[2]),
        "explicit_sales": int(quality_row[3]),
        "explicit_product_count": int(quality_row[4]),
        "platform_sales": platform_sales,
    }


def refresh_coverage(conn: Any) -> None:
    """Precompute raw source coverage so the API never scans raw.sales_data."""
    with conn.cursor() as cur:
        cur.execute("SELECT app.refresh_coverage()")
        cur.fetchone()


def refresh_application(
    conn: Any,
    metrics: QualityMetrics,
) -> dict[str, Any]:
    if metrics.min_business_date is None or metrics.max_business_date is None:
        return {"start_date": None, "end_date": None, "rows_written": 0, "sales_count": 0}

    start_date = metrics.min_business_date
    end_date = metrics.max_business_date
    with conn.cursor() as cur:
        cur.execute(
            "SELECT app.refresh_maxi_dress_daily(%s::date, %s::date)",
            (start_date, end_date),
        )
        rows_written = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COALESCE(sum(sales_count), 0)::bigint
            FROM app.maxi_dress_daily
            WHERE stat_date BETWEEN %s::date AND %s::date
            """,
            (start_date, end_date),
        )
        sales_count = int(cur.fetchone()[0])
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rows_written": rows_written,
        "sales_count": sales_count,
    }


def _assert_quality(problems: list[str]) -> None:
    if problems:
        raise QualityGateError("; ".join(problems))


def load_workbook(
    *,
    workbook_path: Path,
    database_url: str,
    sheet_name: str = "sample_sales_data",
    sql_dir: Path = DEFAULT_SQL_DIR,
    verify_sample: bool = True,
    skip_schema: bool = False,
) -> dict[str, Any]:
    raw = read_sales_workbook(workbook_path, sheet_name)
    prepared: PreparedSales = assess_quality(raw)

    if verify_sample:
        _assert_quality(verify_sample_metrics(prepared.metrics))

    from psycopg import connect

    conn = connect(database_url, connect_timeout=10)
    try:
        with conn.transaction():
            if not skip_schema:
                apply_schema(conn, sql_dir)

            raw_rows_inserted = insert_raw_rows(conn, raw)
            standardize_rows(conn, sql_dir)
            refresh_coverage(conn)
            db_metrics = database_quality_metrics(conn)

            compare_keys = (
                "raw_count",
                "accepted_count",
                "explicit_count",
                "explicit_sales",
                "explicit_product_count",
                "platform_sales",
            )
            python_values = prepared.metrics.as_dict()
            mismatches = [
                f"{key}: python={python_values[key]!r}, database={db_metrics[key]!r}"
                for key in compare_keys
                if python_values[key] != db_metrics[key]
            ]
            _assert_quality(mismatches)

            refresh = refresh_application(conn, prepared.metrics)
            if verify_sample and refresh["sales_count"] != prepared.metrics.explicit_sales:
                raise QualityGateError(
                    "application refresh mismatch: expected "
                    f"{prepared.metrics.explicit_sales}, got {refresh['sales_count']}"
                )

        result = {
            "status": "ok",
            "workbook": str(workbook_path),
            "sheet": sheet_name,
            "quality": prepared.metrics.as_dict(),
            "database_quality": db_metrics,
            "raw_rows_inserted": raw_rows_inserted,
            "refresh": refresh,
        }
        return result
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", help="XLSX path; Chinese paths are supported")
    parser.add_argument(
        "--sheet",
        default=os.getenv("WORKBOOK_SHEET", "sample_sales_data"),
        help="worksheet name (default: sample_sales_data)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=Path(os.getenv("SQL_DIR", str(DEFAULT_SQL_DIR))),
        help="directory containing the SQL files",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="skip applying idempotent schema/function SQL",
    )
    parser.add_argument(
        "--verify-sample",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="verify the 300/288/119/1117 sample acceptance contract",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        workbook_path = resolve_workbook_path(args.workbook)
        result = load_workbook(
            workbook_path=workbook_path,
            database_url=args.database_url,
            sheet_name=args.sheet,
            sql_dir=args.sql_dir,
            verify_sample=args.verify_sample,
            skip_schema=args.skip_schema,
        )
    except Exception:
        LOGGER.exception("ETL failed")
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())