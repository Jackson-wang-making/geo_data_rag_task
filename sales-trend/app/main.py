"""FastAPI application factory and error-envelope handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.errors import DomainError, RepositoryUnavailableError
from app.repository import SalesTrendRepository

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body})


def create_app(repository: SalesTrendRepository | None = None) -> FastAPI:
    """Create an app without touching the database.

    Passing a repository is the preferred dependency-injection path for tests.
    """

    application = FastAPI(
        title="Sales Trend API",
        version="1.0.0",
        description="Maxi dress sales trend queries over app.maxi_dress_daily.",
    )
    application.state.repository = repository
    application.include_router(router)

    @application.exception_handler(DomainError)
    async def domain_error_handler(
        request: Request, exc: DomainError
    ) -> JSONResponse:
        return _error_response(
            exc.status_code, exc.code, exc.message, exc.details
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": list(item.get("loc", ())),
                "message": item.get("msg", "Invalid value"),
                "type": item.get("type", "validation_error"),
            }
            for item in exc.errors()
        ]
        return _error_response(
            400,
            "INVALID_QUERY",
            "One or more query parameters are invalid",
            {"errors": details},
        )

    @application.exception_handler(RepositoryUnavailableError)
    async def repository_error_handler(
        request: Request, exc: RepositoryUnavailableError
    ) -> JSONResponse:
        logger.warning("Sales trend repository unavailable: %s", exc)
        return _error_response(
            503,
            "DATABASE_UNAVAILABLE",
            "The sales trend database is unavailable",
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled sales trend API error", exc_info=exc)
        return _error_response(
            500,
            "INTERNAL_ERROR",
            "An unexpected server error occurred",
        )

    return application


app = create_app()
