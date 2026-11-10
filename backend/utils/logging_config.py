"""
utils/logging_config.py
=======================
Console (and optional file) logging setup.

Called as the very first thing in ``app.py`` because it also sets
``TF_CPP_MIN_LOG_LEVEL``, which TensorFlow only reads at import time. Since the
model is loaded lazily, setting it here successfully silences the oneDNN and
CUDA-probe banners that otherwise bury the useful startup output.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

LOG_FORMAT = "%(asctime)s  %(levelname)-7s [%(name)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"

# Third-party loggers that are noisy at INFO level.
QUIET_LOGGERS = {
    "werkzeug": logging.WARNING,
    "urllib3": logging.WARNING,
    "urllib3.connectionpool": logging.WARNING,
    "matplotlib": logging.WARNING,
    "PIL": logging.WARNING,
    "h5py": logging.WARNING,
}


class _ColourFormatter(logging.Formatter):
    """Colourised level names, enabled only on a real TTY."""

    COLOURS = {
        "DEBUG": "\033[38;5;245m",
        "INFO": "\033[38;5;35m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;203m",
        "CRITICAL": "\033[48;5;203;38;5;231m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        colour = self.COLOURS.get(original)
        if colour:
            record.levelname = f"{colour}{original}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original


def _supports_colour() -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def configure_logging(level: str = "INFO", log_file: Optional[Path] = None) -> logging.Logger:
    """Configure the root logger and return the application logger."""
    # Must happen before TensorFlow is imported anywhere in the process.
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    formatter_class = _ColourFormatter if _supports_colour() else logging.Formatter
    console.setFormatter(formatter_class(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(console)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)

    for name, quiet_level in QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(max(quiet_level, numeric_level))

    return logging.getLogger("plant-disease-backend")


def log_startup_banner(logger: logging.Logger, config_summary: dict) -> None:
    """Print the effective configuration so misconfiguration is obvious at boot."""
    logger.info("=" * 72)
    logger.info("  AI Plant Disease Detection - Flask backend")
    logger.info("=" * 72)
    width = max(len(key) for key in config_summary) if config_summary else 10
    for key, value in config_summary.items():
        logger.info("  %s : %s", key.ljust(width), value)
    logger.info("=" * 72)


__all__ = ["configure_logging", "log_startup_banner"]
