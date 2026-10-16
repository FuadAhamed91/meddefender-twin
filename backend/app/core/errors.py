"""Structured application errors rendered as ``{"error": {...}}`` responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class NotFound(AppError):
    def __init__(self, what: str, identifier: str | int) -> None:
        super().__init__(404, "NOT_FOUND", f"{what} '{identifier}' was not found")


class Forbidden(AppError):
    def __init__(self, message: str = "Your role does not permit this action") -> None:
        super().__init__(403, "FORBIDDEN", message)


class Conflict(AppError):
    def __init__(self, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(409, code, message, details)


class BadRequest(AppError):
    def __init__(self, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(400, code, message, details)
