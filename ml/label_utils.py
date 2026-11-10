"""
label_utils.py
==============
Helpers for turning raw dataset folder names into human readable plant /
disease information.

The PlantVillage dataset stores one directory per class, using the convention
``<Plant>___<Disease>``, for example::

    Tomato___Early_blight
    Potato___healthy
    Pepper,_bell___Bacterial_spot

Everything in this module is pure string handling - no model, no randomness -
so the same raw label always maps to the same structured result.
"""

from __future__ import annotations

import re
from typing import Dict, List

# Separator used by PlantVillage between the plant and the disease part.
PRIMARY_SEPARATOR = "___"
FALLBACK_SEPARATORS = ("__", "--")

HEALTHY_TOKENS = {"healthy", "health", "normal", "fresh"}

# Words that should keep a fixed casing when humanising a label.
CASING_OVERRIDES = {
    "mold": "Mold",
    "mould": "Mould",
    "tmv": "TMV",
    "tylcv": "TYLCV",
    "ylcv": "YLCV",
    "virus": "Virus",
    "bell": "Bell",
    "two": "Two",
    "spotted": "Spotted",
}

# Normalised plant display names for known folder spellings.
PLANT_ALIASES = {
    "pepper, bell": "Bell Pepper",
    "pepper bell": "Bell Pepper",
    "pepper,bell": "Bell Pepper",
    "pepper": "Bell Pepper",
    "peppe": "Bell Pepper",
    "corn (maize)": "Corn",
    "cherry (including sour)": "Cherry",
    "orange": "Orange",
    "squash": "Squash",
}


def _clean_tokens(raw: str) -> List[str]:
    """Split a raw label fragment into lowercase word tokens."""
    text = raw.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return [token for token in text.split(" ") if token]


def humanise(raw: str) -> str:
    """``Septoria_leaf_spot`` -> ``Septoria Leaf Spot``."""
    tokens = _clean_tokens(raw)
    if not tokens:
        return ""

    words: List[str] = []
    for token in tokens:
        key = token.lower().strip(",.")
        if key in CASING_OVERRIDES:
            words.append(CASING_OVERRIDES[key])
        elif token.isupper() and len(token) > 1:
            # Already an acronym such as "TMV".
            words.append(token)
        else:
            words.append(token[:1].upper() + token[1:].lower())
    return " ".join(words)


def split_raw_label(raw_label: str) -> tuple[str, str]:
    """Split a raw class directory name into ``(plant_part, disease_part)``."""
    label = raw_label.strip().strip("/\\")

    if PRIMARY_SEPARATOR in label:
        plant_part, disease_part = label.split(PRIMARY_SEPARATOR, 1)
        return plant_part, disease_part

    for separator in FALLBACK_SEPARATORS:
        if separator in label:
            plant_part, disease_part = label.split(separator, 1)
            return plant_part, disease_part

    # Single-underscore convention, e.g. "Tomato_Early_blight".
    tokens = label.split("_")
    if len(tokens) > 1:
        return tokens[0], "_".join(tokens[1:])

    return label, ""


def _strip_redundant_plant_prefix(disease: str, plant: str) -> str:
    """``Tomato Yellow Leaf Curl Virus`` + plant ``Tomato`` -> ``Yellow Leaf Curl Virus``."""
    if not disease or not plant:
        return disease
    plant_first_word = plant.split(" ")[0].lower()
    tokens = disease.split(" ")
    if len(tokens) > 1 and tokens[0].lower() == plant_first_word:
        return " ".join(tokens[1:])
    return disease


def parse_label(raw_label: str) -> Dict[str, object]:
    """
    Convert a raw dataset folder name into structured label information.

    Returns a dictionary with:
        raw            - the original folder name (used as the canonical key)
        plant          - display name of the plant, e.g. "Tomato"
        disease        - display name of the condition, e.g. "Early Blight"
        display        - combined label, e.g. "Tomato - Early Blight"
        is_healthy     - True when the class represents a healthy leaf
        status         - "healthy" or "diseased"
    """
    plant_part, disease_part = split_raw_label(raw_label)

    plant = humanise(plant_part)
    plant_key = plant.lower()
    plant = PLANT_ALIASES.get(plant_key, plant)

    disease_tokens = _clean_tokens(disease_part)
    is_healthy = bool(disease_tokens) and disease_tokens[0].lower() in HEALTHY_TOKENS

    if is_healthy:
        disease = "Healthy"
    elif not disease_tokens:
        disease = "Unspecified"
    else:
        disease = _strip_redundant_plant_prefix(humanise(disease_part), plant)
        disease = disease or "Unspecified"

    return {
        "raw": raw_label,
        "plant": plant or "Unknown",
        "disease": disease,
        "display": f"{plant or 'Unknown'} - {disease}",
        "is_healthy": is_healthy,
        "status": "healthy" if is_healthy else "diseased",
    }


def parse_labels(raw_labels: List[str]) -> List[Dict[str, object]]:
    """Parse a list of raw folder names, preserving order (= model output order)."""
    return [parse_label(label) for label in raw_labels]


def build_label_catalogue(raw_labels: List[str]) -> Dict[str, object]:
    """
    Build the structure persisted to ``class_labels.json``.

    ``classes`` is index aligned with the model's softmax output, which is what
    makes the saved file the single source of truth for inference.
    """
    parsed = parse_labels(raw_labels)

    plants: Dict[str, List[str]] = {}
    for item in parsed:
        plants.setdefault(str(item["plant"]), [])
        disease = str(item["disease"])
        if disease not in plants[str(item["plant"])]:
            plants[str(item["plant"])].append(disease)

    return {
        "num_classes": len(parsed),
        "raw_labels": list(raw_labels),
        "classes": parsed,
        "plants": plants,
    }


if __name__ == "__main__":  # Small self check: python ml/label_utils.py
    samples = [
        "Tomato___Early_blight",
        "Tomato___Leaf_Mold",
        "Tomato___Septoria_leaf_spot",
        "Tomato___Tomato_Yellow_Leaf_Curl_Virus",
        "Tomato___healthy",
        "Potato___Late_blight",
        "Potato___healthy",
        "Pepper,_bell___Bacterial_spot",
        "Pepper__bell___healthy",
    ]
    for sample in samples:
        info = parse_label(sample)
        print(f"{sample:45s} -> {info['display']:40s} [{info['status']}]")
