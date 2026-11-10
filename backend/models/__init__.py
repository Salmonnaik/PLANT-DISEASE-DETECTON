"""Data-access layer: thin, typed wrappers over the SQLite tables."""

from models import detection, device  # noqa: F401

__all__ = ["detection", "device"]
