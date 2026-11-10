"""
routes/system_routes.py
=======================
Health, capability and reference endpoints.

    GET  /api                 endpoint index (handy when probing with a browser)
    GET  /api/health          backend, database, model and device status
    GET  /api/classes         plants and conditions the model can predict
    GET  /api/disease-info    static reference text for every known class
    POST /api/model/reload    re-read the model from disk after training
"""

from __future__ import annotations

import logging
import platform
import sys
import time
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify

from database.db import query_scalar
from models import device as device_model
from services.esp32_service import get_esp32_service
from services.ml_service import get_ml_service
from services.vision_service import get_vision_service
from utils.errors import NotFoundError
from utils.image_utils import directory_usage
from utils.ml_bridge import all_known_classes, get_disease_info
from utils.responses import success_response

logger = logging.getLogger(__name__)

system_bp = Blueprint("system", __name__, url_prefix="/api")

APP_NAME = "AI Plant Disease Detection API"
APP_VERSION = "1.0.0"
_STARTED_AT = time.time()


def _database_status() -> Dict[str, Any]:
    """Confirm the database answers a real query, not just that the file exists."""
    try:
        detections = int(query_scalar("SELECT COUNT(*) FROM detection_history"))
        devices = int(query_scalar("SELECT COUNT(*) FROM device_status"))
        return {
            "connected": True,
            "path": str(current_app.config["DATABASE_PATH"]),
            "detection_records": detections,
            "device_records": devices,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Database health check failed: %s", exc)
        return {
            "connected": False,
            "path": str(current_app.config["DATABASE_PATH"]),
            "detection_records": None,
            "device_records": None,
            "error": str(exc),
        }


@system_bp.route("", methods=["GET"])
@system_bp.route("/", methods=["GET"])
def api_index():
    """List the available endpoints."""
    return jsonify(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "documentation": "docs/architecture.md",
            "endpoints": {
                "GET  /api/health": "Backend, database and model status",
                "GET  /api/classes": "Supported plants and disease categories",
                "GET  /api/disease-info": "Reference text for every known class",
                "POST /api/analyze-plant": "Universal analysis - ANY plant species",
                "GET  /api/plants": "Plant species with care profiles",
                "POST /api/predict": "Classify an uploaded or pushed image (10 trained classes)",
                "POST /api/analyze": "Classify without saving",
                "POST /api/capture": "Capture from the ESP32-CAM, then classify",
                "POST /api/diagnosis": "Full diagnosis for ANY plant (alias: /api/analyze-plant)",
                "GET  /api/diseases": "Condition reference: descriptions, severity, causes",
                "GET  /api/treatments": "Treatment plans per condition",
                "GET  /api/history": "Paginated detection history",
                "GET  /api/history/<id>/report": "Download the diagnosis as a PDF",
                "GET  /api/stats": "Dashboard statistics",
                "GET  /api/analytics": "Analytics and model evaluation metrics",
                "GET  /api/cameras": "Available camera sources and their state",
                "GET  /api/device/status": "ESP32-CAM connection status",
                "GET  /api/device/config": "Effective ESP32-CAM address and its origin",
                "POST /api/device/config": "Set the ESP32-CAM IP from the dashboard",
                "POST /api/device/register": "Firmware heartbeat (device -> server)",
                "POST /api/device/status": "Alias of /api/device/register",
                "GET  /api/device/command": "Firmware command poll (device -> server)",
                "POST /api/device/upload": "Firmware image push (device -> server)",
                "POST /api/device/led": "Turn the white LED on or off",
                "POST /api/model/reload": "Reload the model from disk",
            },
        }
    )


@system_bp.route("/health", methods=["GET"])
def health():
    """
    Full system health.

    Returns HTTP 200 when the backend itself is serving, with ``data.status``
    set to ``healthy`` or ``degraded``, and 503 only when a core dependency (the
    database or the model) is unusable. That lets the dashboard distinguish
    "backend is down" from "backend is up but has no trained model".
    """
    ml_service = get_ml_service()
    esp32 = get_esp32_service()

    database = _database_status()
    model_status = ml_service.status()

    offline_after = current_app.config["ESP32_OFFLINE_AFTER_SECONDS"]
    try:
        device_model.mark_stale_devices_offline(offline_after)
        primary_device = device_model.get_primary_device(
            offline_after, current_app.config["ESP32_CAM_NAME"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Device status lookup failed during health check: %s", exc)
        primary_device = None

    problems = []
    if not database["connected"]:
        problems.append("database")
    if not model_status["can_predict"]:
        problems.append("model")

    status = "healthy" if not problems else "degraded"

    payload = {
        "status": status,
        "problems": problems,
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "uptime_seconds": round(time.time() - _STARTED_AT, 1),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "debug": bool(current_app.config.get("DEBUG")),
        },
        "database": database,
        "model": model_status,
        "universal_analysis": {
            "enabled": bool(current_app.config.get("UNIVERSAL_ANALYSIS_ENABLED", True)),
            "method": "classical computer vision + rule inference",
            "species_agnostic": True,
            "note": (
                "Lets any plant be analysed. Produces measured symptoms and a shortlist "
                "of possible conditions, not a confirmed diagnosis."
            ),
        },
        "ai_vision": get_vision_service().status(),
        "device": {
            "configured_ip": esp32.configured_ip,
            "configured_name": esp32.default_device_name,
            "resolved_ip": esp32.resolve_ip(),
            "primary": primary_device,
            "is_online": bool(primary_device and primary_device.get("is_online")),
        },
        "storage": {
            "upload_folder": str(current_app.config["UPLOAD_FOLDER"]),
            **directory_usage(current_app.config["UPLOAD_FOLDER"]),
        },
        "config": current_app.config["CONFIG_SUMMARY"],
    }

    http_status = 200 if status == "healthy" else 503
    return success_response(payload, message=model_status.get("message"), status_code=http_status)


@system_bp.route("/classes", methods=["GET"])
def classes():
    """
    Plants and conditions the loaded model can predict.

    These come from ``class_labels.json``, which is generated from the dataset's
    own folder names during training - so this list always matches what the
    network can actually output.
    """
    return success_response(get_ml_service().classes())


@system_bp.route("/disease-info", methods=["GET"])
def disease_info_all():
    """All static reference entries (descriptions, symptoms, management)."""
    entries = all_known_classes()
    return success_response(
        {
            "count": len(entries),
            "entries": entries,
            "note": (
                "Reference material shown next to a prediction. It never influences "
                "the model's output."
            ),
        }
    )


@system_bp.route("/disease-info/<path:class_name>", methods=["GET"])
def disease_info_one(class_name: str):
    info = get_disease_info(class_name)
    if not info.get("matched"):
        raise NotFoundError(
            f"No reference entry for class '{class_name}'.",
            {"known_classes": sorted(all_known_classes().keys())},
        )
    return success_response(info)


@system_bp.route("/model/reload", methods=["POST"])
def reload_model():
    """
    Reload the model from disk.

    Called after ``ml/train.py`` finishes so the running server picks up the new
    weights without a restart.
    """
    ml_service = get_ml_service()
    reloaded = ml_service.reload()
    status = ml_service.status()
    return success_response(
        {"reloaded": reloaded, "model": status},
        message=status.get("message"),
        status_code=200 if reloaded else 503,
    )


__all__ = ["system_bp", "APP_NAME", "APP_VERSION"]
