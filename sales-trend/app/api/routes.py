"""Sales trend HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_sales_trend_service
from app.models import ErrorResponse, TrendResponse
from app.services.sales_trends import SalesTrendService

router = APIRouter(prefix="/v1/sales", tags=["sales"])


@router.get(
    "/trends",
    response_model=TrendResponse,
    response_model_exclude_none=True,
    summary="Query maxi dress sales trends",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid query parameter"},
        422: {"model": ErrorResponse, "description": "Range too large"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)
def get_sales_trends(
    start_date: str = Query(..., description="Inclusive start date, YYYY-MM-DD"),
    end_date: str = Query(..., description="Inclusive end date, YYYY-MM-DD"),
    category: str = Query("maxi dress", description="Normalized category gate"),
    platform: list[str] | None = Query(
        None,
        description="Repeatable platform filter: website, app, or marketplace",
    ),
    granularity: str = Query("day", description="day, week, month, or auto"),
    timezone_name: str = Query(
        "Asia/Shanghai",
        alias="timezone",
        description="v1 only supports Asia/Shanghai",
    ),
    fill_missing: bool = Query(True, description="Fill date/platform gaps with zero"),
    include_titles: bool = Query(
        False, description="Include paginated product/title detail"
    ),
    page: int = Query(1, description="Title detail page, starting at 1"),
    page_size: int = Query(100, description="Title detail page size, max 500"),
    service: SalesTrendService = Depends(get_sales_trend_service),
) -> TrendResponse:
    return service.get_trends(
        start_date=start_date,
        end_date=end_date,
        category=category,
        platforms=platform,
        granularity=granularity,
        timezone=timezone_name,
        fill_missing=fill_missing,
        include_titles=include_titles,
        page=page,
        page_size=page_size,
    )
