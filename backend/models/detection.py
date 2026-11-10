"""
models/detection.py
===================
Data access for the ``detection_history`` table.

Every function here takes and returns plain dictionaries so that route handlers
never touch SQL and the JSON shape sent to the dashboard is defined in one
place (:func:`to_api_dict`).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from database.db import (
    execute,
    insert_returning_id,
    query_all,
    query_one,
    query_scalar,
    to_iso8601,
    utc_now_string,
)
from database.migrations import (
    CAMERA_SOURCE_ESP32,
    CAMERA_SOURCE_FILE,
    CAMERA_SOURCE_UNKNOWN,
    CAMERA_SOURCE_WEBCAM,
    VALID_CAMERA_SOURCES,
)

logger = logging.getLogger(__name__)

VALID_STATUSES = ("healthy", "diseased", "uncertain", "unknown")
VALID_SOURCES = ("upload", "esp32cam")
VALID_MODEL_MODES = ("trained", "test")

# Human-readable name per camera source, used by the API and the dashboard so
# the wording is identical everywhere.
CAMERA_SOURCE_LABELS = {
    CAMERA_SOURCE_WEBCAM: "Laptop webcam",
    CAMERA_SOURCE_ESP32: "ESP32-CAM",
    CAMERA_SOURCE_FILE: "File upload",
    CAMERA_SOURCE_UNKNOWN: "Unknown source",
}


def camera_source_label(camera_source: Optional[str]) -> str:
    return CAMERA_SOURCE_LABELS.get(str(camera_source or ""), CAMERA_SOURCE_LABELS[CAMERA_SOURCE_UNKNOWN])


def normalise_camera_source(
    camera_source: Optional[str],
    transport_source: str = "upload",
) -> str:
    """
    Resolve the camera source, falling back to what the transport implies.

    Accepts a few spellings a client might send (``webcam``, ``esp32cam``)
    because the value arrives from a browser form field, and an unrecognised
    string should not become an unqueryable value in the database.
    """
    if camera_source:
        candidate = str(camera_source).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "webcam": CAMERA_SOURCE_WEBCAM,
            "laptop": CAMERA_SOURCE_WEBCAM,
            "laptop_webcam": CAMERA_SOURCE_WEBCAM,
            "browser": CAMERA_SOURCE_WEBCAM,
            "esp32": CAMERA_SOURCE_ESP32,
            "esp32cam": CAMERA_SOURCE_ESP32,
            "esp32_cam": CAMERA_SOURCE_ESP32,
            "upload": CAMERA_SOURCE_FILE,
            "file": CAMERA_SOURCE_FILE,
            "file_upload": CAMERA_SOURCE_FILE,
        }
        resolved = aliases.get(candidate)
        if resolved:
            return resolved
        if candidate in VALID_CAMERA_SOURCES:
            return candidate
        logger.warning(
            "Unrecognised camera_source %r; recording it as %r instead.",
            camera_source,
            CAMERA_SOURCE_UNKNOWN,
        )
        return CAMERA_SOURCE_UNKNOWN

    # No explicit value: infer from the transport that delivered the image.
    return CAMERA_SOURCE_ESP32 if transport_source == "esp32cam" else CAMERA_SOURCE_FILE

SORTABLE_COLUMNS = {
    "created_at": "created_at",
    "confidence": "confidence",
    "plant_name": "plant_name",
    "predicted_disease": "predicted_disease",
    "id": "id",
}


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #

def _loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def to_api_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a database row into the JSON object the frontend consumes."""
    image_path = row.get("image_path") or ""
    return {
        "id": row["id"],
        "image_path": image_path,
        # Served by the /uploads/<path> static route registered in app.py.
        "image_url": f"/uploads/{image_path}" if image_path else None,
        "image_filename": row.get("image_filename"),
        "image_size_bytes": row.get("image_size_bytes"),
        "plant_name": row.get("plant_name"),
        "predicted_disease": row.get("predicted_disease"),
        "predicted_class": row.get("predicted_class"),
        "confidence": round(float(row.get("confidence") or 0.0), 4),
        "confidence_percent": round(float(row.get("confidence") or 0.0) * 100.0, 2),
        "confidence_threshold": row.get("confidence_threshold"),
        "detection_status": row.get("detection_status"),
        "is_healthy": row.get("detection_status") == "healthy",
        "is_conclusive": bool(row.get("is_conclusive", 1)),
        "is_validated": bool(row.get("is_validated", 1)),
        "model_mode": row.get("model_mode", "trained"),
        "source": row.get("source", "upload"),
        "camera_source": row.get("camera_source") or CAMERA_SOURCE_UNKNOWN,
        "camera_source_label": camera_source_label(row.get("camera_source")),
        "device_name": row.get("device_name"),
        "inference_ms": row.get("inference_ms"),
        "probabilities": _loads(row.get("probabilities"), []),
        "image_quality": _loads(row.get("image_quality"), None),
        "notes": row.get("notes"),
        "created_at": to_iso8601(row.get("created_at")),
        # Universal analysis (null on records created by the classifier path).
        "plant_species": row.get("plant_species"),
        "species_source": row.get("species_source"),
        "analysis_mode": row.get("analysis_mode") or "classifier",
        "confidence_level": row.get("confidence_level"),
        "analysis": _loads(row.get("analysis"), None),
        "symptoms": _loads(row.get("symptoms"), []),
    }


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def create_detection(
    *,
    image_path: str,
    plant_name: str,
    predicted_disease: str,
    confidence: float,
    detection_status: str,
    predicted_class: Optional[str] = None,
    source: str = "upload",
    camera_source: Optional[str] = None,
    device_name: Optional[str] = None,
    image_filename: Optional[str] = None,
    image_size_bytes: Optional[int] = None,
    model_mode: str = "trained",
    is_validated: bool = True,
    is_conclusive: bool = True,
    confidence_threshold: Optional[float] = None,
    inference_ms: Optional[float] = None,
    probabilities: Optional[List[Dict[str, Any]]] = None,
    image_quality: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    plant_species: Optional[str] = None,
    species_source: Optional[str] = None,
    analysis_mode: str = "classifier",
    confidence_level: Optional[str] = None,
    analysis: Optional[Dict[str, Any]] = None,
    symptoms: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Insert one detection record and return its new id.

    Values are normalised to satisfy the schema's CHECK constraints so a bad
    status string surfaces here as a clear error rather than as a SQLite
    IntegrityError deep inside a request.
    """
    status = str(detection_status).lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"detection_status must be one of {VALID_STATUSES}, got {status!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}, got {source!r}")
    if model_mode not in VALID_MODEL_MODES:
        raise ValueError(f"model_mode must be one of {VALID_MODEL_MODES}, got {model_mode!r}")

    safe_confidence = min(1.0, max(0.0, float(confidence)))
    resolved_camera_source = normalise_camera_source(camera_source, source)

    detection_id = insert_returning_id(
        """
        INSERT INTO detection_history (
            image_path, plant_name, predicted_disease, confidence, detection_status,
            created_at, predicted_class, source, camera_source, device_name,
            image_filename, image_size_bytes, model_mode, is_validated, is_conclusive,
            confidence_threshold, inference_ms, probabilities, image_quality, notes,
            plant_species, species_source, analysis_mode, confidence_level,
            analysis, symptoms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?)
        """,
        (
            image_path,
            plant_name,
            predicted_disease,
            safe_confidence,
            status,
            utc_now_string(),
            predicted_class,
            source,
            resolved_camera_source,
            device_name,
            image_filename,
            image_size_bytes,
            model_mode,
            1 if is_validated else 0,
            1 if is_conclusive else 0,
            confidence_threshold,
            inference_ms,
            json.dumps(probabilities) if probabilities is not None else None,
            json.dumps(image_quality) if image_quality is not None else None,
            notes,
            plant_species,
            species_source,
            analysis_mode,
            confidence_level,
            json.dumps(analysis) if analysis is not None else None,
            json.dumps(symptoms) if symptoms is not None else None,
        ),
    )
    logger.info(
        "Detection #%d saved: %s / %s (%.1f%%, %s, camera=%s, model=%s)",
        detection_id,
        plant_name,
        predicted_disease,
        safe_confidence * 100,
        status,
        resolved_camera_source,
        model_mode,
    )
    return detection_id


def create_from_prediction(
    prediction: Dict[str, Any],
    *,
    image_path: str,
    image_filename: Optional[str] = None,
    image_size_bytes: Optional[int] = None,
    source: str = "upload",
    camera_source: Optional[str] = None,
    device_name: Optional[str] = None,
    notes: Optional[str] = None,
    universal: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Persist a result produced by ``PlantDiseasePredictor.predict``.

    Inconclusive results are stored too: an "uncertain" or "unknown" outcome is
    real information for the operator, and dropping those rows would make the
    dashboard look more confident than the system actually is.
    """
    conclusive = bool(prediction.get("is_conclusive"))
    model_info = prediction.get("model") or {}
    model_mode = "trained" if model_info.get("trained") else "test"

    # When a universal analysis ran, its conclusions take precedence for the
    # headline columns: it may have identified a species the classifier cannot
    # represent, and storing "Unknown" there would lose that information.
    plant_name = prediction.get("plant_name") or "Unknown"
    predicted_disease = prediction.get("predicted_disease") or "Unknown"
    detection_status = prediction.get("detection_status") or "unknown"
    plant_species: Optional[str] = None
    species_source: Optional[str] = None
    analysis_mode = "classifier"
    confidence_level: Optional[str] = None
    symptoms: Optional[List[Dict[str, Any]]] = None

    if universal:
        analysis_mode = "universal"
        plant_block = universal.get("plant") or {}
        condition_block = universal.get("condition") or {}
        symptom_block = universal.get("symptoms") or {}

        plant_species = plant_block.get("name")
        species_source = plant_block.get("identification_source")
        confidence_level = universal.get("confidence_level")
        symptoms = symptom_block.get("detected") or []

        if plant_block.get("identified") and plant_species:
            plant_name = str(plant_species)
        if condition_block.get("label"):
            predicted_disease = str(condition_block["label"])

        # Map the universal assessment onto the existing status vocabulary so
        # the column's CHECK constraint and every existing query still hold.
        assessment = str(universal.get("assessment", ""))
        if assessment == "healthy":
            detection_status = "healthy"
        elif assessment == "condition_identified":
            detection_status = "diseased"
        elif assessment == "symptoms_observed":
            # Symptoms are real but the cause is a shortlist, not a diagnosis.
            detection_status = "uncertain"
        else:
            detection_status = "unknown"

    return create_detection(
        image_path=image_path,
        plant_name=plant_name,
        predicted_disease=predicted_disease,
        confidence=float(prediction.get("confidence") or 0.0),
        detection_status=detection_status,
        predicted_class=prediction.get("predicted_class"),
        source=source,
        camera_source=camera_source,
        device_name=device_name,
        image_filename=image_filename,
        image_size_bytes=image_size_bytes,
        model_mode=model_mode,
        is_validated=bool(prediction.get("is_validated_prediction")),
        is_conclusive=conclusive,
        confidence_threshold=prediction.get("confidence_threshold"),
        inference_ms=prediction.get("inference_ms"),
        probabilities=(prediction.get("top_predictions") or [])[:5],
        image_quality=prediction.get("image_quality"),
        notes=notes or prediction.get("reason"),
        plant_species=plant_species,
        species_source=species_source,
        analysis_mode=analysis_mode,
        confidence_level=confidence_level,
        analysis=universal,
        symptoms=symptoms,
    )


def delete_detection(detection_id: int) -> Optional[str]:
    """Delete one record. Returns the stored ``image_path`` so the file can be removed."""
    row = query_one("SELECT image_path FROM detection_history WHERE id = ?", (detection_id,))
    if row is None:
        return None
    execute("DELETE FROM detection_history WHERE id = ?", (detection_id,))
    logger.info("Detection #%d deleted.", detection_id)
    return row.get("image_path")


def delete_all_detections() -> int:
    """Clear the history table. Returns the number of removed rows."""
    total = int(query_scalar("SELECT COUNT(*) FROM detection_history"))
    execute("DELETE FROM detection_history")
    return total


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def get_detection(detection_id: int) -> Optional[Dict[str, Any]]:
    row = query_one("SELECT * FROM detection_history WHERE id = ?", (detection_id,))
    return to_api_dict(row) if row else None


def _build_filters(
    status: Optional[str] = None,
    plant: Optional[str] = None,
    disease: Optional[str] = None,
    source: Optional[str] = None,
    camera_source: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    only_validated: bool = False,
) -> Tuple[str, List[Any]]:
    """Compose a parameterised WHERE clause (no string interpolation of values)."""
    clauses: List[str] = []
    params: List[Any] = []

    if status and status.lower() != "all":
        if status.lower() == "inconclusive":
            clauses.append("detection_status IN ('uncertain', 'unknown')")
        else:
            clauses.append("detection_status = ?")
            params.append(status.lower())

    if plant and plant.lower() != "all":
        clauses.append("plant_name = ?")
        params.append(plant)

    if disease and disease.lower() != "all":
        clauses.append("predicted_disease = ?")
        params.append(disease)

    if source and source.lower() != "all":
        clauses.append("source = ?")
        params.append(source.lower())

    if camera_source and str(camera_source).lower() != "all":
        clauses.append("camera_source = ?")
        params.append(normalise_camera_source(camera_source))

    if only_validated:
        clauses.append("is_validated = 1")

    if search:
        clauses.append(
            "(plant_name LIKE ? OR predicted_disease LIKE ? OR predicted_class LIKE ?"
            " OR COALESCE(device_name, '') LIKE ?)"
        )
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern, pattern, pattern])

    if date_from:
        clauses.append("date(created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(created_at) <= date(?)")
        params.append(date_to)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_detections(
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    **filters: Any,
) -> Dict[str, Any]:
    """Paginated, filtered history query. Returns ``{items, total, limit, offset}``."""
    where, params = _build_filters(**filters)

    total = int(query_scalar(f"SELECT COUNT(*) FROM detection_history{where}", params))

    column = SORTABLE_COLUMNS.get(sort_by, "created_at")
    direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    rows = query_all(
        f"SELECT * FROM detection_history{where} "
        f"ORDER BY {column} {direction}, id {direction} LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )

    return {
        "items": [to_api_dict(row) for row in rows],
        "total": total,
        "limit": int(limit),
        "offset": int(offset),
        "has_more": offset + len(rows) < total,
    }


def recent_detections(limit: int = 5) -> List[Dict[str, Any]]:
    rows = query_all(
        "SELECT * FROM detection_history ORDER BY created_at DESC, id DESC LIMIT ?",
        (int(limit),),
    )
    return [to_api_dict(row) for row in rows]


def distinct_values() -> Dict[str, List[str]]:
    """Distinct plants / diseases actually present in the history, for filter dropdowns."""
    plants = [
        row["plant_name"]
        for row in query_all(
            "SELECT DISTINCT plant_name FROM detection_history "
            "WHERE plant_name IS NOT NULL ORDER BY plant_name"
        )
    ]
    diseases = [
        row["predicted_disease"]
        for row in query_all(
            "SELECT DISTINCT predicted_disease FROM detection_history "
            "WHERE predicted_disease IS NOT NULL ORDER BY predicted_disease"
        )
    ]
    sources = [
        row["source"]
        for row in query_all("SELECT DISTINCT source FROM detection_history ORDER BY source")
    ]
    camera_sources = [
        {
            "value": row["camera_source"],
            "label": camera_source_label(row["camera_source"]),
            "count": int(row["total"]),
        }
        for row in query_all(
            "SELECT camera_source, COUNT(*) AS total FROM detection_history "
            "WHERE camera_source IS NOT NULL GROUP BY camera_source ORDER BY total DESC"
        )
    ]
    return {
        "plants": plants,
        "diseases": diseases,
        "sources": sources,
        "camera_sources": camera_sources,
    }


def count_all() -> int:
    return int(query_scalar("SELECT COUNT(*) FROM detection_history"))


__all__ = [
    "VALID_STATUSES",
    "VALID_SOURCES",
    "VALID_CAMERA_SOURCES",
    "CAMERA_SOURCE_WEBCAM",
    "CAMERA_SOURCE_ESP32",
    "CAMERA_SOURCE_FILE",
    "CAMERA_SOURCE_LABELS",
    "camera_source_label",
    "normalise_camera_source",
    "to_api_dict",
    "create_detection",
    "create_from_prediction",
    "delete_detection",
    "delete_all_detections",
    "get_detection",
    "list_detections",
    "recent_detections",
    "distinct_values",
    "count_all",
]
