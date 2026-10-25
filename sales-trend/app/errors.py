"""Domain errors and the API error envelope."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """An expected request error with a stable API code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class RepositoryUnavailableError(RuntimeError):
    """Raised when the application repository cannot be reached."""
