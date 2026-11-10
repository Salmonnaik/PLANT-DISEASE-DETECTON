"""
routes/stats_routes.py
======================
Aggregated statistics for the Dashboard and Analytics pages.

    GET /api/stats       totals, distributions, activity, recent detections
    GET /api/analytics   the above plus confidence histogram and model metrics

Every value is computed from ``detection_history`` at request time, so a fresh
install returns zeros rather than sample data.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request

from services import stats_service
from utils.errors import ValidationError
from utils.responses import success_response

logger = logging.getLogger(__name__)

stats_bp = Blueprint("stats", __name__, url_prefix="/api")


def _int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"'{name}' must be an integer, got {raw!r}.") from exc
    return max(minimum, min(maximum, value))


@stats_bp.route("/stats", methods=["GET"])
def get_stats():
    """Dashboard overview statistics."""
    return success_response(
        stats_service.overview(
            recent_limit=_int_arg("recent", 5, 1, 50),
            activity_days=_int_arg("days", 14, 1, 365),
        )
    )


@stats_bp.route("/analytics", methods=["GET"])
def get_analytics():
    """Analytics page payload, including model evaluation metrics when available."""
    return success_response(stats_service.analytics(days=_int_arg("days", 30, 1, 365)))


__all__ = ["stats_bp"]
