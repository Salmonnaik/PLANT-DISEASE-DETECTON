"""
routes/camera_routes.py
=======================
Camera source discovery for the Camera Management page.

    GET /api/cameras  describe every available camera source and its state

Why a dedicated endpoint: the two sources are fundamentally asymmetric and the
UI needs to know how. The ESP32-CAM is a network device the *backend* talks to,
so only the server can report whether it is reachable. The laptop webcam is
owned by the *browser* - the Flask process has no access to it and must not
pretend otherwise - so this endpoint reports its availability as
"browser-managed" and the frontend determines the rest through
``navigator.mediaDevices``.

Both sources feed the identical prediction pipeline; this endpoint only
describes how an image gets *to* that pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from flask import Blueprint, current_app, request

from database.db import query_all
from models import detection as detection_model
from models import device as device_model
from services.esp32_service import get_esp32_service
from services.ml_service import get_ml_service
from utils.errors import NotFoundError
from utils.responses import success_response

logger = logging.getLogger(__name__)

camera_bp = Blueprint("cameras", __name__, url_prefix="/api")


def _usage_counts() -> Dict[str, int]:
    """How many stored detections came from each camera."""
    try:
        return {
            str(row["camera_source"]): int(row["total"])
            for row in query_all(
                "SELECT camera_source, COUNT(*) AS total FROM detection_history "
                "GROUP BY camera_source"
            )
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read camera usage counts: %s", exc)
        return {}


@camera_bp.route("/diseases", methods=["GET"])
def list_diseases():
    """
    Every condition the system can shortlist, with its clinical reference.

    Includes the non-disease entries (scorch, nutrient deficiency, pest damage,
    senescence) because the diagnosis layer treats them as first-class
    explanations - damage is not assumed to be infection.
    """
    from utils.ml_bridge import all_conditions, cause_categories, severity_scale  # noqa: PLC0415

    conditions = all_conditions()
    return success_response(
        {
            "count": len(conditions),
            "diseases": conditions,
            "severity_scale": severity_scale(),
            "cause_categories": cause_categories(),
            "note": (
                "Reference material shown alongside an assessment. It never influences "
                "what the analysis finds."
            ),
        }
    )


@camera_bp.route("/treatments", methods=["GET"])
def list_treatments():
    """
    Treatment plans per condition.

    Filter with ``?condition=early_blight``. Chemical entries name documented
    active-ingredient classes only - no product names and no dosages anywhere -
    and each carries ``requires_verification`` plus the shared disclaimer,
    because registration differs by country and only the label is
    authoritative.
    """
    from utils.ml_bridge import all_treatments  # noqa: PLC0415

    treatments = all_treatments()
    requested = (request.args.get("condition") or "").strip().lower()
    if requested:
        treatments = [item for item in treatments if item["condition_id"] == requested]
        if not treatments:
            raise NotFoundError(
                f"No treatment plan for condition '{requested}'.",
                {"available": [item["condition_id"] for item in all_treatments()]},
            )

    return success_response(
        {
            "count": len(treatments),
            "treatments": treatments,
            "policy": {
                "no_product_names": True,
                "no_dosages": True,
                "withheld_when_uncertain": True,
                "note": (
                    "Chemical guidance is withheld entirely when an assessment is not "
                    "confident. Cultural and organic measures are shown instead, because "
                    "they are safe whether or not the diagnosis is correct."
                ),
            },
        }
    )


@camera_bp.route("/plants", methods=["GET"])
def list_plants():
    """
    Plant species with a care profile, for the dashboard's species picker.

    Declaring the species is the most reliable way the system learns what plant
    it is looking at - more reliable than either the 10-class classifier or an
    AI vision guess - so this list is offered prominently in the UI. A plant
    that is not listed can still be analysed; it simply gets generic care
    guidance.
    """
    from services.analysis_service import available_species  # noqa: PLC0415
    from services.vision_service import get_vision_service  # noqa: PLC0415

    species = available_species()
    return success_response(
        {
            "count": len(species),
            "species": species,
            "categories": sorted({item["category"] for item in species}),
            "supports_unlisted": True,
            "unlisted_note": (
                "Any plant can be analysed. Species not in this list receive general "
                "plant-care guidance instead of species-specific advice."
            ),
            "classifier_species": ["tomato", "potato", "pepper"],
            "classifier_note": (
                "The trained MobileNetV2 classifier covers only these three crops. For "
                "any other plant the analysis uses computer-vision symptom measurement "
                "and rule inference instead of forcing a classifier label."
            ),
            "ai_vision": get_vision_service().status(),
        }
    )


@camera_bp.route("/cameras", methods=["GET"])
def list_cameras():
    """
    Describe the camera sources this installation supports.

    Pass ``?ping=true`` to additionally probe the ESP32-CAM. The probe is
    opt-in because it blocks for up to ``ESP32_STATUS_TIMEOUT`` seconds.
    """
    config = current_app.config
    esp32 = get_esp32_service()
    ml_service = get_ml_service()

    usage = _usage_counts()
    should_ping = (request.args.get("ping") or "").lower() in ("1", "true", "yes")

    # ---- ESP32-CAM ------------------------------------------------------
    device_model.mark_stale_devices_offline(int(config["ESP32_OFFLINE_AFTER_SECONDS"]))
    device = device_model.get_primary_device(
        int(config["ESP32_OFFLINE_AFTER_SECONDS"]), config["ESP32_CAM_NAME"]
    )
    addresses = esp32.address_sources(config["ESP32_CAM_NAME"])

    probe = esp32.ping(device_name=config["ESP32_CAM_NAME"]) if should_ping else None

    esp32_camera: Dict[str, Any] = {
        "id": detection_model.CAMERA_SOURCE_ESP32,
        "label": "ESP32-CAM",
        "description": (
            "AI Thinker ESP32-CAM with an OV2640 sensor and a white illumination LED. "
            "Captures over Wi-Fi and uploads the JPEG to this backend by HTTP."
        ),
        "managed_by": "backend",
        "enabled": bool(config["ENABLE_ESP32_SOURCE"]),
        "available": bool(device and device["is_online"]),
        "status": "online" if (device and device["is_online"]) else "offline",
        "device": device,
        "addresses": addresses,
        "effective_address": addresses["effective"],
        "base_url": esp32.base_url(addresses["effective"]),
        "supports_led": True,
        "supports_remote_capture": True,
        "push_fallback_enabled": bool(config["ENABLE_PUSH_CAPTURE_FALLBACK"]),
        "live_probe": probe,
        "detections_recorded": usage.get(detection_model.CAMERA_SOURCE_ESP32, 0),
        "capture_endpoint": "/api/capture",
        "requirements": [
            "Board flashed with esp32cam/plant_disease_camera.ino",
            "Board and server on the same Wi-Fi network (2.4 GHz)",
            "5V supply able to deliver at least 500 mA",
        ],
    }

    # ---- Laptop webcam --------------------------------------------------
    webcam_camera: Dict[str, Any] = {
        "id": detection_model.CAMERA_SOURCE_WEBCAM,
        "label": "Laptop webcam",
        "description": (
            "The built-in or USB webcam on the machine viewing this dashboard. "
            "Captured in the browser with the MediaDevices API, drawn to a canvas "
            "and posted to this backend as a JPEG."
        ),
        # The browser owns this device; the backend cannot enumerate or open it.
        "managed_by": "browser",
        "enabled": bool(config["ENABLE_WEBCAM_SOURCE"]),
        "available": None,
        "status": "browser_managed",
        "supports_led": False,
        "supports_remote_capture": False,
        "detections_recorded": usage.get(detection_model.CAMERA_SOURCE_WEBCAM, 0),
        "capture_endpoint": "/api/predict",
        "requirements": [
            "A browser with MediaDevices support (Chrome, Edge, Firefox, Safari)",
            "Camera permission granted to this site",
            "A secure context: localhost, or HTTPS on a remote host",
        ],
        "notes": (
            "Browsers only expose a camera on a secure context. http://localhost "
            "counts as secure; opening the dashboard over plain HTTP from another "
            "machine's IP address does not, and the browser will refuse access."
        ),
    }

    cameras: List[Dict[str, Any]] = [webcam_camera, esp32_camera]

    return success_response(
        {
            "cameras": cameras,
            "default_camera_source": config["DEFAULT_CAMERA_SOURCE"],
            "valid_camera_sources": list(config["CAMERA_SOURCES"]),
            "file_upload": {
                "id": detection_model.CAMERA_SOURCE_FILE,
                "label": "File upload",
                "description": "An existing image file chosen from this computer.",
                "enabled": True,
                "detections_recorded": usage.get(detection_model.CAMERA_SOURCE_FILE, 0),
                "capture_endpoint": "/api/predict",
            },
            # Identical for every source - stated here so the UI can show that
            # switching cameras does not change the model or its settings.
            "shared_pipeline": {
                "endpoint": "/api/predict",
                "model": ml_service.status().get("base_model"),
                "model_mode": ml_service.status().get("mode"),
                "num_classes": ml_service.status().get("num_classes"),
                "image_size": ml_service.status().get("image_size"),
                "input_scaling": ml_service.status().get("input_scaling"),
                "confidence_threshold": ml_service.confidence_threshold,
                "quality_gate_enabled": bool(config["ENFORCE_QUALITY_GATE"]),
            },
        }
    )


__all__ = ["camera_bp"]
