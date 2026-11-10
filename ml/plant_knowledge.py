"""
plant_knowledge.py
==================
Loader for ``plant_knowledge.json``: per-species care information and
per-condition management guidance.

This is static reference text. It is looked up *after* the analysis has decided
what it is looking at, and never feeds back into that decision.

Two safety rules are enforced here rather than left to the caller:

1. **Chemical guidance is withheld when the assessment is uncertain.**
   ``get_treatment(condition_id, certain=False)`` returns the general
   plant-care plan instead of naming active ingredients. Suggesting a fungicide
   for a problem that might be drought stress is worse than suggesting nothing.

2. **No product names and no dosages exist anywhere in the data.** Chemical
   entries name documented active-ingredient *classes* and always carry
   ``requires_verification: true`` plus the shared disclaimer, because
   registration for a given crop differs by country and only the label is
   authoritative.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "plant_knowledge.json"
REFERENCE_PATH = Path(__file__).resolve().parent / "treatment_reference.json"

_EMPTY_TREATMENT: Dict[str, Any] = {
    "immediate_actions": [],
    "organic_options": [],
    "cultural_controls": [],
    "chemical_options": None,
    "prevention": [],
}


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace - for alias matching."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


@lru_cache(maxsize=4)
def _load(path: str) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("plant_knowledge.json not found at %s; guidance will be empty.", file_path)
        return {"species": {}, "conditions": {}, "generic_species": {}, "_lookup": {}}

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("plant_knowledge.json is not valid JSON (%s); guidance will be empty.", exc)
        return {"species": {}, "conditions": {}, "generic_species": {}, "_lookup": {}}

    # Build an alias lookup so "bell pepper", "capsicum" and "chilli" all land
    # on the pepper entry.
    lookup: Dict[str, str] = {}
    for key, entry in (payload.get("species") or {}).items():
        lookup[_normalise(key)] = key
        lookup[_normalise(entry.get("common_name", ""))] = key
        scientific = entry.get("scientific_name")
        if scientific:
            lookup[_normalise(scientific)] = key
            # Also index the genus on its own ("mangifera", "citrus").
            genus = _normalise(scientific).split(" ")[0]
            lookup.setdefault(genus, key)
        for alias in entry.get("aliases", ()) or ():
            lookup[_normalise(alias)] = key

    lookup.pop("", None)
    payload["_lookup"] = lookup

    _merge_reference(payload)
    return payload


def _merge_reference(payload: Dict[str, Any]) -> None:
    """
    Fold ``treatment_reference.json`` into the condition entries.

    The clinical material - descriptions, severity, cause categories, chemical
    precautions and citations - lives in its own file so it can be reviewed and
    sourced independently of the plant care profiles. Merging at load time means
    the rest of the code sees one combined structure and does not care that
    there are two files.
    """
    if not REFERENCE_PATH.is_file():
        logger.warning(
            "treatment_reference.json not found at %s; disease descriptions and "
            "severity will be missing.",
            REFERENCE_PATH,
        )
        payload.setdefault("severity_scale", {})
        payload.setdefault("cause_categories", {})
        return

    try:
        reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("treatment_reference.json is not valid JSON (%s).", exc)
        payload.setdefault("severity_scale", {})
        payload.setdefault("cause_categories", {})
        return

    payload["severity_scale"] = reference.get("severity_scale", {})
    payload["cause_categories"] = reference.get("cause_categories", {})

    conditions: Dict[str, Any] = payload.setdefault("conditions", {})
    clinical: Dict[str, Any] = reference.get("conditions", {}) or {}
    additions: Dict[str, Any] = reference.get("treatment_additions", {}) or {}

    for condition_id, info in clinical.items():
        entry = conditions.setdefault(condition_id, {})
        entry.setdefault("display_name", info.get("display_name", condition_id))
        entry["description"] = info.get("description", "")
        entry["severity"] = info.get("severity", "unknown")
        entry["cause_categories"] = info.get("cause_categories", [])
        entry["references"] = info.get("references", [])

        # Precautions belong with the chemical block they apply to.
        precautions = info.get("chemical_precautions") or []
        chemical = entry.get("chemical_options")
        if isinstance(chemical, dict):
            chemical["precautions"] = precautions
        elif precautions:
            # Precautions with no chemical block would be orphaned; keep them
            # on the entry so nothing is silently dropped.
            entry["chemical_precautions"] = precautions

    for condition_id, extra in additions.items():
        entry = conditions.get(condition_id)
        if not entry:
            continue
        if extra.get("organic_options"):
            entry["organic_options"] = list(extra["organic_options"])
        chemical = entry.get("chemical_options")
        if isinstance(chemical, dict) and extra.get("chemical_additions"):
            existing = list(chemical.get("active_ingredient_classes", []))
            for item in extra["chemical_additions"]:
                if item not in existing:
                    existing.append(item)
            chemical["active_ingredient_classes"] = existing


def reload_knowledge() -> None:
    """Drop the cache so an edited JSON file is picked up without a restart."""
    _load.cache_clear()


# --------------------------------------------------------------------------- #
# Species
# --------------------------------------------------------------------------- #

def list_species(path: str | Path = KNOWLEDGE_PATH) -> List[Dict[str, Any]]:
    """Every species with a care profile, for the dashboard's picker."""
    data = _load(str(path))
    return [
        {
            "id": key,
            "common_name": entry.get("common_name", key.title()),
            "scientific_name": entry.get("scientific_name"),
            "category": entry.get("category", "Unknown"),
            "common_issues": entry.get("common_issues", []),
        }
        for key, entry in sorted(
            (data.get("species") or {}).items(),
            key=lambda item: item[1].get("common_name", item[0]),
        )
    ]


def resolve_species_key(name: Optional[str], path: str | Path = KNOWLEDGE_PATH) -> Optional[str]:
    """
    Match a free-text plant name to a known species key.

    Tries an exact normalised match first, then a word-level containment check
    so "a mango leaf" or "Tomato (Solanum)" still resolve. Returns None when
    nothing matches, which the caller must treat as an unknown species rather
    than guessing.
    """
    if not name:
        return None

    data = _load(str(path))
    lookup: Dict[str, str] = data.get("_lookup", {})
    normalised = _normalise(name)
    if not normalised:
        return None

    if normalised in lookup:
        return lookup[normalised]

    # Longest alias first, so "bell pepper" wins over "pepper".
    for alias in sorted(lookup, key=len, reverse=True):
        if not alias:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", normalised):
            return lookup[alias]

    return None


def get_species_info(
    name: Optional[str],
    path: str | Path = KNOWLEDGE_PATH,
) -> Dict[str, Any]:
    """
    Care profile for a plant name.

    Always returns a usable dictionary. When the species is unknown it returns
    the generic profile with ``matched: False`` and ``id: None`` so the UI can
    say "unidentified plant" rather than silently showing tomato advice.
    """
    data = _load(str(path))
    key = resolve_species_key(name, path)

    if key is None:
        generic = dict(data.get("generic_species") or {})
        generic.update({"id": None, "matched": False, "requested_name": name})
        return generic

    entry = dict((data.get("species") or {}).get(key, {}))
    entry.update({"id": key, "matched": True, "requested_name": name})
    return entry


# --------------------------------------------------------------------------- #
# Treatments
# --------------------------------------------------------------------------- #

def get_treatment(
    condition_id: Optional[str],
    certain: bool = True,
    path: str | Path = KNOWLEDGE_PATH,
) -> Dict[str, Any]:
    """
    Management guidance for a condition.

    ``certain=False`` (an uncertain or weakly-supported assessment) replaces
    chemical guidance with the general plant-care plan. The returned dictionary
    always reports which happened via ``chemical_withheld`` and
    ``withheld_reason``, so the UI can explain the omission instead of leaving
    a blank section.
    """
    data = _load(str(path))
    conditions = data.get("conditions") or {}
    disclaimer = data.get("chemical_disclaimer", "")

    if not condition_id or condition_id not in conditions:
        guidance = dict(data.get("uncertain_guidance") or _EMPTY_TREATMENT)
        return {
            **_EMPTY_TREATMENT,
            **guidance,
            "condition_id": condition_id,
            "matched": False,
            "chemical_options": None,
            "chemical_withheld": True,
            "withheld_reason": (
                "No specific management plan is available for this condition, so only "
                "general plant-care steps are shown."
            ),
            "chemical_disclaimer": disclaimer,
        }

    entry = dict(conditions[condition_id])
    chemical = entry.get("chemical_options")

    if not certain and chemical:
        uncertain = data.get("uncertain_guidance") or {}
        return {
            **_EMPTY_TREATMENT,
            **entry,
            "condition_id": condition_id,
            "matched": True,
            # Keep the cultural and organic measures - they are safe whether or
            # not the diagnosis is right - but drop the chemicals.
            "immediate_actions": list(uncertain.get("immediate_actions", []))
            + list(entry.get("immediate_actions", [])),
            "chemical_options": None,
            "chemical_withheld": True,
            "withheld_reason": (
                "Chemical options are hidden because the assessment is not confident "
                "enough. Applying a treatment for the wrong cause wastes money, can "
                "damage the plant, and delays the right fix. Narrow the diagnosis down "
                "using the checks listed, then come back."
            ),
            "chemical_disclaimer": disclaimer,
        }

    return {
        **_EMPTY_TREATMENT,
        **entry,
        "condition_id": condition_id,
        "matched": True,
        "chemical_options": chemical,
        "chemical_withheld": False,
        "withheld_reason": None,
        "chemical_disclaimer": disclaimer if chemical else "",
    }


def get_condition_info(
    condition_id: Optional[str],
    path: str | Path = KNOWLEDGE_PATH,
) -> Dict[str, Any]:
    """
    Clinical reference for a condition: description, severity, cause categories.

    Used by the diagnosis dashboard's "Disease Information" panel. Always
    returns a dictionary, with ``matched: False`` when the id is unknown.
    """
    data = _load(str(path))
    entry = (data.get("conditions") or {}).get(condition_id or "")

    if not entry:
        return {
            "id": condition_id,
            "matched": False,
            "display_name": condition_id or "Unknown condition",
            "description": "",
            "severity": "unknown",
            "cause_categories": [],
            "references": [],
        }

    return {
        "id": condition_id,
        "matched": True,
        "display_name": entry.get("display_name", condition_id),
        "description": entry.get("description", ""),
        "severity": entry.get("severity", "unknown"),
        "cause_categories": entry.get("cause_categories", []),
        "references": entry.get("references", []),
    }


def severity_scale(path: str | Path = KNOWLEDGE_PATH) -> Dict[str, Any]:
    return dict(_load(str(path)).get("severity_scale") or {})


def cause_categories(path: str | Path = KNOWLEDGE_PATH) -> Dict[str, Any]:
    return dict(_load(str(path)).get("cause_categories") or {})


def all_conditions(path: str | Path = KNOWLEDGE_PATH) -> List[Dict[str, Any]]:
    """Every condition with its clinical reference, for ``GET /api/diseases``."""
    data = _load(str(path))
    output: List[Dict[str, Any]] = []
    for condition_id, entry in sorted((data.get("conditions") or {}).items()):
        output.append(
            {
                "id": condition_id,
                "display_name": entry.get("display_name", condition_id),
                "description": entry.get("description", ""),
                "severity": entry.get("severity", "unknown"),
                "cause_categories": entry.get("cause_categories", []),
                "references": entry.get("references", []),
                "has_chemical_options": isinstance(entry.get("chemical_options"), dict),
            }
        )
    return output


def all_treatments(path: str | Path = KNOWLEDGE_PATH) -> List[Dict[str, Any]]:
    """Every treatment plan, for ``GET /api/treatments``."""
    data = _load(str(path))
    disclaimer = data.get("chemical_disclaimer", "")
    output: List[Dict[str, Any]] = []
    for condition_id, entry in sorted((data.get("conditions") or {}).items()):
        output.append(
            {
                "condition_id": condition_id,
                "display_name": entry.get("display_name", condition_id),
                "severity": entry.get("severity", "unknown"),
                "immediate_actions": entry.get("immediate_actions", []),
                "organic_options": entry.get("organic_options", []),
                "cultural_controls": entry.get("cultural_controls", []),
                "chemical_options": entry.get("chemical_options"),
                "prevention": entry.get("prevention", []),
                "references": entry.get("references", []),
                "chemical_disclaimer": disclaimer
                if isinstance(entry.get("chemical_options"), dict)
                else "",
            }
        )
    return output


def get_uncertain_guidance(path: str | Path = KNOWLEDGE_PATH) -> Dict[str, Any]:
    """The general care plan used when no condition can be shortlisted."""
    data = _load(str(path))
    guidance = dict(data.get("uncertain_guidance") or _EMPTY_TREATMENT)
    return {
        **_EMPTY_TREATMENT,
        **guidance,
        "condition_id": None,
        "matched": False,
        "chemical_options": None,
        "chemical_withheld": True,
        "withheld_reason": (
            "No condition could be identified from the image, so no chemical treatment "
            "is suggested. These general steps are safe regardless of the cause."
        ),
        "chemical_disclaimer": data.get("chemical_disclaimer", ""),
    }


def condition_ids(path: str | Path = KNOWLEDGE_PATH) -> List[str]:
    return sorted((_load(str(path)).get("conditions") or {}).keys())


__all__ = [
    "KNOWLEDGE_PATH",
    "REFERENCE_PATH",
    "list_species",
    "resolve_species_key",
    "get_species_info",
    "get_treatment",
    "get_condition_info",
    "get_uncertain_guidance",
    "all_conditions",
    "all_treatments",
    "severity_scale",
    "cause_categories",
    "condition_ids",
    "reload_knowledge",
]


if __name__ == "__main__":  # python ml/plant_knowledge.py
    print(f"{len(list_species())} species profiles, {len(condition_ids())} condition plans\n")
    for species in list_species():
        print(f"  {species['common_name']:18s} {species['category']:16s} {species['scientific_name']}")

    print("\nAlias resolution:")
    for probe in ("bell pepper", "chilli", "Mangifera indica", "angoor", "a rose leaf", "dragonfruit"):
        print(f"  {probe:22s} -> {resolve_species_key(probe)}")

    print("\nChemical withholding when uncertain:")
    certain = get_treatment("late_blight", certain=True)
    uncertain = get_treatment("late_blight", certain=False)
    print(f"  certain=True  -> chemical_withheld={certain['chemical_withheld']}")
    print(f"  certain=False -> chemical_withheld={uncertain['chemical_withheld']}")
