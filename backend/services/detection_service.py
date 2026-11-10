"""
services/detection_service.py
=============================
The one code path that turns image bytes into a stored, returned detection.

Both entry points - a browser upload (``POST /api/predict``) and an ESP32-CAM
frame (``POST /api/capture`` or a device push) - funnel through
:func:`analyze_and_store`, so validation, inference, file naming, database
writes and the response shape can never drift apart.

Ordering matters: the image is only written to disk *after* inference succeeds.
If no model is available the request fails without leaving an orphan file, and
an inconclusive result still gets saved because "the system could not decide" is
information the operator needs in the history.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from flask import current_app

from models import detection as detection_model
from services.ml_service import get_ml_service
from utils.errors import ModelUnavailableError, NotFoundError
from utils.image_utils import delete_image, save_image, validate_image_bytes
from utils.ml_bridge import decode_image_bytes

logger = logging.getLogger(__name__)

# Transport that delivered the bytes.
SOURCE_UPLOAD = "upload"
SOURCE_DEVICE = "esp32cam"

# Camera that actually took the picture.
CAMERA_WEBCAM = detection_model.CAMERA_SOURCE_WEBCAM
CAMERA_ESP32 = detection_model.CAMERA_SOURCE_ESP32
CAMERA_FILE = detection_model.CAMERA_SOURCE_FILE

# Wording used in validation error messages, so a rejected webcam frame says
# "webcam capture" rather than the generic "upload".
ORIGIN_LABELS = {
    CAMERA_WEBCAM: "webcam capture",
    CAMERA_ESP32: "ESP32-CAM capture",
    CAMERA_FILE: "upload",
}

# Stored-filename prefix per camera.
FILENAME_PREFIXES = {
    CAMERA_WEBCAM: "webcam",
    CAMERA_ESP32: "esp32cam",
    CAMERA_FILE: "upload",
}


def _config() -> Any:
    return current_app.config


def _prediction_from_universal(
    report: Dict[str, Any],
    threshold: Optional[float],
) -> Dict[str, Any]:
    """
    Build a classifier-shaped result from a universal analysis.

    Used when no trained model is available: the storage layer and the response
    schema both expect these fields, and inventing a shim here keeps one code
    path instead of two.

    ``confidence`` is deliberately 0.0 and ``is_validated_prediction`` False.
    The universal layer produces qualitative support levels, not probabilities,
    and putting a fabricated percentage in this field is exactly the kind of
    fake confidence the whole design avoids. Consumers read
    ``confidence_level`` instead.
    """
    plant = report.get("plant") or {}
    condition = report.get("condition") or {}
    symptoms = report.get("symptoms") or {}
    assessment = str(report.get("assessment", "insufficient_evidence"))

    status = {
        "healthy": "healthy",
        "condition_identified": "diseased",
        "symptoms_observed": "uncertain",
    }.get(assessment, "unknown")

    return {
        "success": True,
        "is_conclusive": assessment in ("healthy", "condition_identified"),
        "is_validated_prediction": False,
        "plant_name": plant.get("name") or "Unidentified plant",
        "predicted_class": condition.get("id"),
        "predicted_disease": condition.get("label") or "No assessment possible",
        "display_label": f"{plant.get('name') or 'Unidentified plant'} - {condition.get('label')}",
        "detection_status": status,
        "is_healthy": assessment == "healthy",
        "confidence": 0.0,
        "confidence_percent": 0.0,
        "confidence_threshold": threshold or 0.0,
        "reason": report.get("basis"),
        "top_predictions": [],
        "class_probabilities": [],
        "disease_info": None,
        "image_quality": {
            "passed": bool(symptoms.get("leaf_detected")),
            "issues": [],
            "metrics": (report.get("evidence_sources", {}).get("local_cv", {}).get("metrics", {})),
        },
        "model": {
            "mode": "universal_cv",
            "trained": False,
            "base_model": "classical computer vision + rule inference",
            "num_classes": 0,
        },
        "inference_ms": 0.0,
        "warnings": [
            "No trained classifier contributed to this result. It is based on measured "
            "image features and rule inference, which produces a shortlist of "
            "possibilities rather than a diagnosis."
        ],
    }


def analyze_and_store(
    data: bytes,
    *,
    source: str = SOURCE_UPLOAD,
    camera_source: Optional[str] = None,
    device_name: Optional[str] = None,
    original_filename: Optional[str] = None,
    confidence_threshold: Optional[float] = None,
    capture_info: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    persist: bool = True,
    universal: bool = False,
    declared_species: Optional[str] = None,
    use_vision_api: bool = True,
) -> Dict[str, Any]:
    """
    Validate, classify, store and return one detection.

    This is the single pipeline shared by every camera source. A laptop webcam
    frame (canvas -> JPEG -> multipart POST) and an ESP32-CAM frame (raw JPEG
    body) both arrive here as plain bytes and receive identical treatment:
    the same validation, the same preprocessing, the same model, the same
    confidence threshold and the same response shape. The only thing that
    differs is the ``camera_source`` recorded alongside the result.

    Parameters
    ----------
    data
        Raw image bytes (JPEG from either camera, or any supported upload format).
    source
        Transport that delivered the image: ``"upload"`` (HTTP from the browser)
        or ``"esp32cam"`` (pushed/pulled from the device).
    camera_source
        Which camera actually took the picture: ``laptop_webcam``, ``esp32_cam``
        or ``file_upload``. Inferred from ``source`` when not supplied.
    confidence_threshold
        Per-request override of the configured threshold.
    persist
        When False nothing is written to disk or to the database (used by the
        "analyse without saving" path).

    Raises
    ------
    ImageValidationError
        The bytes are not a usable image.
    ModelUnavailableError
        No usable model is loaded.
    """
    config = _config()
    resolved_camera_source = detection_model.normalise_camera_source(camera_source, source)

    # ---- 1. validate ----------------------------------------------------
    image_meta = validate_image_bytes(
        data,
        allowed_extensions=config["ALLOWED_EXTENSIONS"],
        max_bytes=config["MAX_CONTENT_LENGTH"],
        origin=ORIGIN_LABELS.get(resolved_camera_source, "upload"),
    )

    # ---- 2. classify ----------------------------------------------------
    ml_service = get_ml_service()
    prediction: Optional[Dict[str, Any]] = None

    if universal:
        # In universal mode the trained classifier is one evidence source among
        # several, and a missing or untrained model must not block the analysis
        # - the computer-vision layer works without it.
        try:
            prediction = ml_service.predict(data, confidence_threshold=confidence_threshold)
        except ModelUnavailableError as exc:
            logger.info(
                "Universal analysis proceeding without the classifier: %s", exc.message
            )
    else:
        prediction = ml_service.predict(data, confidence_threshold=confidence_threshold)

    # ---- 2b. universal, species-agnostic analysis -----------------------
    universal_report: Optional[Dict[str, Any]] = None
    if universal:
        from services.analysis_service import analyse_plant_image  # noqa: PLC0415

        image_array = decode_image_bytes(data)
        universal_report = analyse_plant_image(
            data,
            image_array,
            declared_species=declared_species,
            use_vision_api=use_vision_api,
            classifier_result=prediction,
            mime_type=f"image/{'jpeg' if image_meta['format'] == 'jpg' else image_meta['format']}",
        )

        # Synthesise the classifier-shaped fields the rest of the pipeline and
        # the history table expect, so one storage path serves both modes.
        if prediction is None:
            prediction = _prediction_from_universal(universal_report, confidence_threshold)

    # ---- 3. store the image --------------------------------------------
    stored: Optional[Dict[str, Any]] = None
    detection_id: Optional[int] = None

    if persist and config.get("KEEP_UPLOADED_IMAGES", True):
        # The filename prefix records the camera in the file name itself, so
        # the uploads folder stays readable without consulting the database.
        stored = save_image(
            data,
            upload_folder=Path(config["UPLOAD_FOLDER"]),
            prefix=FILENAME_PREFIXES.get(resolved_camera_source, "upload"),
            extension=image_meta["format"],
            original_filename=original_filename,
        )

    # ---- 4. record it ---------------------------------------------------
    if persist:
        try:
            detection_id = detection_model.create_from_prediction(
                prediction,
                image_path=(stored or {}).get("relative_path", ""),
                image_filename=(stored or {}).get("filename") or original_filename,
                image_size_bytes=image_meta["size_bytes"],
                source=source,
                camera_source=resolved_camera_source,
                device_name=device_name,
                notes=notes,
                universal=universal_report,
            )
        except Exception:
            # Don't leave a saved file with no row pointing at it.
            if stored:
                delete_image(Path(config["UPLOAD_FOLDER"]), stored["relative_path"])
            raise

    record = detection_model.get_detection(detection_id) if detection_id else None

    if universal_report:
        logger.info(
            "Universal analysis: camera=%s plant=%s (%s) condition=%s confidence=%s (%s)",
            resolved_camera_source,
            (universal_report.get("plant") or {}).get("name"),
            (universal_report.get("plant") or {}).get("identification_source"),
            (universal_report.get("condition") or {}).get("label"),
            universal_report.get("confidence_level"),
            f"record #{detection_id}" if detection_id else "not persisted",
        )
    else:
        logger.info(
            "Detection complete: camera=%s status=%s label=%s confidence=%.1f%% (%s)",
            resolved_camera_source,
            prediction["detection_status"],
            prediction.get("display_label"),
            prediction["confidence"] * 100,
            f"record #{detection_id}" if detection_id else "not persisted",
        )

    return {
        "detection_id": detection_id,
        "prediction": prediction,
        "detection": record,
        "image": {
            "url": (stored or {}).get("url"),
            "path": (stored or {}).get("relative_path"),
            "filename": (stored or {}).get("filename") or original_filename,
            "format": image_meta["format"],
            "width": image_meta["width"],
            "height": image_meta["height"],
            "size_bytes": image_meta["size_bytes"],
            "sha256": image_meta["sha256"],
            "stored": stored is not None,
        },
        "capture": capture_info,
        "source": source,
        "camera_source": resolved_camera_source,
        "camera_source_label": detection_model.camera_source_label(resolved_camera_source),
        "analysis_mode": "universal" if universal else "classifier",
        "analysis": universal_report,
        "model_mode": prediction.get("model", {}).get("mode"),
        "is_validated_prediction": prediction.get("is_validated_prediction", False),
    }


def delete_detection_with_image(detection_id: int) -> Dict[str, Any]:
    """Remove a history record together with its stored image file."""
    image_path = detection_model.delete_detection(detection_id)
    if image_path is None:
        raise NotFoundError(f"No detection record with id {detection_id}.")

    removed = delete_image(Path(_config()["UPLOAD_FOLDER"]), image_path)
    return {"id": detection_id, "image_path": image_path, "image_file_removed": removed}


def clear_history(delete_files: bool = False) -> Dict[str, Any]:
    """
    Delete every history record, optionally removing the image files too.

    Used by the History page's "clear history" action; the route requires an
    explicit confirmation flag before calling this.
    """
    upload_folder = Path(_config()["UPLOAD_FOLDER"])
    paths = [
        row["image_path"]
        for row in detection_model.list_detections(limit=100000, offset=0)["items"]
        if row.get("image_path")
    ]
    removed_rows = detection_model.delete_all_detections()

    removed_files = 0
    if delete_files:
        for path in paths:
            if delete_image(upload_folder, path):
                removed_files += 1

    logger.warning("History cleared: %d rows, %d image files.", removed_rows, removed_files)
    return {"rows_deleted": removed_rows, "files_deleted": removed_files}


__all__ = [
    "SOURCE_UPLOAD",
    "SOURCE_DEVICE",
    "CAMERA_WEBCAM",
    "CAMERA_ESP32",
    "CAMERA_FILE",
    "analyze_and_store",
    "delete_detection_with_image",
    "clear_history",
]
