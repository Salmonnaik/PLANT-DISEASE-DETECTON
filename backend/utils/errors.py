"""
utils/errors.py
===============
A single exception type for expected failures plus the Flask error handlers
that turn anything escaping a route into the standard JSON envelope.

The point: a route raises ``ApiError("ESP32-CAM is not reachable", 503,
"DEVICE_OFFLINE")`` and the client receives an actionable message with a stable
code, instead of an HTML stack trace.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Optional

from flask import Flask, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from utils.responses import error_response

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """An expected, reportable failure with an HTTP status and error code."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: Optional[str] = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "status_code": self.status_code,
            "code": self.code,
            "details": self.details,
        }


# Convenience subclasses for the failure modes this project hits most often.

class ValidationError(ApiError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, 400, "VALIDATION_ERROR", details)


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found.", details: Any = None) -> None:
        super().__init__(message, 404, "NOT_FOUND", details)


class ModelUnavailableError(ApiError):
    """No usable model: the file is missing, or it is untrained and test mode is off."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, 503, "MODEL_UNAVAILABLE", details)


class DeviceUnreachableError(ApiError):
    """The ESP32-CAM did not answer, timed out, or returned an unusable response."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, 503, "DEVICE_UNREACHABLE", details)


class ImageValidationError(ApiError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, 400, "INVALID_IMAGE", details)


def register_error_handlers(app: Flask) -> None:
    """Install JSON error handlers on the application."""

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        logger.warning(
            "%s %s -> %d %s: %s",
            request.method,
            request.path,
            exc.status_code,
            exc.code or "",
            exc.message,
        )
        return error_response(exc.message, exc.status_code, exc.code, exc.details)

    @app.errorhandler(RequestEntityTooLarge)
    def _handle_too_large(_exc: RequestEntityTooLarge):
        limit = app.config.get("MAX_UPLOAD_MB", 12)
        return error_response(
            f"The uploaded image is larger than the {limit} MB limit. "
            "Reduce the ESP32-CAM frame size or compress the file before uploading.",
            413,
            "PAYLOAD_TOO_LARGE",
            {"max_upload_mb": limit},
        )

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response(
            f"No API route matches {request.method} {request.path}.",
            404,
            "ROUTE_NOT_FOUND",
        )

    @app.errorhandler(405)
    def _handle_405(exc):
        allowed = getattr(exc, "valid_methods", None)
        return error_response(
            f"{request.method} is not allowed on {request.path}.",
            405,
            "METHOD_NOT_ALLOWED",
            {"allowed_methods": list(allowed) if allowed else None},
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        return error_response(
            exc.description or exc.name,
            exc.code or 500,
            exc.name.upper().replace(" ", "_"),
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        logger.error(
            "Unhandled error on %s %s: %s\n%s",
            request.method,
            request.path,
            exc,
            traceback.format_exc(),
        )
        details = None
        if app.config.get("DEBUG"):
            details = {"exception": exc.__class__.__name__, "message": str(exc)}
        return error_response(
            "An unexpected server error occurred. Check the backend console for the "
            "full traceback.",
            500,
            "INTERNAL_ERROR",
            details,
        )


__all__ = [
    "ApiError",
    "ValidationError",
    "NotFoundError",
    "ModelUnavailableError",
    "DeviceUnreachableError",
    "ImageValidationError",
    "register_error_handlers",
]
