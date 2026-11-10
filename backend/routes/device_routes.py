"""
routes/device_routes.py
=======================
ESP32-CAM device endpoints - both the dashboard-facing ones and the
firmware-facing ones.

Dashboard -> server
    GET    /api/device/status     connection state, telemetry, troubleshooting
    GET    /api/devices           every known device
    POST   /api/device/led        switch the white illumination LED
    GET    /api/device/ping       live reachability probe
    DELETE /api/device/<name>     forget a device

Firmware -> server
    POST /api/device/register     heartbeat with IP, RSSI, heap, LED state
    GET  /api/device/command      poll for a queued capture command
    POST /api/device/upload       push a JPEG (fulfils a job, or classifies it)

The firmware endpoints can be protected with a shared secret: set
``DEVICE_API_KEY`` in ``.env`` and the same value in the sketch, and requests
must then carry it in the ``X-Device-Key`` header.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from flask import Blueprint, current_app, request

from models import device as device_model
from services.detection_service import CAMERA_ESP32, SOURCE_DEVICE, analyze_and_store
from services.esp32_service import get_esp32_service
from services.settings_service import InvalidSettingError, set_configured_esp32_ip
from utils.errors import ApiError, ImageValidationError, NotFoundError, ValidationError
from utils.image_utils import describe_jpeg_integrity
from utils.responses import success_response

logger = logging.getLogger(__name__)

device_bp = Blueprint("device", __name__, url_prefix="/api")

RAW_IMAGE_CONTENT_TYPES = ("image/jpeg", "image/jpg", "application/octet-stream", "")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def require_device_key(view: Callable) -> Callable:
    """Reject firmware requests without the shared secret, when one is configured."""

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        expected = current_app.config.get("DEVICE_API_KEY")
        if expected:
            supplied = request.headers.get("X-Device-Key") or request.args.get("key")
            if supplied != expected:
                raise ApiError(
                    "Invalid or missing device key. Set DEVICE_API_KEY in .env and the "
                    "matching DEVICE_API_KEY in the ESP32-CAM sketch.",
                    401,
                    "INVALID_DEVICE_KEY",
                )
        return view(*args, **kwargs)

    return wrapper


def _offline_after() -> int:
    return int(current_app.config["ESP32_OFFLINE_AFTER_SECONDS"])


def _default_device_name() -> str:
    return str(current_app.config["ESP32_CAM_NAME"])


def _body() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {key: value for key, value in request.form.items()}


def _first(body: Dict[str, Any], *names: str) -> Optional[Any]:
    """Accept several spellings of the same field, so firmware naming can vary."""
    for name in names:
        if name in body and body[name] not in (None, ""):
            return body[name]
        if name in request.args and request.args[name] not in (None, ""):
            return request.args[name]
    return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_bool_int(value: Any) -> Optional[int]:
    """JSON booleans arrive as bool, form fields as strings; store 0/1."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return 1
    if text in ("0", "false", "no", "off"):
        return 0
    return None


# --------------------------------------------------------------------------- #
# Dashboard-facing
# --------------------------------------------------------------------------- #

@device_bp.route("/device/config", methods=["GET"])
def get_device_config():
    """Current ESP32-CAM addressing, including where the effective value came from."""
    esp32 = get_esp32_service()
    return success_response(
        {
            "device_name": _default_device_name(),
            "addresses": esp32.address_sources(_default_device_name()),
            "port": current_app.config["ESP32_CAM_PORT"],
            "base_url": esp32.base_url(esp32.resolve_ip()),
            "capture_path": current_app.config["ESP32_CAPTURE_PATH"],
            "status_path": current_app.config["ESP32_STATUS_PATH"],
            "led_path": current_app.config["ESP32_LED_PATH"],
        }
    )


@device_bp.route("/device/config", methods=["POST"])
def set_device_config():
    """
    Save the ESP32-CAM IP address typed on the Camera Management page.

    Stored in ``app_settings`` rather than written into ``.env``: the operator's
    own configuration file is left alone, and the value takes effect at once
    without a restart. Send an empty string to clear it and fall back to the
    ``.env`` value or heartbeat discovery.
    """
    body = _body()
    raw = _first(body, "ip_address", "ip", "host")

    try:
        stored = set_configured_esp32_ip(None if raw is None else str(raw))
    except InvalidSettingError as exc:
        raise ValidationError(str(exc), {"received": raw}) from exc

    esp32 = get_esp32_service()
    addresses = esp32.address_sources(_default_device_name())

    # Probe straight away: the operator typed an address to make it work, so
    # telling them now whether it answers is more useful than a saved toast.
    probe = esp32.ping(device_name=_default_device_name())
    if probe.get("reachable"):
        device_model.ensure_device(_default_device_name(), probe.get("ip_address"))
        device_model.upsert_device(
            _default_device_name(),
            connection_status="online",
            ip_address=probe.get("ip_address"),
        )

    message = (
        f"Address cleared; now using {addresses['effective'] or 'no address'}."
        if stored is None
        else (
            f"Saved {stored}. Camera responded in {probe.get('latency_ms')} ms."
            if probe.get("reachable")
            else f"Saved {stored}, but the camera did not respond: {probe.get('reason')}"
        )
    )

    return success_response(
        {"ip_address": stored, "addresses": addresses, "live_probe": probe},
        message=message,
    )


@device_bp.route("/device/status", methods=["GET"])
def device_status():
    """
    Current ESP32-CAM status for the Device Management page.

    Pass ``?ping=true`` to additionally attempt a live HTTP probe of the camera.
    The probe is opt-in because it blocks for up to ``ESP32_STATUS_TIMEOUT``
    seconds and the page polls this endpoint frequently.
    """
    esp32 = get_esp32_service()
    device_model.mark_stale_devices_offline(_offline_after())

    requested_name = request.args.get("device") or _default_device_name()
    device = device_model.get_primary_device(_offline_after(), requested_name)

    live_probe: Optional[Dict[str, Any]] = None
    if (request.args.get("ping") or "").lower() in ("1", "true", "yes"):
        live_probe = esp32.ping(device_name=requested_name)
        if device and live_probe.get("reachable"):
            device_model.upsert_device(
                device["device_name"],
                connection_status="online",
                ip_address=live_probe.get("ip_address"),
            )
            device = device_model.get_primary_device(_offline_after(), requested_name)

    payload = {
        "device": device,
        "is_online": bool(device and device["is_online"]),
        "configured": {
            "device_name": _default_device_name(),
            "static_ip": esp32.configured_ip,
            "resolved_ip": esp32.resolve_ip(device_name=requested_name),
            "addresses": esp32.address_sources(requested_name),
            "capture_path": current_app.config["ESP32_CAPTURE_PATH"],
            "status_path": current_app.config["ESP32_STATUS_PATH"],
            "led_path": current_app.config["ESP32_LED_PATH"],
            "offline_after_seconds": _offline_after(),
            "push_fallback_enabled": bool(current_app.config["ENABLE_PUSH_CAPTURE_FALLBACK"]),
            "device_key_required": bool(current_app.config.get("DEVICE_API_KEY")),
        },
        "live_probe": live_probe,
        "pending_capture_jobs": esp32.jobs.snapshot(),
        "troubleshooting": esp32.troubleshooting(device),
    }

    message = (
        f"{device['device_name']} is online at {device['ip_address']}."
        if payload["is_online"] and device
        else "No ESP32-CAM is currently online."
    )
    return success_response(payload, message=message)


@device_bp.route("/devices", methods=["GET"])
def list_devices():
    devices = device_model.list_devices(_offline_after())
    return success_response({"count": len(devices), "devices": devices})


@device_bp.route("/device/ping", methods=["GET", "POST"])
def ping_device():
    """Live reachability probe against the camera's /status endpoint."""
    esp32 = get_esp32_service()
    name = request.args.get("device") or _default_device_name()
    result = esp32.ping(ip_address=request.args.get("ip"), device_name=name)

    if result["reachable"]:
        device_model.ensure_device(name, result.get("ip_address"))
        device_model.upsert_device(
            name, connection_status="online", ip_address=result.get("ip_address")
        )
        message = f"Camera responded in {result.get('latency_ms')} ms."
    else:
        message = result.get("reason") or "Camera did not respond."

    return success_response(result, message=message, status_code=200 if result["reachable"] else 503)


@device_bp.route("/device/led", methods=["POST"])
def control_led():
    """
    Switch the white illumination LED on or off.

    This needs a direct connection to the camera (the LED is wired to the
    board's GPIO), so it cannot work through the push fallback.
    """
    body = _body()
    state = str(_first(body, "state", "led") or "").strip().lower()
    if state not in ("on", "off"):
        raise ValidationError("'state' must be either 'on' or 'off'.", {"received": state or None})

    esp32 = get_esp32_service()
    name = str(_first(body, "device", "device_name") or _default_device_name())

    result = esp32.set_led(state, ip_address=_first(body, "ip", "ip_address"), device_name=name)

    device_model.ensure_device(name, result.get("ip_address"))
    device_model.set_led_state(name, state)

    return success_response(
        {**result, "device": device_model.get_primary_device(_offline_after(), name)},
        message=f"White LED switched {state}.",
    )


@device_bp.route("/device/<device_name>", methods=["DELETE"])
def forget_device(device_name: str):
    if not device_model.delete_device(device_name):
        raise NotFoundError(f"No device named '{device_name}' is registered.")
    return success_response({"device_name": device_name}, message=f"Device '{device_name}' removed.")


# --------------------------------------------------------------------------- #
# Firmware-facing
# --------------------------------------------------------------------------- #

# `POST /api/device/status` is accepted as an alias of `/api/device/register`:
# both mean "the device is reporting its status". One handler serves both rules
# so there is no duplicated logic, and `GET /api/device/status` (the
# dashboard-facing read) is unaffected.
@device_bp.route("/device/register", methods=["POST"])
@device_bp.route("/device/status", methods=["POST"])
@require_device_key
def register_device():
    """
    Firmware heartbeat.

    The board calls this every few seconds with its telemetry. Two things make
    it worth having: the backend learns the camera's current DHCP address (so
    ``ESP32_CAM_IP`` never has to be hardcoded), and the dashboard can show a
    real online/offline state based on heartbeat age.

    The response also carries any queued capture command, which saves the board
    a second HTTP round-trip in the common case.
    """
    body = _body()
    name = str(_first(body, "device_name", "device", "name") or _default_device_name())

    reported_ip = _first(body, "ip_address", "ip", "local_ip")
    ip_address = str(reported_ip) if reported_ip else request.remote_addr

    device = device_model.upsert_device(
        name,
        connection_status="online",
        ip_address=ip_address,
        mac_address=_first(body, "mac_address", "mac"),
        wifi_ssid=_first(body, "wifi_ssid", "ssid"),
        wifi_rssi=_as_int(_first(body, "wifi_rssi", "rssi")),
        firmware_version=_first(body, "firmware_version", "firmware", "version"),
        camera_model=_first(body, "camera_model", "camera"),
        led_state=_first(body, "led_state", "led"),
        free_heap=_as_int(_first(body, "free_heap", "heap")),
        uptime_seconds=_as_int(_first(body, "uptime_seconds", "uptime")),
        frame_size=_first(body, "frame_size", "framesize"),
        psram_found=_as_bool_int(_first(body, "psram_found", "psram")),
        last_error=_first(body, "last_error", "error"),
    )

    esp32 = get_esp32_service()
    pending = esp32.jobs.next_pending(name)

    logger.debug("Heartbeat from %s at %s (rssi=%s)", name, ip_address, _first(body, "rssi"))

    return success_response(
        {
            "device": device_model.to_api_dict(device, _offline_after()) if device else None,
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "heartbeat_interval_seconds": max(5, _offline_after() // 3),
            "command": (
                {"action": "capture", "job_id": pending.job_id, "led": pending.led}
                if pending
                else {"action": "none"}
            ),
        },
        message="Heartbeat recorded.",
    )


@device_bp.route("/device/command", methods=["GET"])
@require_device_key
def poll_command():
    """
    Command poll for the firmware.

    Returns ``{"action": "capture", "job_id": ...}`` when the dashboard has
    requested an image, otherwise ``{"action": "none"}``. This is the path that
    makes dashboard-triggered capture work even when the server cannot open a
    connection to the camera (client-isolated Wi-Fi, different subnet).
    """
    name = request.args.get("device") or request.args.get("device_name") or _default_device_name()

    device_model.ensure_device(name, request.remote_addr)
    device_model.upsert_device(name, connection_status="online", ip_address=request.remote_addr)

    job = get_esp32_service().jobs.next_pending(name)
    if job is None:
        return success_response({"action": "none"})

    return success_response(
        {
            "action": "capture",
            "job_id": job.job_id,
            "led": job.led,
            "upload_url": "/api/device/upload",
        },
        message="Capture requested.",
    )


@device_bp.route("/device/upload", methods=["POST"])
@require_device_key
def upload_image():
    """
    Receive a JPEG pushed by the firmware.

    Two cases:

    * **Answering a queued job** (``?job_id=...``) - the bytes are handed to the
      waiting ``/api/capture`` request, which performs inference and returns the
      result to the dashboard. This endpoint returns immediately so the board's
      socket is freed while the model runs.
    * **Unsolicited push** - the firmware captured on its own (button, timer).
      The full pipeline runs here and the prediction is returned to the device,
      which can log it over serial.
    """
    content_type = (request.content_type or "").split(";")[0].strip().lower()
    name = (
        request.args.get("device")
        or request.args.get("device_name")
        or request.headers.get("X-Device-Name")
        or _default_device_name()
    )
    job_id = request.args.get("job_id") or request.headers.get("X-Job-Id")

    # Accept either transport. Raw body is what the firmware uses (streaming a
    # multipart envelope from an MCU is needless work); multipart is accepted so
    # curl, Postman and the simulator can post the same way a browser would.
    # An absent Content-Type is tolerated for raw bodies because some HTTPClient
    # builds omit it, and rejecting on that alone would fail a valid image.
    if "multipart/form-data" in (request.content_type or ""):
        file_storage = request.files.get("image") or request.files.get("file")
        data = file_storage.read() if file_storage else b""
        transport = "multipart"
    elif content_type in RAW_IMAGE_CONTENT_TYPES:
        data = request.get_data(cache=False)
        transport = "raw"
    else:
        raise ValidationError(
            f"Unsupported Content-Type '{request.content_type}'. Send the JPEG as a raw "
            "body with Content-Type: image/jpeg, or as multipart/form-data with an "
            "'image' field.",
            {"received_content_type": request.content_type},
        )

    device_model.ensure_device(name, request.remote_addr)

    # An empty or structurally broken payload is a real device fault, so it is
    # reported as such: the waiting capture job fails, the error is recorded
    # against the device for the Device page, and the response is a 400. It is
    # never accepted as a successful detection - a grey half-frame classified
    # as a disease would be worse than no answer at all.
    if not data:
        error = (
            f"The device uploaded an empty body (0 bytes) over the {transport} transport; "
            "the camera frame grab failed. Check the 5V supply (the module browns out "
            "below ~500 mA), reseat the camera ribbon, and confirm PSRAM is enabled."
        )
        if job_id:
            get_esp32_service().jobs.fail(job_id, error)
        device_model.set_error(name, error)
        logger.warning("Rejected an empty upload from '%s' (%s transport).", name, transport)
        raise ImageValidationError(error, {"transport": transport, "bytes_received": 0})

    integrity = describe_jpeg_integrity(data)
    if integrity["has_soi"] and not integrity["has_eoi"]:
        error = (
            f"The device uploaded a truncated JPEG ({len(data)} bytes, End Of Image marker "
            "missing). The transfer was cut short - usually a weak Wi-Fi signal or a "
            "brown-out mid-upload. Reduce CAMERA_FRAME_SIZE in the sketch and retry."
        )
        if job_id:
            get_esp32_service().jobs.fail(job_id, error)
        device_model.set_error(name, error)
        logger.warning("Rejected a truncated upload from '%s': %s", name, integrity)
        raise ImageValidationError(error, {"transport": transport, "integrity": integrity})

    logger.info(
        "Accepted %d bytes from '%s' (%s transport, job=%s).",
        len(data),
        name,
        transport,
        job_id or "none",
    )

    device_model.upsert_device(name, connection_status="online", ip_address=request.remote_addr)
    device_model.record_capture(name)
    device_model.clear_error(name)

    # Case 1: fulfil the job and let the waiting request do the inference.
    if job_id:
        job = get_esp32_service().jobs.fulfil(job_id, data)
        if job is not None:
            return success_response(
                {
                    "job_id": job_id,
                    "bytes_received": len(data),
                    "transport": transport,
                    "integrity": integrity,
                    "handled_by": "capture_request",
                },
                message="Image received; the waiting capture request will classify it.",
            )
        logger.warning("Upload referenced unknown job '%s'; classifying it here instead.", job_id)

    # Case 2: unsolicited push - run the full pipeline now.
    result = analyze_and_store(
        data,
        source=SOURCE_DEVICE,
        camera_source=CAMERA_ESP32,
        device_name=name,
        capture_info={
            "transport": f"push-unsolicited-{transport}",
            "ip_address": request.remote_addr,
            "integrity": integrity,
        },
    )
    return success_response(
        result,
        message=(
            "Detection complete."
            if result["prediction"]["is_conclusive"]
            else f"Inconclusive result: {result['prediction']['reason']}"
        ),
    )


__all__ = ["device_bp", "require_device_key"]
