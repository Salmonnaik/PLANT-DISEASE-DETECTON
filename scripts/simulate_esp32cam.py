"""
simulate_esp32cam.py
====================
A SIMULATED ESP32-CAM, for testing the backend without the hardware attached.

It speaks exactly the same HTTP protocol as ``esp32cam/plant_disease_camera.ino``:

    POST /api/device/register   heartbeat with IP / RSSI / heap / LED state
    GET  /api/device/command    poll for a dashboard-triggered capture
    POST /api/device/upload     push the JPEG for a given job_id

What this proves and what it does not
------------------------------------
It verifies the *protocol and the backend*: heartbeats, online/offline state,
dashboard-triggered capture, image upload, inference and history writes. It
does **not** prove anything about the real camera optics, the LED wiring or
Wi-Fi behaviour on the board - only real hardware does that.

Every value it reports is marked as simulated: the device name defaults to
``esp32-cam-sim``, the firmware version string is ``simulator-1.0.0``, and
synthetic frames carry a visible "SIMULATED FRAME" label. Nothing it produces
should be presented as a hardware result.

Usage
-----
    python scripts/simulate_esp32cam.py
    python scripts/simulate_esp32cam.py --server http://192.168.1.10:5000
    python scripts/simulate_esp32cam.py --image path/to/real_leaf.jpg
    python scripts/simulate_esp32cam.py --once          # one heartbeat, then exit
"""

from __future__ import annotations

import argparse
import io
import logging
import random
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:
    import numpy as np
    import requests
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    print(
        f"Missing dependency: {exc}\nInstall with: pip install -r backend/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("esp32-sim")

DEFAULT_SERVER = "http://127.0.0.1:5000"
DEVICE_NAME = "esp32-cam-sim"
FIRMWARE_VERSION = "simulator-1.0.0"


# --------------------------------------------------------------------------- #
# Synthetic frame generation
# --------------------------------------------------------------------------- #

def generate_frame(size: int = 480, seed: Optional[int] = None) -> bytes:
    """
    Render a synthetic leaf-like frame.

    Deliberately labelled on the image itself so a simulated capture can never
    be mistaken for a photograph from the real camera. The texture (veins plus
    sensor-style noise) exists so the frame passes the backend's image-quality
    gate and the inference path is actually exercised.
    """
    rng = np.random.default_rng(seed if seed is not None else random.randrange(1 << 30))

    height = width = size
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    centre_y, centre_x = height / 2.0, width / 2.0

    canvas = np.full((height, width, 3), 48.0, dtype=np.float32)   # dark background
    leaf_mask = (
        ((grid_x - centre_x) ** 2) / (width * 0.36) ** 2
        + ((grid_y - centre_y) ** 2) / (height * 0.28) ** 2
    ) < 1.0

    base_green = rng.uniform(120, 165)
    canvas[leaf_mask] = [base_green * 0.42, base_green, base_green * 0.34]

    # Midrib and side veins.
    midrib = np.abs(grid_y - centre_y) < 2.5
    canvas[midrib & leaf_mask] = [base_green * 0.62, base_green * 1.18, base_green * 0.52]
    for offset in range(-int(width * 0.4), int(width * 0.4), 18):
        for direction in (0.55, -0.55):
            vein = np.abs((grid_y - centre_y) - direction * (grid_x - centre_x - offset)) < 1.4
            canvas[vein & leaf_mask] = [base_green * 0.58, base_green * 1.1, base_green * 0.48]

    # A few brown spots so the frame is not a flat colour field.
    for _ in range(rng.integers(3, 9)):
        spot_x = rng.integers(int(width * 0.2), int(width * 0.8))
        spot_y = rng.integers(int(height * 0.25), int(height * 0.75))
        radius = rng.integers(6, 20)
        spot = ((grid_x - spot_x) ** 2 + (grid_y - spot_y) ** 2) < radius**2
        canvas[spot & leaf_mask] = [rng.uniform(95, 130), rng.uniform(70, 100), rng.uniform(35, 55)]

    canvas += rng.normal(0.0, 7.0, canvas.shape)        # sensor noise
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)

    image = Image.fromarray(canvas)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, 22], fill=(120, 20, 20))
    draw.text((6, 6), "SIMULATED FRAME - NOT A REAL CAMERA IMAGE", fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def load_frame(image_path: Optional[Path], size: int) -> bytes:
    """Use a real photograph when one is supplied, otherwise synthesise one."""
    if image_path is None:
        return generate_frame(size)
    if not image_path.is_file():
        raise SystemExit(f"Image not found: {image_path}")
    logger.info("Using real image file: %s", image_path)
    return image_path.read_bytes()


# --------------------------------------------------------------------------- #
# Simulated device
# --------------------------------------------------------------------------- #

class SimulatedCamera:
    """Mirrors the firmware's heartbeat / poll / upload loop."""

    def __init__(
        self,
        server: str,
        device_name: str = DEVICE_NAME,
        device_key: Optional[str] = None,
        image_path: Optional[Path] = None,
        frame_size: int = 480,
    ) -> None:
        self.server = server.rstrip("/")
        self.device_name = device_name
        self.image_path = image_path
        self.frame_size = frame_size
        self.led_state = "off"
        self.started_at = time.time()
        self.captures = 0
        self.session = requests.Session()
        self.headers: Dict[str, str] = {"X-Device-Name": device_name}
        if device_key:
            self.headers["X-Device-Key"] = device_key

    # ---- telemetry ------------------------------------------------------

    def _local_ip(self) -> str:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"
        finally:
            probe.close()

    def telemetry(self) -> Dict[str, Any]:
        return {
            "device_name": self.device_name,
            "ip_address": self._local_ip(),
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "wifi_ssid": "SIMULATED-WIFI",
            "wifi_rssi": random.randint(-72, -48),
            "firmware_version": FIRMWARE_VERSION,
            "camera_model": "SIMULATOR (no OV2640 attached)",
            "led_state": self.led_state,
            "free_heap": random.randint(120_000, 210_000),
            "uptime_seconds": int(time.time() - self.started_at),
            "frame_size": f"SIMULATED ({self.frame_size}x{self.frame_size})",
            "psram_found": True,
        }

    # ---- protocol -------------------------------------------------------

    def heartbeat(self) -> Optional[Dict[str, Any]]:
        """POST /api/device/register. Returns any command the server piggybacked."""
        try:
            response = self.session.post(
                f"{self.server}/api/device/register",
                json=self.telemetry(),
                headers=self.headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            logger.error("Heartbeat failed - is the backend running at %s? (%s)", self.server, exc)
            return None

        if response.status_code >= 400:
            logger.error("Heartbeat rejected: HTTP %d %s", response.status_code, response.text[:200])
            return None

        payload = response.json().get("data", {})
        command = payload.get("command") or {}
        if command.get("action") == "capture":
            logger.info("Heartbeat returned a queued capture command.")
            return command
        return None

    def poll_command(self) -> Optional[Dict[str, Any]]:
        """GET /api/device/command."""
        try:
            response = self.session.get(
                f"{self.server}/api/device/command",
                params={"device": self.device_name},
                headers=self.headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            logger.debug("Command poll failed: %s", exc)
            return None

        if response.status_code >= 400:
            logger.error("Command poll rejected: HTTP %d %s", response.status_code, response.text[:200])
            return None

        command = response.json().get("data", {})
        return command if command.get("action") == "capture" else None

    def capture_and_upload(self, job_id: Optional[str] = None, led: bool = True) -> bool:
        """Grab a frame (with the 'LED' on) and POST it to /api/device/upload."""
        if led:
            self.led_state = "on"
            time.sleep(0.2)   # the real firmware lets exposure settle here

        frame = load_frame(self.image_path, self.frame_size)
        self.led_state = "off"
        self.captures += 1

        logger.info(
            "Uploading %d byte frame%s ...", len(frame), f" for job {job_id}" if job_id else ""
        )
        try:
            response = self.session.post(
                f"{self.server}/api/device/upload",
                params={"device": self.device_name, **({"job_id": job_id} if job_id else {})},
                data=frame,
                headers={**self.headers, "Content-Type": "image/jpeg"},
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.error("Upload failed: %s", exc)
            return False

        if response.status_code >= 400:
            logger.error("Upload rejected: HTTP %d %s", response.status_code, response.text[:300])
            return False

        body = response.json()
        logger.info("Server: %s", body.get("message"))

        prediction = (body.get("data") or {}).get("prediction")
        if prediction:
            logger.info(
                "  -> %s | confidence %.2f%% | validated=%s",
                prediction.get("display_label"),
                prediction.get("confidence_percent", 0.0),
                prediction.get("is_validated_prediction"),
            )
        return True

    # ---- main loop ------------------------------------------------------

    def run(self, heartbeat_interval: float = 5.0, poll_interval: float = 2.0) -> int:
        logger.warning("=" * 76)
        logger.warning("ESP32-CAM SIMULATOR - no real hardware is involved.")
        logger.warning("Device name '%s', firmware '%s'.", self.device_name, FIRMWARE_VERSION)
        logger.warning("=" * 76)
        logger.info("Backend: %s", self.server)

        command = self.heartbeat()
        if command:
            self.capture_and_upload(command.get("job_id"), bool(command.get("led", True)))

        last_heartbeat = time.time()
        logger.info("Polling for capture commands. Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(poll_interval)

                command = self.poll_command()
                if command:
                    self.capture_and_upload(command.get("job_id"), bool(command.get("led", True)))

                if time.time() - last_heartbeat >= heartbeat_interval:
                    piggybacked = self.heartbeat()
                    last_heartbeat = time.time()
                    if piggybacked:
                        self.capture_and_upload(
                            piggybacked.get("job_id"), bool(piggybacked.get("led", True))
                        )
        except KeyboardInterrupt:
            logger.info("Simulator stopped after %d capture(s).", self.captures)
            return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate an ESP32-CAM against the Flask backend (no hardware required).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Backend base URL")
    parser.add_argument("--device", default=DEVICE_NAME, help="Device name to register as")
    parser.add_argument("--device-key", default=None, help="Value for the X-Device-Key header")
    parser.add_argument("--image", type=Path, default=None, help="Upload this real image instead of a synthetic frame")
    parser.add_argument("--frame-size", type=int, default=480, help="Synthetic frame size in pixels")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true", help="Send one heartbeat and one capture, then exit")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    camera = SimulatedCamera(
        server=args.server,
        device_name=args.device,
        device_key=args.device_key,
        image_path=args.image,
        frame_size=args.frame_size,
    )

    if args.once:
        logger.warning("ESP32-CAM SIMULATOR (single shot) - no real hardware involved.")
        camera.heartbeat()
        ok = camera.capture_and_upload()
        return 0 if ok else 1

    return camera.run(args.heartbeat_interval, args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
