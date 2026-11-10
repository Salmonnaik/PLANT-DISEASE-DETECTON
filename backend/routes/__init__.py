"""
Blueprint registration.

Kept in one place so ``app.py`` stays a thin factory and adding an endpoint
group means touching exactly one list.
"""

from __future__ import annotations

from flask import Flask

from routes.camera_routes import camera_bp
from routes.detection_routes import detection_bp
from routes.device_routes import device_bp
from routes.history_routes import history_bp
from routes.stats_routes import stats_bp
from routes.system_routes import system_bp

BLUEPRINTS = (system_bp, detection_bp, history_bp, stats_bp, device_bp, camera_bp)


def register_blueprints(app: Flask) -> None:
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)


__all__ = [
    "BLUEPRINTS",
    "register_blueprints",
    "system_bp",
    "detection_bp",
    "history_bp",
    "stats_bp",
    "device_bp",
    "camera_bp",
]
