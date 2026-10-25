"""Pydantic response models for the sales trend endpoint."""

from __future__ import annotations

from datetime import date as Date
from typing import Any

from pydantic import BaseModel, Field


class SeriesPoint(BaseModel):
    """A date/platform aggregate.

    This model deliberately has no title field. Zero-filled points therefore
    cannot expose title: null.
    """

    date: Date
    platform: str
    sales_count: int = Field(ge=0)


class TitlePoint(BaseModel):
    """A paginated product/title aggregate."""

    date: Date
    platform: str
    product_id: int
    title: str = Field(min_length=1)
    sales_count: int = Field(ge=0)


class PlatformTotal(BaseModel):
    platform: str
    sales_count: int = Field(ge=0)


class Pagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    total: int = Field(ge=0)
    has_more: bool


class TrendData(BaseModel):
    series: list[SeriesPoint]
    totals: list[PlatformTotal]
    total_sales: int = Field(ge=0)
    titles: list[TitlePoint] | None = None
    pagination: Pagination | None = None


class TrendQueryEcho(BaseModel):
    category: str
    start_date: Date
    end_date: Date
    platforms: list[str]
    granularity: str
    resolved_granularity: str
    timezone: str
    fill_missing: bool
    include_titles: bool
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)


class Coverage(BaseModel):
    min_date: Date | None
    max_date: Date | None
    is_complete_quarter: bool
    coverage_type: str = "raw_source"


class TrendMeta(BaseModel):
    rule_version: str = "maxi_dress_v1"
    coverage: Coverage


class TrendResponse(BaseModel):
    query: TrendQueryEcho
    data: TrendData
    meta: TrendMeta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
