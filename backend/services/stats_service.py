"""
services/stats_service.py
=========================
Aggregation queries behind ``/api/stats`` and ``/api/analytics``.

Every number the dashboard shows is computed here from ``detection_history`` -
there are no seeded or illustrative values anywhere. An empty database produces
zeros and empty series, which the UI renders as its own empty state.

Timezone note: grouping uses ``date(created_at, 'localtime')`` so "today" and
the daily activity chart line up with the operator's wall clock, even though the
rows themselves are stored in UTC.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from database.db import query_all, query_one, query_scalar, to_iso8601
from models import detection as detection_model
from services.ml_service import get_ml_service

logger = logging.getLogger(__name__)

# Fixed palette so a disease keeps the same colour across every chart.
CHART_COLOURS = [
    "#16a34a", "#dc2626", "#ea580c", "#ca8a04", "#0891b2",
    "#7c3aed", "#db2777", "#0d9488", "#4f46e5", "#b45309",
    "#059669", "#e11d48", "#2563eb", "#9333ea", "#65a30d",
]


def _colour_for(index: int) -> str:
    return CHART_COLOURS[index % len(CHART_COLOURS)]


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #

def status_counts() -> Dict[str, int]:
    """Row counts per detection status, with every status key always present."""
    rows = query_all(
        "SELECT detection_status, COUNT(*) AS total FROM detection_history "
        "GROUP BY detection_status"
    )
    counts = {status: 0 for status in detection_model.VALID_STATUSES}
    for row in rows:
        counts[row["detection_status"]] = int(row["total"])
    return counts


def source_counts() -> Dict[str, int]:
    rows = query_all(
        "SELECT source, COUNT(*) AS total FROM detection_history GROUP BY source"
    )
    counts = {source: 0 for source in detection_model.VALID_SOURCES}
    for row in rows:
        counts[row["source"]] = int(row["total"])
    return counts


def camera_source_counts() -> List[Dict[str, Any]]:
    """
    Detections per camera, always listing every configured source.

    Zero-filled so the dashboard can show "Laptop webcam: 0" rather than
    omitting a camera that simply has not been used yet.
    """
    rows = {
        str(row["camera_source"]): row
        for row in query_all(
            """
            SELECT camera_source,
                   COUNT(*) AS total,
                   SUM(CASE WHEN detection_status = 'healthy'  THEN 1 ELSE 0 END) AS healthy,
                   SUM(CASE WHEN detection_status = 'diseased' THEN 1 ELSE 0 END) AS diseased,
                   AVG(confidence) AS avg_confidence,
                   MAX(created_at) AS last_used
              FROM detection_history
             GROUP BY camera_source
            """
        )
    }

    palette = {
        detection_model.CAMERA_SOURCE_WEBCAM: "#0891b2",
        detection_model.CAMERA_SOURCE_ESP32: "#16a34a",
        detection_model.CAMERA_SOURCE_FILE: "#7c3aed",
    }

    ordered = [
        detection_model.CAMERA_SOURCE_WEBCAM,
        detection_model.CAMERA_SOURCE_ESP32,
        detection_model.CAMERA_SOURCE_FILE,
    ]
    # Include anything unexpected that is already stored, so no record is hidden.
    ordered += [key for key in rows if key not in ordered]

    result: List[Dict[str, Any]] = []
    for index, key in enumerate(ordered):
        row = rows.get(key)
        result.append(
            {
                "camera_source": key,
                "label": detection_model.camera_source_label(key),
                "count": int(row["total"]) if row else 0,
                "healthy": int(row["healthy"] or 0) if row else 0,
                "diseased": int(row["diseased"] or 0) if row else 0,
                "avg_confidence": round(float(row["avg_confidence"] or 0.0), 4) if row else 0.0,
                "last_used": to_iso8601(row["last_used"]) if row and row["last_used"] else None,
                "colour": palette.get(key, _colour_for(index + 6)),
            }
        )
    return result


def disease_distribution(include_healthy: bool = False) -> List[Dict[str, Any]]:
    """Counts per detected condition, ordered by frequency."""
    where = "" if include_healthy else " WHERE detection_status = 'diseased'"
    rows = query_all(
        f"""
        SELECT predicted_disease AS disease,
               plant_name        AS plant,
               COUNT(*)          AS total,
               AVG(confidence)   AS avg_confidence
          FROM detection_history{where}
         GROUP BY predicted_disease, plant_name
         ORDER BY total DESC, disease ASC
        """
    )
    total = sum(int(row["total"]) for row in rows) or 1
    return [
        {
            "name": f"{row['plant']} - {row['disease']}",
            "disease": row["disease"],
            "plant": row["plant"],
            "count": int(row["total"]),
            "percentage": round(int(row["total"]) * 100.0 / total, 1),
            "avg_confidence": round(float(row["avg_confidence"] or 0.0), 4),
            "colour": _colour_for(index),
        }
        for index, row in enumerate(rows)
    ]


def plant_distribution() -> List[Dict[str, Any]]:
    """Per-plant totals split by outcome, for the plant-wise analytics chart."""
    rows = query_all(
        """
        SELECT plant_name AS plant,
               COUNT(*) AS total,
               SUM(CASE WHEN detection_status = 'healthy'  THEN 1 ELSE 0 END) AS healthy,
               SUM(CASE WHEN detection_status = 'diseased' THEN 1 ELSE 0 END) AS diseased,
               SUM(CASE WHEN detection_status IN ('uncertain','unknown') THEN 1 ELSE 0 END) AS inconclusive,
               AVG(confidence) AS avg_confidence
          FROM detection_history
         GROUP BY plant_name
         ORDER BY total DESC, plant ASC
        """
    )
    return [
        {
            "plant": row["plant"],
            "total": int(row["total"]),
            "healthy": int(row["healthy"] or 0),
            "diseased": int(row["diseased"] or 0),
            "inconclusive": int(row["inconclusive"] or 0),
            "avg_confidence": round(float(row["avg_confidence"] or 0.0), 4),
            "colour": _colour_for(index),
        }
        for index, row in enumerate(rows)
    ]


def daily_activity(days: int = 14) -> List[Dict[str, Any]]:
    """
    Detections per day for the last ``days`` days, zero-filled.

    Zero-filling in Python (rather than with a recursive SQL date series) keeps
    the chart's x-axis continuous even on days with no scans, so a gap reads as
    "nothing happened" instead of compressing the timeline.
    """
    span = max(1, min(int(days), 365))
    rows = query_all(
        """
        SELECT date(created_at, 'localtime') AS day,
               COUNT(*) AS total,
               SUM(CASE WHEN detection_status = 'healthy'  THEN 1 ELSE 0 END) AS healthy,
               SUM(CASE WHEN detection_status = 'diseased' THEN 1 ELSE 0 END) AS diseased,
               SUM(CASE WHEN detection_status IN ('uncertain','unknown') THEN 1 ELSE 0 END) AS inconclusive
          FROM detection_history
         WHERE date(created_at, 'localtime') >= date('now', 'localtime', ?)
         GROUP BY day
         ORDER BY day ASC
        """,
        (f"-{span - 1} days",),
    )
    by_day = {row["day"]: row for row in rows}

    today = date.today()
    series: List[Dict[str, Any]] = []
    for offset in range(span - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        row = by_day.get(key)
        series.append(
            {
                "date": key,
                "label": day.strftime("%d %b"),
                "total": int(row["total"]) if row else 0,
                "healthy": int(row["healthy"] or 0) if row else 0,
                "diseased": int(row["diseased"] or 0) if row else 0,
                "inconclusive": int(row["inconclusive"] or 0) if row else 0,
            }
        )
    return series


def confidence_distribution() -> List[Dict[str, Any]]:
    """Histogram of prediction confidence over conclusive detections."""
    buckets = [
        ("0-50%", 0.0, 0.5),
        ("50-70%", 0.5, 0.7),
        ("70-85%", 0.7, 0.85),
        ("85-95%", 0.85, 0.95),
        ("95-100%", 0.95, 1.01),
    ]
    result: List[Dict[str, Any]] = []
    for index, (label, low, high) in enumerate(buckets):
        count = int(
            query_scalar(
                "SELECT COUNT(*) FROM detection_history "
                "WHERE is_conclusive = 1 AND confidence >= ? AND confidence < ?",
                (low, high),
            )
        )
        result.append({"range": label, "count": count, "colour": _colour_for(index)})
    return result


def confidence_summary() -> Dict[str, Any]:
    row = query_one(
        """
        SELECT AVG(confidence) AS average,
               MIN(confidence) AS minimum,
               MAX(confidence) AS maximum,
               COUNT(*)        AS samples
          FROM detection_history
         WHERE is_conclusive = 1
        """
    ) or {}
    samples = int(row.get("samples") or 0)
    return {
        "samples": samples,
        "average": round(float(row.get("average") or 0.0), 4),
        "minimum": round(float(row.get("minimum") or 0.0), 4),
        "maximum": round(float(row.get("maximum") or 0.0), 4),
        "average_percent": round(float(row.get("average") or 0.0) * 100.0, 1),
    }


def today_count() -> int:
    return int(
        query_scalar(
            "SELECT COUNT(*) FROM detection_history "
            "WHERE date(created_at, 'localtime') = date('now', 'localtime')"
        )
    )


def last_detection_at() -> Optional[str]:
    value = query_scalar(
        "SELECT MAX(created_at) FROM detection_history", default=None
    )
    return to_iso8601(value) if value else None


def test_mode_record_count() -> int:
    """
    Rows produced by the untrained bootstrap model.

    Surfaced so the UI can warn that part of the history is not real diagnostic
    data rather than silently mixing it with trained-model results.
    """
    return int(query_scalar("SELECT COUNT(*) FROM detection_history WHERE is_validated = 0"))


# --------------------------------------------------------------------------- #
# Composite endpoints
# --------------------------------------------------------------------------- #

def overview(recent_limit: int = 5, activity_days: int = 14) -> Dict[str, Any]:
    """Payload for ``GET /api/stats`` - everything the Dashboard page needs."""
    counts = status_counts()
    total = sum(counts.values())
    inconclusive = counts["uncertain"] + counts["unknown"]

    return {
        "totals": {
            "total_detections": total,
            "healthy": counts["healthy"],
            "diseased": counts["diseased"],
            "uncertain": counts["uncertain"],
            "unknown": counts["unknown"],
            "inconclusive": inconclusive,
            "today": today_count(),
            "test_mode_records": test_mode_record_count(),
        },
        "rates": {
            "healthy_percent": round(counts["healthy"] * 100.0 / total, 1) if total else 0.0,
            "diseased_percent": round(counts["diseased"] * 100.0 / total, 1) if total else 0.0,
            "inconclusive_percent": round(inconclusive * 100.0 / total, 1) if total else 0.0,
        },
        "confidence": confidence_summary(),
        "sources": source_counts(),
        "camera_sources": camera_source_counts(),
        "disease_distribution": disease_distribution(),
        "plant_distribution": plant_distribution(),
        "activity": daily_activity(activity_days),
        "recent_detections": detection_model.recent_detections(recent_limit),
        "last_detection_at": last_detection_at(),
        "is_empty": total == 0,
    }


def analytics(days: int = 30) -> Dict[str, Any]:
    """Payload for ``GET /api/analytics`` - the Analytics page."""
    counts = status_counts()
    total = sum(counts.values())
    inconclusive = counts["uncertain"] + counts["unknown"]

    ml_service = get_ml_service()
    reports = ml_service.evaluation_reports()

    healthy_vs_diseased = [
        {"name": "Healthy", "count": counts["healthy"], "colour": "#16a34a"},
        {"name": "Diseased", "count": counts["diseased"], "colour": "#dc2626"},
        {"name": "Inconclusive", "count": inconclusive, "colour": "#a1a1aa"},
    ]

    top_conditions = query_all(
        """
        SELECT plant_name AS plant,
               predicted_disease AS disease,
               COUNT(*) AS total,
               AVG(confidence) AS avg_confidence,
               MAX(created_at) AS last_seen
          FROM detection_history
         WHERE detection_status = 'diseased'
         GROUP BY plant_name, predicted_disease
         ORDER BY total DESC
         LIMIT 10
        """
    )

    return {
        "window_days": max(1, min(int(days), 365)),
        "totals": {
            "total_detections": total,
            "healthy": counts["healthy"],
            "diseased": counts["diseased"],
            "inconclusive": inconclusive,
            "test_mode_records": test_mode_record_count(),
        },
        "healthy_vs_diseased": healthy_vs_diseased,
        "disease_distribution": disease_distribution(),
        "disease_distribution_with_healthy": disease_distribution(include_healthy=True),
        "plant_distribution": plant_distribution(),
        "activity": daily_activity(days),
        "confidence_distribution": confidence_distribution(),
        "confidence": confidence_summary(),
        "sources": source_counts(),
        "camera_sources": camera_source_counts(),
        "top_conditions": [
            {
                "plant": row["plant"],
                "disease": row["disease"],
                "count": int(row["total"]),
                "avg_confidence": round(float(row["avg_confidence"] or 0.0), 4),
                "last_seen": to_iso8601(row["last_seen"]),
            }
            for row in top_conditions
        ],
        # Model evaluation metrics come from ml/reports/, written by evaluate.py.
        "model_evaluation": reports,
        "model_status": ml_service.status(),
        "is_empty": total == 0,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


__all__ = [
    "status_counts",
    "source_counts",
    "camera_source_counts",
    "disease_distribution",
    "plant_distribution",
    "daily_activity",
    "confidence_distribution",
    "confidence_summary",
    "today_count",
    "last_detection_at",
    "test_mode_record_count",
    "overview",
    "analytics",
]
