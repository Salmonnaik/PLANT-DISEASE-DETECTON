"""
routes/history_routes.py
========================
Detection history endpoints.

    GET    /api/history            paginated, filterable list
    GET    /api/history/filters    distinct values for the filter dropdowns
    GET    /api/history/<id>       one record with its full probability vector
    DELETE /api/history/<id>       delete one record and its image file
    DELETE /api/history            clear the history (requires ?confirm=true)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from flask import Blueprint, current_app, make_response, request

from models import detection as detection_model
from services.detection_service import clear_history, delete_detection_with_image
from services.report_service import (
    ReportUnavailableError,
    build_diagnosis_report,
    report_filename,
)
from utils.errors import ApiError, NotFoundError, ValidationError
from utils.responses import paginated_response, success_response

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__, url_prefix="/api/history")

ALLOWED_STATUS_FILTERS = {"all", "healthy", "diseased", "uncertain", "unknown", "inconclusive"}
ALLOWED_SOURCE_FILTERS = {"all", "upload", "esp32cam"}
ALLOWED_CAMERA_FILTERS = {"all", "laptop_webcam", "esp32_cam", "file_upload", "unknown"}


def _int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"'{name}' must be an integer, got {raw!r}.") from exc
    if value < minimum or value > maximum:
        raise ValidationError(f"'{name}' must be between {minimum} and {maximum}, got {value}.")
    return value


def _choice_arg(name: str, allowed: set[str]) -> Optional[str]:
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip().lower()
    if value not in allowed:
        raise ValidationError(
            f"'{name}' must be one of {sorted(allowed)}, got {raw!r}.",
            {"allowed": sorted(allowed)},
        )
    return value


@history_bp.route("", methods=["GET"])
def list_history():
    """Paginated detection history with search and filtering."""
    config = current_app.config
    limit = _int_arg("limit", config["HISTORY_PAGE_SIZE"], 1, config["HISTORY_MAX_PAGE_SIZE"])
    offset = _int_arg("offset", 0, 0, 10_000_000)

    sort_by = (request.args.get("sort_by") or "created_at").strip()
    if sort_by not in detection_model.SORTABLE_COLUMNS:
        raise ValidationError(
            f"'sort_by' must be one of {sorted(detection_model.SORTABLE_COLUMNS)}.",
            {"allowed": sorted(detection_model.SORTABLE_COLUMNS)},
        )

    result = detection_model.list_detections(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=(request.args.get("sort_dir") or "desc"),
        status=_choice_arg("status", ALLOWED_STATUS_FILTERS),
        source=_choice_arg("source", ALLOWED_SOURCE_FILTERS),
        camera_source=_choice_arg("camera_source", ALLOWED_CAMERA_FILTERS),
        plant=request.args.get("plant"),
        disease=request.args.get("disease"),
        search=request.args.get("search"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
        only_validated=(request.args.get("validated_only", "").lower() in ("1", "true", "yes")),
    )

    return paginated_response(
        result["items"],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@history_bp.route("/filters", methods=["GET"])
def history_filters():
    """Distinct plants, diseases and sources present in the history."""
    values = detection_model.distinct_values()
    values["statuses"] = sorted(ALLOWED_STATUS_FILTERS - {"all"})
    values["camera_source_options"] = [
        {"value": value, "label": detection_model.camera_source_label(value)}
        for value in sorted(ALLOWED_CAMERA_FILTERS - {"all"})
    ]
    values["total_records"] = detection_model.count_all()
    return success_response(values)


@history_bp.route("/<int:detection_id>", methods=["GET"])
def get_history_item(detection_id: int):
    record = detection_model.get_detection(detection_id)
    if record is None:
        raise NotFoundError(f"No detection record with id {detection_id}.")
    return success_response(record)


@history_bp.route("/<int:detection_id>/report", methods=["GET"])
def download_report(detection_id: int):
    """
    Download the diagnosis as a PDF.

    The report repeats the dashboard's caveats on purpose: a PDF gets printed
    and forwarded away from the UI that produced it, so the confidence level,
    the "not a confirmed diagnosis" statement, the limitations and the
    chemical-verification notice all have to travel with the document.
    """
    record = detection_model.get_detection(detection_id)
    if record is None:
        raise NotFoundError(f"No detection record with id {detection_id}.")

    try:
        pdf = build_diagnosis_report(
            record,
            upload_folder=Path(current_app.config["UPLOAD_FOLDER"]),
            app_version=current_app.config["CONFIG_SUMMARY"].get("version", "1.0.0"),
        )
    except ReportUnavailableError as exc:
        raise ApiError(str(exc), 503, "REPORT_UNAVAILABLE") from exc

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{report_filename(record)}"'
    )
    response.headers["Content-Length"] = str(len(pdf))
    return response


@history_bp.route("/<int:detection_id>", methods=["DELETE"])
def delete_history_item(detection_id: int):
    result = delete_detection_with_image(detection_id)
    return success_response(result, message=f"Detection #{detection_id} deleted.")


@history_bp.route("", methods=["DELETE"])
def delete_all_history():
    """
    Clear the entire history.

    Guarded by an explicit ``?confirm=true`` so a stray DELETE cannot wipe the
    record of every scan.
    """
    if (request.args.get("confirm") or "").lower() not in ("1", "true", "yes"):
        raise ValidationError(
            "Clearing the history is irreversible. Repeat the request with "
            "?confirm=true to proceed.",
        )
    delete_files = (request.args.get("delete_files") or "").lower() in ("1", "true", "yes")
    result = clear_history(delete_files=delete_files)
    return success_response(
        result,
        message=f"Removed {result['rows_deleted']} record(s) and {result['files_deleted']} image file(s).",
    )


__all__ = ["history_bp"]
