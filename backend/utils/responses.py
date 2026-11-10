"""
utils/responses.py
==================
One JSON envelope for every endpoint, so the frontend has exactly one shape to
parse and one place to look for errors.

Success::

    {"success": true, "data": {...}, "message": null, "timestamp": "..."}

Failure::

    {"success": false,
     "error": {"code": "MODEL_NOT_LOADED", "message": "...", "details": {...}},
     "timestamp": "..."}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from flask import jsonify

JsonResponse = Tuple[Any, int]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def success_response(
    data: Any = None,
    message: Optional[str] = None,
    status_code: int = 200,
    **extra: Any,
) -> JsonResponse:
    """Build a successful JSON response."""
    payload: Dict[str, Any] = {
        "success": True,
        "data": data,
        "message": message,
        "timestamp": _timestamp(),
    }
    payload.update(extra)
    return jsonify(payload), status_code


def error_response(
    message: str,
    status_code: int = 400,
    code: Optional[str] = None,
    details: Any = None,
) -> JsonResponse:
    """Build a failed JSON response with a stable machine-readable ``code``."""
    payload: Dict[str, Any] = {
        "success": False,
        "data": None,
        "error": {
            "code": code or _default_code(status_code),
            "message": message,
            "details": details,
        },
        "timestamp": _timestamp(),
    }
    return jsonify(payload), status_code


def _default_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }.get(status_code, "ERROR")


def paginated_response(
    items: Any,
    total: int,
    limit: int,
    offset: int,
    message: Optional[str] = None,
    **extra: Any,
) -> JsonResponse:
    """Success response that also carries pagination metadata."""
    page_size = max(1, int(limit))
    return success_response(
        data={
            "items": items,
            "pagination": {
                "total": int(total),
                "limit": page_size,
                "offset": int(offset),
                "page": (int(offset) // page_size) + 1,
                "pages": max(1, (int(total) + page_size - 1) // page_size),
                "has_more": int(offset) + len(items) < int(total),
            },
            **extra,
        },
        message=message,
    )


__all__ = ["success_response", "error_response", "paginated_response"]
