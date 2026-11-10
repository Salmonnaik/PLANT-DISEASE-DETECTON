"""
routes/detection_routes.py
==========================
The detection endpoints.

    POST /api/predict   classify an uploaded (or pushed) image
    POST /api/capture   ask the ESP32-CAM for a frame, then classify it
    POST /api/analyze   classify without writing anything to disk or the DB

``/api/predict`` accepts three request shapes so the same endpoint serves the
browser and the firmware:

1. ``multipart/form-data`` with an ``image`` file part - what the dashboard sends.
2. a raw body with ``Content-Type: image/jpeg`` - what the ESP32-CAM sends,
   because streaming a multipart body from an 8-bit MCU is needless work.
3. JSON ``{"image_base64": "..."}`` - convenient for scripted tests.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, current_app, request

from models import detection as detection_model
from models import device as device_model
from services.detection_service import (
    SOURCE_DEVICE,
    SOURCE_UPLOAD,
    analyze_and_store,
)
from services.esp32_service import get_esp32_service
from utils.errors import ImageValidationError, ValidationError
from utils.responses import success_response

logger = logging.getLogger(__name__)

detection_bp = Blueprint("detection", __name__, url_prefix="/api")

RAW_IMAGE_CONTENT_TYPES = ("image/jpeg", "image/jpg", "image/png", "image/bmp", "image/webp")
FILE_FIELD_NAMES = ("image", "file", "photo", "leaf")


# --------------------------------------------------------------------------- #
# Request parsing
# --------------------------------------------------------------------------- #

def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _parse_threshold(raw: Any) -> Optional[float]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"'threshold' must be a number between 0 and 1, got {raw!r}.") from exc
    if not 0.0 < value <= 1.0:
        raise ValidationError(f"'threshold' must be greater than 0 and at most 1, got {value}.")
    return value


def _request_options() -> Dict[str, Any]:
    """Collect options from the query string, form fields or JSON body."""
    body: Dict[str, Any] = {}
    if request.is_json:
        candidate = request.get_json(silent=True)
        if isinstance(candidate, dict):
            body = candidate

    def pick(name: str) -> Any:
        if name in request.args:
            return request.args.get(name)
        if name in request.form:
            return request.form.get(name)
        return body.get(name)

    return {
        "threshold": _parse_threshold(pick("threshold")),
        "save": _parse_bool(pick("save"), True),
        "led": _parse_bool(pick("led"), True),
        "device_name": pick("device") or pick("device_name"),
        "ip_address": pick("ip") or pick("ip_address"),
        "camera_source": pick("camera_source") or pick("camera"),
        "plant_species": pick("plant_species") or pick("species") or pick("plant"),
        "use_vision_api": _parse_bool(pick("use_vision_api"), True),
        "notes": pick("notes"),
        "body": body,
    }


def _extract_image_bytes(options: Dict[str, Any]) -> Tuple[bytes, Optional[str], str]:
    """
    Pull image bytes out of whichever request shape was used.

    Returns ``(data, original_filename, transport)``.
    """
    # 1. multipart file part
    for field in FILE_FIELD_NAMES:
        if field in request.files:
            file_storage = request.files[field]
            if file_storage and file_storage.filename:
                data = file_storage.read()
                if not data:
                    raise ImageValidationError(
                        f"The uploaded file '{file_storage.filename}' is empty (0 bytes)."
                    )
                return data, file_storage.filename, "multipart"

    # 2. raw image body (ESP32-CAM)
    content_type = (request.content_type or "").split(";")[0].strip().lower()
    if content_type in RAW_IMAGE_CONTENT_TYPES:
        data = request.get_data(cache=False)
        if not data:
            raise ImageValidationError(
                "The request declared an image Content-Type but the body was empty. "
                "The camera's frame buffer grab probably failed."
            )
        return data, None, "raw"

    # 3. base64 in a JSON body
    encoded = options["body"].get("image_base64") or options["body"].get("image")
    if isinstance(encoded, str) and encoded.strip():
        payload = encoded.split(",", 1)[1] if encoded.startswith("data:") else encoded
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageValidationError(f"'image_base64' is not valid base64: {exc}") from exc
        if not data:
            raise ImageValidationError("'image_base64' decoded to zero bytes.")
        return data, options["body"].get("filename"), "base64"

    raise ValidationError(
        "No image was found in the request. Send one of:\n"
        "  - multipart/form-data with an 'image' file field (dashboard upload),\n"
        "  - a raw body with Content-Type: image/jpeg (ESP32-CAM push),\n"
        "  - JSON {\"image_base64\": \"...\"}.",
        {
            "received_content_type": request.content_type,
            "received_files": list(request.files.keys()),
            "content_length": request.content_length,
        },
    )


def _resolve_camera_source(
    requested: Optional[Any],
    transport_source: str,
    transport: str,
) -> str:
    """
    Decide which camera to credit for this image.

    An explicit ``camera_source`` from the client wins, but it is validated
    against the allowed list first - a client must not be able to write an
    arbitrary string into a column the dashboard filters on. Without one, the
    transport decides: a raw body from the device is the ESP32-CAM, a multipart
    file is a file upload.
    """
    allowed = set(current_app.config.get("CAMERA_SOURCES", ()))

    if requested:
        normalised = detection_model.normalise_camera_source(str(requested), transport_source)
        if normalised not in allowed:
            raise ValidationError(
                f"'camera_source' must be one of {sorted(allowed)}, got {requested!r}.",
                {"allowed": sorted(allowed)},
            )
        return normalised

    if transport_source == SOURCE_DEVICE or transport == "raw":
        return detection_model.CAMERA_SOURCE_ESP32
    return detection_model.CAMERA_SOURCE_FILE


def _infer_source(transport: str, explicit: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Decide whether this image came from the camera or a browser upload.

    A raw-body POST carrying ``X-Device-Name`` is the firmware; anything else is
    treated as an operator upload.
    """
    device_header = request.headers.get("X-Device-Name")
    if explicit in (SOURCE_UPLOAD, SOURCE_DEVICE):
        return explicit, device_header
    if transport == "raw" or device_header:
        return SOURCE_DEVICE, device_header or current_app.config["ESP32_CAM_NAME"]
    return SOURCE_UPLOAD, None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@detection_bp.route("/predict", methods=["POST"])
def predict():
    """
    Classify a leaf image and store the result in the detection history.

    Used by every camera source. Send ``camera_source`` to record which camera
    took the picture:

        laptop_webcam - a canvas frame captured in the browser
        esp32_cam     - a frame from the camera module
        file_upload   - an existing image file (the default)

    The value only labels the record; validation, preprocessing, the model and
    the confidence threshold are identical regardless of what is sent.
    """
    options = _request_options()
    data, filename, transport = _extract_image_bytes(options)

    explicit_source = (request.args.get("source") or request.form.get("source") or "").strip().lower()
    source, device_name = _infer_source(transport, explicit_source or None)

    camera_source = _resolve_camera_source(options["camera_source"], source, transport)

    result = analyze_and_store(
        data,
        source=source,
        camera_source=camera_source,
        device_name=device_name or options["device_name"],
        original_filename=filename,
        confidence_threshold=options["threshold"],
        notes=options["notes"],
        persist=options["save"],
        capture_info={"transport": transport},
    )

    if source == SOURCE_DEVICE and (device_name or options["device_name"]):
        name = device_name or options["device_name"]
        device_model.ensure_device(name, request.remote_addr)
        device_model.record_capture(name)

    message = (
        "Detection complete."
        if result["prediction"]["is_conclusive"]
        else f"Inconclusive result: {result['prediction']['reason']}"
    )
    return success_response(result, message=message)


# `/api/diagnosis` is the primary name for the full diagnosis workflow;
# `/api/analyze-plant` is kept as an alias so anything already calling it keeps
# working. One handler serves both rules - no duplicated logic.
@detection_bp.route("/diagnosis", methods=["POST"])
@detection_bp.route("/analyze-plant", methods=["POST"])
def analyze_plant():
    """
    Universal plant leaf analysis - works for ANY plant species.

    This is the endpoint behind the dashboard's "Analyse plant" button. Unlike
    ``/api/predict``, it does not force the image into one of the trained
    classifier's classes. It combines, and reports which of these contributed:

      * species-agnostic computer-vision symptom measurement (always),
      * the plant species you declare via ``plant_species`` (optional),
      * an AI vision reading when one is configured (optional),
      * the trained MobileNetV2 classifier, but only when the plant is one of
        the species it was trained on and it is confident.

    Accepts the same three request shapes as ``/api/predict``. Extra fields:

        plant_species   the plant, if you know it (e.g. "mango", "rose")
        use_vision_api  set false to skip the AI vision call for this request
        save            set false to analyse without recording

    The response never claims a confirmed diagnosis: it returns a ranked
    shortlist of possible conditions with the measured evidence for each, and
    withholds chemical treatment guidance unless the assessment is confident.
    """
    if not current_app.config.get("UNIVERSAL_ANALYSIS_ENABLED", True):
        raise ValidationError(
            "Universal analysis is disabled on this server. Set "
            "UNIVERSAL_ANALYSIS_ENABLED=true in .env, or use POST /api/predict for "
            "classifier-only detection."
        )

    options = _request_options()
    data, filename, transport = _extract_image_bytes(options)

    explicit_source = (request.args.get("source") or request.form.get("source") or "").strip().lower()
    source, device_name = _infer_source(transport, explicit_source or None)
    camera_source = _resolve_camera_source(options["camera_source"], source, transport)

    declared_species = options["plant_species"]
    if declared_species is not None:
        declared_species = str(declared_species).strip() or None
        if declared_species and len(declared_species) > 120:
            raise ValidationError("'plant_species' must be 120 characters or fewer.")

    result = analyze_and_store(
        data,
        source=source,
        camera_source=camera_source,
        device_name=device_name or options["device_name"],
        original_filename=filename,
        confidence_threshold=options["threshold"],
        notes=options["notes"],
        persist=options["save"],
        capture_info={"transport": transport},
        universal=True,
        declared_species=declared_species,
        use_vision_api=options["use_vision_api"],
    )

    report = result.get("analysis") or {}
    plant = report.get("plant") or {}
    condition = report.get("condition") or {}
    message = (
        f"{plant.get('name', 'Plant')}: {condition.get('label', 'no assessment')} "
        f"({report.get('confidence_level', 'unknown')} confidence)."
    )
    return success_response(result, message=message)


@detection_bp.route("/analyze", methods=["POST"])
def analyze():
    """Classify an image without saving the file or creating a history record."""
    options = _request_options()
    data, filename, transport = _extract_image_bytes(options)

    result = analyze_and_store(
        data,
        source=SOURCE_UPLOAD,
        camera_source=_resolve_camera_source(options["camera_source"], SOURCE_UPLOAD, transport),
        original_filename=filename,
        confidence_threshold=options["threshold"],
        persist=False,
        capture_info={"transport": transport},
    )
    return success_response(result, message="Analysed without saving.")


@detection_bp.route("/capture", methods=["POST"])
def capture():
    """
    Ask the ESP32-CAM for a fresh frame and classify it.

    Tries a direct ``GET /capture`` on the camera, then falls back to queuing a
    command the firmware picks up on its next poll. A 503 with both failure
    reasons is returned if neither transport delivers an image - no placeholder
    image is ever substituted.
    """
    options = _request_options()
    esp32 = get_esp32_service()
    device_name = options["device_name"] or current_app.config["ESP32_CAM_NAME"]

    logger.info("Capture requested for device '%s' (led=%s).", device_name, options["led"])

    image_bytes, capture_info = esp32.capture(
        led=options["led"],
        ip_address=options["ip_address"],
        device_name=device_name,
    )

    device_model.ensure_device(device_name, capture_info.get("ip_address"))
    if capture_info.get("ip_address"):
        device_model.upsert_device(
            device_name,
            connection_status="online",
            ip_address=capture_info["ip_address"],
        )
    device_model.record_capture(device_name)
    device_model.clear_error(device_name)

    result = analyze_and_store(
        image_bytes,
        source=SOURCE_DEVICE,
        camera_source=detection_model.CAMERA_SOURCE_ESP32,
        device_name=device_name,
        confidence_threshold=options["threshold"],
        capture_info=capture_info,
        persist=options["save"],
    )

    transport = capture_info.get("transport")
    message = (
        f"Captured via {transport} transport. "
        + (
            "Detection complete."
            if result["prediction"]["is_conclusive"]
            else f"Inconclusive result: {result['prediction']['reason']}"
        )
    )
    return success_response(result, message=message)


__all__ = ["detection_bp"]
