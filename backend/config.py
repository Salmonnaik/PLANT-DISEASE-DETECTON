"""
config.py
=========
Central configuration for the Flask backend.

Every value can be overridden with an environment variable, which is how the
same code runs on a developer laptop and on the lab Wi-Fi network without edits.
Values are read from the process environment and from a ``.env`` file at the
project root (see ``.env.example``).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import List, Optional, Set

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is in requirements.txt
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ML_DIR = PROJECT_ROOT / "ml"

# Load .env from the project root first, then allow a backend-local override.
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)


# --------------------------------------------------------------------------- #
# Typed environment readers
# --------------------------------------------------------------------------- #

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n"}


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def env_optional_str(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def env_path(name: str, default: Path) -> Path:
    raw = env_optional_str(name)
    if raw is None:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()


def env_list(name: str, default: List[str]) -> List[str]:
    raw = env_optional_str(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

class Config:
    """Base configuration shared by all environments."""

    # ---- Flask ----------------------------------------------------------
    HOST: str = env_str("FLASK_HOST", "0.0.0.0")
    PORT: int = env_int("FLASK_PORT", 5000)
    DEBUG: bool = env_bool("FLASK_DEBUG", False)
    SECRET_KEY: str = env_str("SECRET_KEY", secrets.token_hex(16))
    JSON_SORT_KEYS: bool = False

    # ---- Uploads --------------------------------------------------------
    UPLOAD_FOLDER: Path = env_path("UPLOAD_FOLDER", BACKEND_DIR / "uploads")
    MAX_UPLOAD_MB: int = env_int("MAX_UPLOAD_MB", 12)
    MAX_CONTENT_LENGTH: int = MAX_UPLOAD_MB * 1024 * 1024
    ALLOWED_EXTENSIONS: Set[str] = {"jpg", "jpeg", "png", "bmp", "webp"}
    KEEP_UPLOADED_IMAGES: bool = env_bool("KEEP_UPLOADED_IMAGES", True)

    # ---- Database -------------------------------------------------------
    DATABASE_PATH: Path = env_path("DATABASE_PATH", BACKEND_DIR / "database" / "plant_disease.db")
    SCHEMA_PATH: Path = BACKEND_DIR / "database" / "schema.sql"

    # ---- Universal analysis ---------------------------------------------
    # The species-agnostic computer-vision layer, which lets any plant be
    # analysed rather than forcing every image into the classifier's classes.
    UNIVERSAL_ANALYSIS_ENABLED: bool = env_bool("UNIVERSAL_ANALYSIS_ENABLED", True)

    # ---- AI vision API (optional) ---------------------------------------
    # Supplies plant species identification, which local code cannot do.
    # Without a key the system still works: species comes from the user's
    # selection and symptoms from local measurement.
    VISION_API_ENABLED: bool = env_bool("VISION_API_ENABLED", False)
    VISION_API_PROVIDER: str = env_str("VISION_API_PROVIDER", "openai")
    VISION_API_KEY: Optional[str] = env_optional_str("VISION_API_KEY")
    VISION_API_MODEL: str = env_str("VISION_API_MODEL", "gpt-4o-mini")
    VISION_API_BASE_URL: Optional[str] = env_optional_str("VISION_API_BASE_URL")
    VISION_API_TIMEOUT: float = env_float("VISION_API_TIMEOUT", 45.0)

    # ---- Cameras --------------------------------------------------------
    # Camera sources the API accepts for a detection. The laptop webcam is
    # captured in the browser (MediaDevices + canvas) and posted as a JPEG, so
    # the backend needs no driver for it - only a label to record.
    CAMERA_SOURCES: tuple = ("laptop_webcam", "esp32_cam", "file_upload")
    DEFAULT_CAMERA_SOURCE: str = env_str("DEFAULT_CAMERA_SOURCE", "file_upload")
    ENABLE_WEBCAM_SOURCE: bool = env_bool("ENABLE_WEBCAM_SOURCE", True)
    ENABLE_ESP32_SOURCE: bool = env_bool("ENABLE_ESP32_SOURCE", True)

    # ---- Machine learning ----------------------------------------------
    ML_DIR: Path = ML_DIR
    MODEL_PATH: Path = env_path("MODEL_PATH", ML_DIR / "saved_model" / "plant_disease_model.keras")
    LABELS_PATH: Path = env_path("LABELS_PATH", ML_DIR / "class_labels.json")
    MODEL_METADATA_PATH: Path = env_path("MODEL_METADATA_PATH", ML_DIR / "saved_model" / "metadata.json")
    REPORTS_DIR: Path = env_path("REPORTS_DIR", ML_DIR / "reports")

    # Minimum softmax confidence before a disease name is reported. Below this
    # the API returns an explicit "uncertain" result instead of a diagnosis.
    CONFIDENCE_THRESHOLD: float = env_float("CONFIDENCE_THRESHOLD", 0.70)
    ENFORCE_QUALITY_GATE: bool = env_bool("ENFORCE_QUALITY_GATE", True)

    # Load the model during startup (slower boot, faster first request).
    EAGER_MODEL_LOAD: bool = env_bool("EAGER_MODEL_LOAD", True)

    # When False the backend refuses to serve predictions from the untrained
    # bootstrap model, so a production deployment can never run in test mode.
    ALLOW_TEST_MODE_MODEL: bool = env_bool("ALLOW_TEST_MODE_MODEL", True)

    # Image quality gate thresholds (see ml/preprocessing.py).
    QUALITY_MIN_SHARPNESS: float = env_float("QUALITY_MIN_SHARPNESS", 30.0)
    QUALITY_MIN_BRIGHTNESS: float = env_float("QUALITY_MIN_BRIGHTNESS", 25.0)
    QUALITY_MAX_BRIGHTNESS: float = env_float("QUALITY_MAX_BRIGHTNESS", 240.0)
    QUALITY_MIN_CONTRAST: float = env_float("QUALITY_MIN_CONTRAST", 12.0)
    QUALITY_MIN_PLANT_RATIO: float = env_float("QUALITY_MIN_PLANT_RATIO", 0.04)
    QUALITY_MIN_SIDE_PIXELS: float = env_float("QUALITY_MIN_SIDE_PIXELS", 64.0)

    # ---- ESP32-CAM ------------------------------------------------------
    # Leave ESP32_CAM_IP empty to let the device self-register: the firmware
    # POSTs a heartbeat to /api/device/register and the backend remembers the IP.
    ESP32_CAM_IP: Optional[str] = env_optional_str("ESP32_CAM_IP")
    ESP32_CAM_PORT: int = env_int("ESP32_CAM_PORT", 80)
    ESP32_CAM_NAME: str = env_str("ESP32_CAM_NAME", "esp32-cam-01")
    ESP32_CAPTURE_PATH: str = env_str("ESP32_CAPTURE_PATH", "/capture")
    ESP32_STATUS_PATH: str = env_str("ESP32_STATUS_PATH", "/status")
    ESP32_LED_PATH: str = env_str("ESP32_LED_PATH", "/led")
    ESP32_REQUEST_TIMEOUT: float = env_float("ESP32_REQUEST_TIMEOUT", 20.0)
    ESP32_STATUS_TIMEOUT: float = env_float("ESP32_STATUS_TIMEOUT", 4.0)

    # A device is reported offline if no heartbeat or capture arrived within this
    # many seconds. The firmware heartbeat interval must be comfortably smaller.
    ESP32_OFFLINE_AFTER_SECONDS: int = env_int("ESP32_OFFLINE_AFTER_SECONDS", 45)

    # Fallback "push" flow: when the backend cannot reach the camera directly it
    # queues a capture command that the firmware picks up on its next poll, then
    # waits this long for the resulting image to be uploaded.
    CAPTURE_JOB_TIMEOUT: float = env_float("CAPTURE_JOB_TIMEOUT", 30.0)
    ENABLE_PUSH_CAPTURE_FALLBACK: bool = env_bool("ENABLE_PUSH_CAPTURE_FALLBACK", True)

    # Optional shared secret. When set, firmware requests must send it as
    # `X-Device-Key`; requests without it are rejected.
    DEVICE_API_KEY: Optional[str] = env_optional_str("DEVICE_API_KEY")

    # ---- CORS -----------------------------------------------------------
    CORS_ORIGINS: List[str] = env_list(
        "CORS_ORIGINS",
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
    )
    # Convenience for lab demos where the dashboard is opened from a phone on
    # the same Wi-Fi and the exact origin is not known in advance.
    CORS_ALLOW_ALL: bool = env_bool("CORS_ALLOW_ALL", False)

    # ---- API ------------------------------------------------------------
    API_PREFIX: str = "/api"
    HISTORY_PAGE_SIZE: int = env_int("HISTORY_PAGE_SIZE", 20)
    HISTORY_MAX_PAGE_SIZE: int = env_int("HISTORY_MAX_PAGE_SIZE", 200)

    # ---- Logging --------------------------------------------------------
    LOG_LEVEL: str = env_str("LOG_LEVEL", "INFO").upper()
    LOG_FILE: Optional[Path] = None

    # ------------------------------------------------------------------ #
    @classmethod
    def esp32_base_url(cls, ip_address: Optional[str] = None) -> Optional[str]:
        """``http://192.168.1.50:80`` or None when no IP is known yet."""
        host = ip_address or cls.ESP32_CAM_IP
        if not host:
            return None
        host = host.strip()
        if host.startswith(("http://", "https://")):
            return host.rstrip("/")
        port = cls.ESP32_CAM_PORT
        suffix = "" if port in (80, 0) else f":{port}"
        return f"http://{host}{suffix}"

    @classmethod
    def quality_thresholds(cls) -> dict:
        """Thresholds dictionary in the shape ``assess_image_quality`` expects."""
        return {
            "min_side_pixels": cls.QUALITY_MIN_SIDE_PIXELS,
            "min_sharpness": cls.QUALITY_MIN_SHARPNESS,
            "min_brightness": cls.QUALITY_MIN_BRIGHTNESS,
            "max_brightness": cls.QUALITY_MAX_BRIGHTNESS,
            "min_contrast": cls.QUALITY_MIN_CONTRAST,
            "min_plant_pixel_ratio": cls.QUALITY_MIN_PLANT_RATIO,
        }

    @classmethod
    def ensure_directories(cls) -> None:
        cls.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def as_dict(cls) -> dict:
        """Non-secret configuration, exposed by ``/api/health`` for debugging."""
        return {
            "host": cls.HOST,
            "port": cls.PORT,
            "debug": cls.DEBUG,
            "project_root": str(PROJECT_ROOT),
            "upload_folder": str(cls.UPLOAD_FOLDER),
            "max_upload_mb": cls.MAX_UPLOAD_MB,
            "allowed_extensions": sorted(cls.ALLOWED_EXTENSIONS),
            "database_path": str(cls.DATABASE_PATH),
            "model_path": str(cls.MODEL_PATH),
            "labels_path": str(cls.LABELS_PATH),
            "confidence_threshold": cls.CONFIDENCE_THRESHOLD,
            "enforce_quality_gate": cls.ENFORCE_QUALITY_GATE,
            "allow_test_mode_model": cls.ALLOW_TEST_MODE_MODEL,
            "universal_analysis_enabled": cls.UNIVERSAL_ANALYSIS_ENABLED,
            "vision_api_enabled": cls.VISION_API_ENABLED,
            "vision_api_provider": cls.VISION_API_PROVIDER if cls.VISION_API_ENABLED else None,
            "vision_api_configured": bool(cls.VISION_API_KEY),
            "esp32_cam_ip": cls.ESP32_CAM_IP,
            "esp32_cam_port": cls.ESP32_CAM_PORT,
            "esp32_offline_after_seconds": cls.ESP32_OFFLINE_AFTER_SECONDS,
            "push_capture_fallback": cls.ENABLE_PUSH_CAPTURE_FALLBACK,
            "device_key_required": bool(cls.DEVICE_API_KEY),
            "cors_origins": "*" if cls.CORS_ALLOW_ALL else cls.CORS_ORIGINS,
        }


class DevelopmentConfig(Config):
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    DEBUG = False
    # A real deployment should never silently serve an untrained model.
    ALLOW_TEST_MODE_MODEL = env_bool("ALLOW_TEST_MODE_MODEL", False)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    DATABASE_PATH = env_path("TEST_DATABASE_PATH", BACKEND_DIR / "database" / "test_plant_disease.db")
    EAGER_MODEL_LOAD = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": Config,
}


def get_config(name: Optional[str] = None) -> type[Config]:
    """Resolve a config class from ``FLASK_ENV`` / ``APP_ENV`` or an explicit name."""
    key = (name or os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "default").strip().lower()
    return CONFIG_MAP.get(key, Config)


__all__ = [
    "BACKEND_DIR",
    "PROJECT_ROOT",
    "ML_DIR",
    "Config",
    "DevelopmentConfig",
    "ProductionConfig",
    "TestingConfig",
    "get_config",
]
