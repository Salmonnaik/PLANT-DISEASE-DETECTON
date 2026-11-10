"""
disease_info.py
===============
Loads ``disease_info.json`` and resolves reference text for a class label.

This is static agronomic reference material (symptoms, management advice,
severity) that the dashboard shows *alongside* a prediction. It never takes part
in producing a prediction - the model alone decides the class, and this module
only looks up text for whichever class the model returned.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INFO_PATH = Path(__file__).resolve().parent / "disease_info.json"

_EMPTY_INFO: Dict[str, Any] = {
    "description": "No reference information is available for this class.",
    "symptoms": [],
    "management": [],
    "severity": "unknown",
}

SEVERITY_ORDER = {"none": 0, "unknown": 1, "mild": 2, "moderate": 3, "severe": 4}


def _normalise_key(raw_label: str) -> str:
    """Loose key used to match folder-name spelling variants."""
    return "".join(character for character in raw_label.lower() if character.isalnum())


@lru_cache(maxsize=4)
def _load_catalogue(info_path: str) -> Dict[str, Any]:
    path = Path(info_path)
    if not path.is_file():
        logger.warning("disease_info.json not found at %s; descriptions will be empty.", path)
        return {"classes": {}, "aliases": {}, "_fallback": dict(_EMPTY_INFO), "_normalised": {}}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("disease_info.json is not valid JSON (%s); descriptions will be empty.", exc)
        return {"classes": {}, "aliases": {}, "_fallback": dict(_EMPTY_INFO), "_normalised": {}}

    classes: Dict[str, Any] = payload.get("classes", {}) or {}
    aliases: Dict[str, str] = payload.get("aliases", {}) or {}

    normalised = {_normalise_key(name): name for name in classes}
    for alias, target in aliases.items():
        if target in classes:
            normalised.setdefault(_normalise_key(alias), target)

    return {
        "classes": classes,
        "aliases": aliases,
        "_fallback": {**_EMPTY_INFO, **(payload.get("_fallback") or {})},
        "_normalised": normalised,
    }


def reload_catalogue() -> None:
    """Drop the cache so an edited ``disease_info.json`` is picked up."""
    _load_catalogue.cache_clear()


def get_disease_info(
    raw_label: str,
    info_path: str | Path = DEFAULT_INFO_PATH,
) -> Dict[str, Any]:
    """
    Resolve reference text for a raw class label.

    Matching order: exact key, declared alias, then a punctuation-insensitive
    match (so ``Pepper__bell___healthy`` and ``Pepper,_bell___healthy`` resolve
    to the same entry). Always returns a dictionary - never ``None``.
    """
    catalogue = _load_catalogue(str(info_path))
    classes: Dict[str, Any] = catalogue["classes"]

    entry: Optional[Dict[str, Any]] = classes.get(raw_label)

    if entry is None:
        alias_target = catalogue["aliases"].get(raw_label)
        if alias_target:
            entry = classes.get(alias_target)

    if entry is None:
        resolved = catalogue["_normalised"].get(_normalise_key(raw_label))
        if resolved:
            entry = classes.get(resolved)

    if entry is None:
        return {**catalogue["_fallback"], "class": raw_label, "matched": False}

    return {
        **_EMPTY_INFO,
        **entry,
        "class": raw_label,
        "matched": True,
    }


def severity_rank(severity: str) -> int:
    """Numeric rank so the UI can sort or colour by urgency."""
    return SEVERITY_ORDER.get(str(severity).lower(), 1)


def all_known_classes(info_path: str | Path = DEFAULT_INFO_PATH) -> Dict[str, Any]:
    """Every reference entry, for the ``/api/disease-info`` endpoint."""
    return dict(_load_catalogue(str(info_path))["classes"])


__all__ = [
    "DEFAULT_INFO_PATH",
    "SEVERITY_ORDER",
    "get_disease_info",
    "all_known_classes",
    "severity_rank",
    "reload_catalogue",
]
