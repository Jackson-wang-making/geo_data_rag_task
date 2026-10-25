"""FastAPI dependency providers."""

from __future__ import annotations

from fastapi import Depends, Request

from app.repository import PostgresSalesTrendRepository, SalesTrendRepository
from app.services.sales_trends import SalesTrendService


def get_repository(request: Request) -> SalesTrendRepository:
    """Return the configured repository, creating a lazy DB repository if needed.

    request.app.state.repository is the injection seam used by app
    factories and tests. No database connection is made here.
    """

    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        repository = PostgresSalesTrendRepository.from_env()
        request.app.state.repository = repository
    return repository


def get_sales_trend_service(
    repository: SalesTrendRepository = Depends(get_repository),
) -> SalesTrendService:
    return SalesTrendService(repository)
