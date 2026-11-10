"""
services/esp32_service.py
=========================
Everything the backend does to talk to the ESP32-CAM.

Two complementary transports, because a classroom/lab network rarely allows
both directions:

**Pull mode (preferred)** - the backend performs ``GET http://<cam-ip>/capture``
and receives the JPEG in the response body. Lowest latency and fully
synchronous, but it needs the camera to be directly reachable from the server.

**Push fallback** - if the camera is not reachable (AP isolation, different
subnet, unknown IP), ``/api/capture`` registers a capture *job*. The firmware
polls ``GET /api/device/command`` every couple of seconds, sees the job,
captures, and POSTs the JPEG to ``/api/device/upload?job_id=...``. The waiting
request is released by a ``threading.Event`` as soon as the bytes arrive.

Nothing here invents an image: if neither transport delivers one, the caller
gets a 503 with the reason.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.errors import DeviceUnreachableError

logger = logging.getLogger(__name__)

JPEG_CONTENT_TYPES = ("image/jpeg", "image/jpg", "application/octet-stream")


# --------------------------------------------------------------------------- #
# Capture jobs (push fallback)
# --------------------------------------------------------------------------- #

@dataclass
class CaptureJob:
    """A capture request waiting for the firmware to deliver an image."""

    job_id: str
    device_name: str
    led: bool = True
    created_at: float = field(default_factory=time.time)
    dispatched_at: Optional[float] = None
    completed_at: Optional[float] = None
    image: Optional[bytes] = None
    error: Optional[str] = None
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def status(self) -> str:
        if self.image is not None:
            return "completed"
        if self.error:
            return "failed"
        if self.dispatched_at:
            return "dispatched"
        return "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "device_name": self.device_name,
            "led": self.led,
            "status": self.status,
            "age_seconds": round(time.time() - self.created_at, 2),
            "error": self.error,
            "image_bytes": len(self.image) if self.image else 0,
        }


class CaptureJobRegistry:
    """In-memory job table. Thread-safe; intentionally not persisted."""

    def __init__(self, max_age_seconds: float = 120.0) -> None:
        self._jobs: Dict[str, CaptureJob] = {}
        self._lock = threading.Lock()
        self._max_age = max_age_seconds

    def create(self, device_name: str, led: bool = True) -> CaptureJob:
        self._prune()
        job = CaptureJob(job_id=uuid.uuid4().hex[:12], device_name=device_name, led=led)
        with self._lock:
            self._jobs[job.job_id] = job
        logger.info("Capture job %s queued for device '%s'.", job.job_id, device_name)
        return job

    def get(self, job_id: str) -> Optional[CaptureJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def next_pending(self, device_name: Optional[str] = None) -> Optional[CaptureJob]:
        """
        Hand the oldest pending job to a polling device and mark it dispatched.

        Marking inside the lock is what stops two concurrent polls from both
        being told to capture for the same job.
        """
        with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if job.status == "pending"
                and (device_name is None or job.device_name == device_name)
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda item: item.created_at)
            job.dispatched_at = time.time()
            return job

    def fulfil(self, job_id: str, image: bytes) -> Optional[CaptureJob]:
        """Attach the delivered image and wake the waiting request."""
        job = self.get(job_id)
        if job is None:
            return None
        job.image = image
        job.completed_at = time.time()
        job._event.set()
        logger.info("Capture job %s fulfilled with %d bytes.", job_id, len(image))
        return job

    def fail(self, job_id: str, error: str) -> Optional[CaptureJob]:
        job = self.get(job_id)
        if job is None:
            return None
        job.error = error
        job.completed_at = time.time()
        job._event.set()
        logger.warning("Capture job %s failed: %s", job_id, error)
        return job

    def wait(self, job: CaptureJob, timeout: float) -> bytes:
        """Block until the image arrives; raises on timeout or reported failure."""
        if job._event.wait(timeout=timeout):
            if job.image is not None:
                return job.image
            raise DeviceUnreachableError(
                f"The camera reported a capture failure: {job.error}",
                {"job": job.to_dict()},
            )

        job.error = f"No image was delivered within {timeout:.0f}s."
        raise DeviceUnreachableError(
            f"Queued a capture command for '{job.device_name}' but no image arrived "
            f"within {timeout:.0f} seconds.\n"
            "Checks: is the board powered and running the firmware? Does its serial log "
            "show it polling /api/device/command? Is FLASK_SERVER_IP in the firmware set "
            "to this computer's LAN IP?",
            {"job": job.to_dict()},
        )

    def _prune(self) -> None:
        cutoff = time.time() - self._max_age
        with self._lock:
            stale = [
                job_id
                for job_id, job in self._jobs.items()
                if job.created_at < cutoff and job.status in ("completed", "failed", "pending")
            ]
            for job_id in stale:
                self._jobs.pop(job_id, None)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [job.to_dict() for job in self._jobs.values()]


# --------------------------------------------------------------------------- #
# HTTP client for the camera
# --------------------------------------------------------------------------- #

class Esp32CamService:
    """HTTP client for the ESP32-CAM firmware endpoints."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self.jobs = CaptureJobRegistry()
        self._session = requests.Session()

    # ---- addressing -----------------------------------------------------

    @property
    def configured_ip(self) -> Optional[str]:
        return self._config.ESP32_CAM_IP

    @property
    def default_device_name(self) -> str:
        return self._config.ESP32_CAM_NAME

    def dashboard_ip(self) -> Optional[str]:
        """Address saved from the Camera Management page, if any."""
        try:
            from services.settings_service import get_configured_esp32_ip  # noqa: PLC0415

            return get_configured_esp32_ip()
        except Exception as exc:  # pragma: no cover - outside an app context
            logger.debug("Could not read the dashboard-configured IP: %s", exc)
            return None

    def resolve_ip(self, explicit_ip: Optional[str] = None, device_name: Optional[str] = None) -> Optional[str]:
        """
        Work out which address to call.

        Priority:
          1. an explicit argument (this request only),
          2. the address saved from the Camera Management page,
          3. ``ESP32_CAM_IP`` from the environment,
          4. the last IP the device reported in its heartbeat.

        The dashboard value outranks ``.env`` because an operator who just
        corrected the address expects it to take effect without editing a file
        and restarting. The heartbeat fallback is what makes the system work on
        a DHCP network where the camera's address changes between sessions.
        """
        if explicit_ip:
            return explicit_ip.strip()

        dashboard = self.dashboard_ip()
        if dashboard:
            return dashboard

        if self.configured_ip:
            return self.configured_ip

        try:
            from models.device import resolve_device_ip  # noqa: PLC0415

            return resolve_device_ip(device_name or self.default_device_name)
        except Exception as exc:  # pragma: no cover - outside app context
            logger.debug("Could not resolve a device IP from the database: %s", exc)
            return None

    def address_sources(self, device_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Every candidate address and which one won.

        Shown on the Camera Management page: when a capture fails, the first
        question is always "which address did it actually try?"
        """
        dashboard = self.dashboard_ip()
        discovered: Optional[str] = None
        try:
            from models.device import resolve_device_ip  # noqa: PLC0415

            discovered = resolve_device_ip(device_name or self.default_device_name)
        except Exception:  # pragma: no cover
            discovered = None

        if dashboard:
            effective_from = "dashboard"
        elif self.configured_ip:
            effective_from = "env"
        elif discovered:
            effective_from = "heartbeat"
        else:
            effective_from = "none"

        return {
            "dashboard": dashboard,
            "env": self.configured_ip,
            "discovered": discovered,
            "effective": self.resolve_ip(device_name=device_name),
            "effective_from": effective_from,
        }

    def base_url(self, ip_address: Optional[str] = None) -> Optional[str]:
        return self._config.esp32_base_url(ip_address)

    # ---- low level ------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        ip_address: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> requests.Response:
        base = self.base_url(ip_address)
        if not base:
            raise DeviceUnreachableError(
                "No ESP32-CAM address is known.\n"
                "Either set ESP32_CAM_IP in .env to the address printed in the board's "
                "serial monitor, or let the firmware self-register by setting "
                "FLASK_SERVER_IP in the sketch so it can POST /api/device/register.",
                {"configured_ip": self.configured_ip},
            )

        url = f"{base}{path}"
        effective_timeout = timeout or self._config.ESP32_REQUEST_TIMEOUT
        try:
            response = self._session.request(method, url, timeout=effective_timeout, **kwargs)
        except requests.exceptions.ConnectTimeout as exc:
            raise DeviceUnreachableError(
                f"Connecting to the ESP32-CAM at {url} timed out after "
                f"{effective_timeout:.0f}s. The board is probably powered off, on a "
                "different Wi-Fi network, or using a different IP than configured.",
                {"url": url},
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise DeviceUnreachableError(
                f"The ESP32-CAM at {url} accepted the connection but did not finish "
                f"responding within {effective_timeout:.0f}s. A larger frame size on a "
                "weak Wi-Fi signal is the usual cause - try FRAMESIZE_VGA.",
                {"url": url},
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise DeviceUnreachableError(
                f"Could not reach the ESP32-CAM at {url}. Verify the board is powered, "
                "joined to the same Wi-Fi network as this server, and that its serial "
                "monitor shows the same IP address.",
                {"url": url, "error": str(exc)},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise DeviceUnreachableError(
                f"Request to the ESP32-CAM at {url} failed: {exc}", {"url": url}
            ) from exc

        if response.status_code >= 400:
            raise DeviceUnreachableError(
                f"The ESP32-CAM returned HTTP {response.status_code} for {path}. "
                "Check the serial monitor - the camera may have failed to initialise.",
                {"url": url, "status_code": response.status_code, "body": response.text[:300]},
            )
        return response

    # ---- operations -----------------------------------------------------

    def ping(self, ip_address: Optional[str] = None, device_name: Optional[str] = None) -> Dict[str, Any]:
        """Reachability probe. Returns a result dict instead of raising."""
        target = self.resolve_ip(ip_address, device_name)
        if not target:
            return {"reachable": False, "ip_address": None, "reason": "No IP address is known."}

        started = time.perf_counter()
        try:
            response = self._request(
                "GET",
                self._config.ESP32_STATUS_PATH,
                ip_address=target,
                timeout=self._config.ESP32_STATUS_TIMEOUT,
            )
        except DeviceUnreachableError as exc:
            return {"reachable": False, "ip_address": target, "reason": exc.message}

        latency = (time.perf_counter() - started) * 1000.0
        payload: Dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:300]}

        return {
            "reachable": True,
            "ip_address": target,
            "latency_ms": round(latency, 1),
            "device_report": payload,
        }

    def fetch_status(self, ip_address: Optional[str] = None, device_name: Optional[str] = None) -> Dict[str, Any]:
        """``GET /status`` on the camera; raises if unreachable."""
        target = self.resolve_ip(ip_address, device_name)
        response = self._request(
            "GET",
            self._config.ESP32_STATUS_PATH,
            ip_address=target,
            timeout=self._config.ESP32_STATUS_TIMEOUT,
        )
        try:
            return response.json()
        except ValueError as exc:
            raise DeviceUnreachableError(
                "The camera's /status endpoint did not return JSON. The firmware on the "
                "board may be older than this backend.",
                {"body": response.text[:300]},
            ) from exc

    def set_led(
        self,
        state: str,
        ip_address: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Switch the white illumination LED on or off."""
        normalised = str(state).strip().lower()
        if normalised not in ("on", "off"):
            raise ValueError("LED state must be 'on' or 'off'.")

        target = self.resolve_ip(ip_address, device_name)
        response = self._request(
            "GET",
            self._config.ESP32_LED_PATH,
            ip_address=target,
            timeout=self._config.ESP32_STATUS_TIMEOUT,
            params={"state": normalised},
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:200]}
        return {"led_state": normalised, "ip_address": target, "device_report": payload}

    def capture_pull(
        self,
        led: bool = True,
        ip_address: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        ``GET /capture`` and return the JPEG bytes.

        The firmware turns the LED on, lets exposure settle, grabs the frame and
        turns the LED off again, so the backend only has to ask once.
        """
        target = self.resolve_ip(ip_address, device_name)
        started = time.perf_counter()

        response = self._request(
            "GET",
            self._config.ESP32_CAPTURE_PATH,
            ip_address=target,
            params={"led": "1" if led else "0"},
        )

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = response.content

        if content_type and content_type not in JPEG_CONTENT_TYPES:
            raise DeviceUnreachableError(
                f"The camera responded with Content-Type '{content_type}' instead of a "
                "JPEG image. The camera module probably failed to initialise - check the "
                "serial monitor for 'Camera init failed'.",
                {"content_type": content_type, "body": response.text[:200]},
            )
        if not data:
            raise DeviceUnreachableError(
                "The camera returned an empty response body. The frame buffer grab "
                "failed; power-cycle the board and retry.",
                {"ip_address": target},
            )

        elapsed = (time.perf_counter() - started) * 1000.0
        logger.info("Pulled %d bytes from ESP32-CAM at %s in %.0f ms", len(data), target, elapsed)

        return data, {
            "transport": "pull",
            "ip_address": target,
            "transfer_ms": round(elapsed, 1),
            "content_type": content_type or "image/jpeg",
            "led_used": led,
        }

    def capture_push(
        self,
        led: bool = True,
        device_name: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Queue a capture command and wait for the firmware to upload the frame."""
        name = device_name or self.default_device_name
        wait_timeout = timeout or self._config.CAPTURE_JOB_TIMEOUT

        job = self.jobs.create(name, led=led)
        started = time.perf_counter()
        data = self.jobs.wait(job, wait_timeout)
        elapsed = (time.perf_counter() - started) * 1000.0

        return data, {
            "transport": "push",
            "job_id": job.job_id,
            "device_name": name,
            "transfer_ms": round(elapsed, 1),
            "content_type": "image/jpeg",
            "led_used": led,
        }

    def capture(
        self,
        led: bool = True,
        ip_address: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Acquire a frame, trying pull mode first and falling back to push mode.

        Both failures are reported together, because "camera unreachable AND no
        device polled for the job" is the diagnosis the user needs.
        """
        pull_error: Optional[str] = None
        target = self.resolve_ip(ip_address, device_name)

        if target:
            try:
                return self.capture_pull(led=led, ip_address=target, device_name=device_name)
            except DeviceUnreachableError as exc:
                pull_error = exc.message
                logger.warning("Pull capture failed (%s); trying the push fallback.", exc.message)
        else:
            pull_error = "No camera IP address is known, so a direct request was not attempted."

        if not self._config.ENABLE_PUSH_CAPTURE_FALLBACK:
            raise DeviceUnreachableError(
                pull_error or "The camera could not be reached.",
                {"push_fallback_enabled": False},
            )

        try:
            data, info = self.capture_push(led=led, device_name=device_name)
        except DeviceUnreachableError as exc:
            raise DeviceUnreachableError(
                "Could not obtain an image from the ESP32-CAM.\n"
                f"Direct request : {pull_error}\n"
                f"Queued command : {exc.message}",
                {"pull_error": pull_error, "push_error": exc.message, "details": exc.details},
            ) from exc

        info["pull_error"] = pull_error
        return data, info

    # ---- diagnostics ----------------------------------------------------

    def troubleshooting(self, device: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Build the Device page's troubleshooting checklist from the live state.

        Each entry is ``{severity, title, detail}``; the UI renders them in
        order, so the most blocking problem appears first.
        """
        checks: List[Dict[str, Any]] = []
        resolved_ip = self.resolve_ip(device_name=self.default_device_name)

        if not resolved_ip:
            checks.append(
                {
                    "severity": "error",
                    "title": "No camera address known",
                    "detail": (
                        "Set ESP32_CAM_IP in .env to the IP printed by the board's serial "
                        "monitor, or set FLASK_SERVER_IP in the sketch so the board can "
                        "register itself by POSTing /api/device/register."
                    ),
                }
            )
        if device is None:
            checks.append(
                {
                    "severity": "warning",
                    "title": "Device has never contacted the backend",
                    "detail": (
                        "No heartbeat has been received. Open the Arduino IDE serial "
                        "monitor at 115200 baud and confirm the board joins Wi-Fi and logs "
                        "'heartbeat ok'."
                    ),
                }
            )
        elif not device.get("is_online"):
            checks.append(
                {
                    "severity": "error",
                    "title": "Device is offline",
                    "detail": (
                        f"Last heartbeat was {device.get('seconds_since_last_seen')}s ago "
                        f"(offline threshold {device.get('offline_after_seconds')}s). Check "
                        "power - the camera browns out if the 5V supply cannot deliver ~500 mA."
                    ),
                }
            )

        signal = (device or {}).get("wifi_signal_quality")
        if signal in ("fair", "weak"):
            checks.append(
                {
                    "severity": "warning",
                    "title": f"Weak Wi-Fi signal ({device.get('wifi_rssi')} dBm)",
                    "detail": (
                        "Image uploads may time out. Move the board closer to the router "
                        "or reduce the frame size to FRAMESIZE_VGA."
                    ),
                }
            )

        if (device or {}).get("last_error"):
            checks.append(
                {
                    "severity": "error",
                    "title": "Device reported an error",
                    "detail": str(device.get("last_error")),
                }
            )

        if not checks:
            checks.append(
                {
                    "severity": "ok",
                    "title": "Device looks healthy",
                    "detail": (
                        f"Heartbeats are arriving from {device.get('ip_address')} and the "
                        "camera is ready to capture."
                    ),
                }
            )

        checks.append(
            {
                "severity": "info",
                "title": "Standard checks",
                "detail": (
                    "GPIO0 must be disconnected from GND after flashing; the white LED needs "
                    "a 220 ohm series resistor on GPIO4 (or use the on-board flash LED); and "
                    "the server and camera must share one subnet with AP isolation disabled."
                ),
            }
        )
        return checks


# --------------------------------------------------------------------------- #
# Singleton
# --------------------------------------------------------------------------- #

_service: Optional[Esp32CamService] = None


def init_esp32_service(config: Any) -> Esp32CamService:
    global _service
    _service = Esp32CamService(config)
    return _service


def get_esp32_service() -> Esp32CamService:
    if _service is None:
        raise RuntimeError(
            "Esp32CamService has not been initialised. init_esp32_service(config) must "
            "run inside create_app()."
        )
    return _service


__all__ = [
    "CaptureJob",
    "CaptureJobRegistry",
    "Esp32CamService",
    "init_esp32_service",
    "get_esp32_service",
]
