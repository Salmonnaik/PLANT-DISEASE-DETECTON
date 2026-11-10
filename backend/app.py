"""
app.py
======
Flask application factory and entry point.

    python app.py                 # start the API on 0.0.0.0:5000

Startup sequence (order matters):

1. configure logging - also sets ``TF_CPP_MIN_LOG_LEVEL`` before TensorFlow is
   ever imported, which keeps the banner readable,
2. create directories, open SQLite and apply the schema,
3. build the ML service and (by default) load the model eagerly so the first
   real prediction is not delayed by a 5-10 second model load,
4. build the ESP32-CAM service and make sure the configured device has a row,
5. register blueprints, the JSON error handlers and the ``/uploads`` route.

The banner prints this machine's LAN IP, which is the value that goes into
``FLASK_SERVER_IP`` in the ESP32-CAM sketch.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Make `backend/` importable whether the process starts here or at the repo root.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import Config, get_config  # noqa: E402
from utils.logging_config import configure_logging, log_startup_banner  # noqa: E402

# Logging first: TensorFlow reads TF_CPP_MIN_LOG_LEVEL at import time.
_config_class = get_config()
logger = configure_logging(_config_class.LOG_LEVEL, _config_class.LOG_FILE)

from flask import Flask, jsonify, redirect, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402

from database import db as database  # noqa: E402
from models import device as device_model  # noqa: E402
from routes import register_blueprints  # noqa: E402
from routes.system_routes import APP_NAME, APP_VERSION  # noqa: E402
from services.esp32_service import init_esp32_service  # noqa: E402
from services.ml_service import init_ml_service  # noqa: E402
from services.vision_service import init_vision_service  # noqa: E402
from utils.errors import register_error_handlers  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def detect_lan_ip() -> str:
    """
    This machine's address on the local network.

    Opens a UDP socket toward a public address - no packet is actually sent, but
    it makes the OS pick the interface it would route through, which is the one
    the ESP32-CAM has to reach. ``socket.gethostbyname(hostname)`` is unreliable
    here because it often returns 127.0.0.1 on Linux and a VPN address on
    Windows.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.3)
        probe.connect(("8.8.8.8", 80))
        return str(probe.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        probe.close()


def _configure_cors(app: Flask, config: Any) -> None:
    if config.CORS_ALLOW_ALL:
        logger.warning(
            "CORS_ALLOW_ALL is enabled - every origin may call this API. Convenient on "
            "a lab network, but do not leave it on for anything exposed beyond it."
        )
        CORS(app, resources={r"/api/*": {"origins": "*"}, r"/uploads/*": {"origins": "*"}})
        return

    CORS(
        app,
        resources={
            r"/api/*": {"origins": config.CORS_ORIGINS},
            r"/uploads/*": {"origins": config.CORS_ORIGINS},
        },
        supports_credentials=False,
    )


# --------------------------------------------------------------------------- #
# Application factory
# --------------------------------------------------------------------------- #

def create_app(config_name: Optional[str] = None, eager_model_load: Optional[bool] = None) -> Flask:
    """Build and wire the Flask application."""
    config = get_config(config_name)

    app = Flask(__name__, static_folder=None)
    app.config.from_object(config)
    app.config["CONFIG_CLASS"] = config
    app.config["CONFIG_SUMMARY"] = config.as_dict()

    config.ensure_directories()
    _configure_cors(app, config)

    # ---- database -------------------------------------------------------
    database.init_app(app)

    # ---- services -------------------------------------------------------
    eager = config.EAGER_MODEL_LOAD if eager_model_load is None else eager_model_load
    ml_service = init_ml_service(config, eager=eager)
    init_esp32_service(config)
    init_vision_service(config)

    # Make sure the configured camera has a row so the Device page has
    # something to show before the first heartbeat ever arrives.
    with app.app_context():
        try:
            device_model.ensure_device(config.ESP32_CAM_NAME, config.ESP32_CAM_IP)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not pre-register the configured device: %s", exc)

    # ---- routes ---------------------------------------------------------
    register_blueprints(app)
    register_error_handlers(app)

    @app.route("/uploads/<path:filename>")
    def serve_upload(filename: str):
        """
        Serve a stored leaf image.

        ``send_from_directory`` resolves the path against the upload folder and
        rejects anything that escapes it, so a crafted ``../`` cannot read
        arbitrary files.
        """
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route("/")
    def index():
        return jsonify(
            {
                "name": APP_NAME,
                "version": APP_VERSION,
                "message": "Backend is running. The dashboard runs separately on port 5173.",
                "api_index": "/api",
                "health": "/api/health",
            }
        )

    @app.route("/health")
    def health_alias():
        return redirect("/api/health", code=302)

    app.extensions["ml_service"] = ml_service
    return app


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def _startup_summary(app: Flask, lan_ip: str) -> Dict[str, Any]:
    config = app.config["CONFIG_CLASS"]
    ml_service = app.extensions["ml_service"]
    status = ml_service.status()

    if not status["loaded"]:
        model_line = "NOT LOADED - predictions are disabled"
    elif status["is_test_mode"]:
        model_line = "TEST MODE (untrained model - results are not real diagnoses)"
    else:
        accuracy = (status.get("metrics") or {}).get("accuracy")
        model_line = "trained" + (f", test accuracy {float(accuracy) * 100:.2f}%" if accuracy else "")

    return {
        "API": f"http://{lan_ip}:{config.PORT}/api",
        "Local API": f"http://127.0.0.1:{config.PORT}/api",
        "Dashboard": "http://localhost:5173  (start it with: cd frontend && npm run dev)",
        "Model": model_line,
        "Classes": status["num_classes"] or "unknown",
        "Confidence gate": f"{config.CONFIDENCE_THRESHOLD:.0%}",
        "Database": str(config.DATABASE_PATH),
        "Uploads": str(config.UPLOAD_FOLDER),
        "Camera name": config.ESP32_CAM_NAME,
        "Camera IP": config.ESP32_CAM_IP or "not set (device will self-register)",
        "FLASK_SERVER_IP for the sketch": lan_ip,
    }


def main() -> int:
    app = create_app()
    config = app.config["CONFIG_CLASS"]
    lan_ip = detect_lan_ip()

    log_startup_banner(logger, _startup_summary(app, lan_ip))

    status = app.extensions["ml_service"].status()
    if not status["loaded"]:
        logger.warning(
            "No model is loaded. /api/predict will return 503 until you run either:\n"
            "    python ml/train.py --dataset-dir ml/dataset   (real training)\n"
            "    python ml/create_test_model.py                (untrained, test mode only)"
        )
    elif status["is_test_mode"]:
        logger.warning(
            "TEST MODE ACTIVE - the loaded model is untrained. Every prediction is "
            "flagged is_validated_prediction=false and the dashboard shows a test-mode "
            "banner. Train a real model before presenting any results."
        )

    # use_reloader is off: the reloader would load the model twice and double
    # the memory footprint for no benefit on a single-file API.
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=True,
        use_reloader=bool(os.getenv("FLASK_USE_RELOADER", "")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
