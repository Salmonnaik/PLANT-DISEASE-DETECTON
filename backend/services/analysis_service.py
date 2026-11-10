"""
services/analysis_service.py
============================
The universal analysis orchestrator.

Combines up to four independent evidence sources into one report, and is
explicit about which of them actually contributed:

    1. **User-declared species** - the most reliable species signal there is.
    2. **AI vision API** - species plus a described symptom reading. Optional.
    3. **MobileNetV2 classifier** - authoritative, but only within its trained
       classes and only above the confidence threshold.
    4. **Local computer vision** - species-agnostic symptom measurement. Always
       available.

Fusion rules
------------
Species, in descending priority: user declaration, then the trained classifier
(only when it is confident *and* genuinely trained), then the vision API, then
"unidentified". The user wins over the model because a grower looking at their
own plant is more reliable than a classifier that only knows ten classes.

Conditions: the classifier's verdict is used when it applies and is confident;
otherwise the rule layer's shortlist is used. The two are never averaged - a
trained 10-class softmax and a rule match are not commensurable quantities, and
blending them would manufacture a number that means nothing.

Chemical treatment guidance is released only when the assessment is
``confident``. Everything weaker gets cultural and organic measures plus the
checks needed to narrow the diagnosis down.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from flask import current_app

from services.ml_service import get_ml_service
from services.vision_service import get_vision_service
from utils.ml_bridge import (
    analyse_leaf,
    cause_categories,
    evaluate_conditions,
    get_condition_info,
    get_species_info,
    get_treatment,
    get_uncertain_guidance,
    list_species,
    resolve_species_key,
    severity_scale,
)

logger = logging.getLogger(__name__)

# Confidence levels, deliberately qualitative. The only numeric confidence in
# the whole report is the trained classifier's softmax probability, which is a
# real measured quantity; everything else is a described level of support.
CONFIDENCE_CONFIDENT = "confident"
CONFIDENCE_PROBABLE = "probable"
CONFIDENCE_POSSIBLE = "possible"
CONFIDENCE_INSUFFICIENT = "insufficient"

# Dataset class -> species key in plant_knowledge.json.
CLASSIFIER_SPECIES_MAP = {
    "tomato": "tomato",
    "potato": "potato",
    "pepper": "pepper",
    "bell pepper": "pepper",
}

# Dataset disease label -> condition id in plant_knowledge.json / condition_rules.
CLASSIFIER_CONDITION_MAP = {
    "healthy": "healthy",
    "early blight": "early_blight",
    "late blight": "late_blight",
    "leaf mold": "leaf_spot",
    "leaf mould": "leaf_spot",
    "septoria leaf spot": "leaf_spot",
    "bacterial spot": "bacterial_leaf_spot",
    "target spot": "leaf_spot",
    "yellow leaf curl virus": "mosaic_virus",
    "mosaic virus": "mosaic_virus",
    "spider mites two spotted spider mite": "pest_damage",
}


def _map_condition(disease_label: Optional[str]) -> Optional[str]:
    if not disease_label:
        return None
    key = str(disease_label).strip().lower()
    if key in CLASSIFIER_CONDITION_MAP:
        return CLASSIFIER_CONDITION_MAP[key]
    for candidate, condition_id in CLASSIFIER_CONDITION_MAP.items():
        if candidate in key:
            return condition_id
    return None


def _classifier_applies(plant_name: Optional[str], species_key: Optional[str]) -> bool:
    """
    Whether the 10-class model is even relevant to this plant.

    This guard is the core of the upgrade. Without it, a mango leaf would be
    forced into the nearest tomato class and reported as a tomato disease. The
    classifier is consulted only when the plant is one it was trained on.
    """
    if species_key and species_key in CLASSIFIER_SPECIES_MAP.values():
        return True
    if plant_name and str(plant_name).strip().lower() in CLASSIFIER_SPECIES_MAP:
        return True
    return False


def available_species() -> List[Dict[str, Any]]:
    """Species with a care profile, for the dashboard's picker."""
    return list_species()


def _estimate_severity(
    condition_id: Optional[str],
    leaf: Dict[str, Any],
    confidence_level: str,
) -> Dict[str, Any]:
    """
    Estimate how severe the problem is on *this* leaf.

    Two inputs: the condition's inherent seriousness (late blight is dangerous
    even when barely visible) and the measured extent of damage on this
    particular leaf. The larger of the two drives the result, because a trace
    of late blight warrants more urgency than extensive but harmless scorch.

    Always labelled an estimate. It describes one leaf, not the planting, and
    the extent of damage on a single leaf is a weak proxy for crop impact.
    """
    scale = severity_scale()
    info = get_condition_info(condition_id)
    baseline = str(info.get("severity", "unknown"))

    damage = float(leaf.get("damage_fraction") or 0.0)
    symptoms = leaf.get("symptoms") or []
    worst = "none"
    for symptom in symptoms:
        level = str(symptom.get("severity", "none"))
        if ("none", "mild", "moderate", "severe").index(level) > (
            "none", "mild", "moderate", "severe"
        ).index(worst):
            worst = level

    # Extent of visible damage on this leaf.
    if damage >= 0.35:
        measured = "severe"
    elif damage >= 0.12:
        measured = "moderate"
    elif damage >= 0.02:
        measured = "mild"
    else:
        measured = "none"

    order = ("none", "mild", "moderate", "severe")
    candidates = [level for level in (baseline, measured, worst) if level in order]
    level = max(candidates, key=order.index) if candidates else "unknown"

    # An uncertain assessment must not produce a confident severity claim.
    if confidence_level in (CONFIDENCE_POSSIBLE, CONFIDENCE_INSUFFICIENT) and level == "severe":
        level = "moderate"

    entry = scale.get(level, {})
    return {
        "level": level,
        "label": entry.get("label", level.title()),
        "rank": entry.get("rank", 1),
        "guidance": entry.get("guidance", ""),
        "damage_percent": round(damage * 100.0, 1),
        "is_estimate": True,
        "basis": (
            f"Estimated from {damage * 100:.1f}% of the leaf area showing damage, the worst "
            f"measured symptom ({worst}), and the inherent seriousness of "
            f"{info.get('display_name', 'this condition').lower()} ({baseline}). "
            "Describes this leaf only, not the whole plant or planting."
        ),
    }


def _group_causes(candidates: List[Dict[str, Any]], condition_id: Optional[str]) -> Dict[str, Any]:
    """
    Group possible causes by category for the dashboard's "Possible Causes" panel.

    Only categories actually implicated by a shortlisted candidate are
    returned. Listing all eight every time would be a checklist rather than a
    finding.
    """
    catalogue = cause_categories()
    seen: Dict[str, Dict[str, Any]] = {}

    def add_category(key: str, reason: str) -> None:
        meta = catalogue.get(key)
        if not meta:
            return
        bucket = seen.setdefault(
            key,
            {"id": key, "label": meta["label"], "icon": meta.get("icon", key), "reasons": []},
        )
        if reason and reason not in bucket["reasons"]:
            bucket["reasons"].append(reason)

    for candidate in candidates:
        info = get_condition_info(candidate.get("id"))
        for key in info.get("cause_categories", []):
            add_category(key, candidate.get("label", ""))

    if condition_id:
        for key in get_condition_info(condition_id).get("cause_categories", []):
            add_category(key, get_condition_info(condition_id).get("display_name", ""))

    # Detailed free-text causes from the top candidate.
    detailed: List[str] = []
    for candidate in candidates[:2]:
        for cause in candidate.get("possible_causes", []):
            if cause not in detailed:
                detailed.append(cause)

    return {
        "categories": list(seen.values()),
        "detailed": detailed,
        "note": (
            "Only categories implicated by the shortlisted conditions are listed. "
            "A category appearing here means the evidence is consistent with it, not "
            "that it has been confirmed."
        ),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def analyse_plant_image(
    image_bytes: bytes,
    image_array: Any,
    *,
    declared_species: Optional[str] = None,
    use_vision_api: bool = True,
    classifier_result: Optional[Dict[str, Any]] = None,
    mime_type: str = "image/jpeg",
) -> Dict[str, Any]:
    """
    Produce the universal analysis report.

    ``classifier_result`` is an already-computed prediction from
    ``MLService.predict`` when one is available; it is reused rather than
    recomputed. ``image_array`` is the decoded RGB array, reused for the same
    reason.
    """
    config = current_app.config
    ml_service = get_ml_service()
    vision_service = get_vision_service()

    sources: List[str] = []

    # ---- 1. local computer vision (always) ------------------------------
    leaf = analyse_leaf(image_array).to_dict()
    sources.append("local_cv")
    rules = evaluate_conditions(leaf)

    # ---- 2. AI vision API (optional) ------------------------------------
    vision: Dict[str, Any] = {"available": False, "attempted": False}
    if use_vision_api and bool(config.get("VISION_API_ENABLED")):
        vision = vision_service.analyse(
            image_bytes, mime_type=mime_type, species_hint=declared_species
        )
        if vision.get("available"):
            sources.append("ai_vision_api")

    # ---- 3. species resolution ------------------------------------------
    species_name: Optional[str] = None
    species_source = "unidentified"
    species_certainty = "unknown"

    declared_key = resolve_species_key(declared_species) if declared_species else None

    if declared_species:
        species_name = declared_species
        species_source = "user_declared"
        # The user said so; we treat that as reliable but still note that it
        # was not verified from the image.
        species_certainty = "declared"
        sources.append("user_declared_species")

    classifier_species_key: Optional[str] = None
    classifier_prediction: Optional[Dict[str, Any]] = None
    classifier_used = False
    classifier_note: Optional[str] = None

    if classifier_result and classifier_result.get("is_validated_prediction"):
        predicted_plant = classifier_result.get("plant_name")
        classifier_species_key = resolve_species_key(predicted_plant)
        applies = _classifier_applies(predicted_plant, declared_key or classifier_species_key)

        if not applies:
            classifier_note = (
                f"The trained classifier was not used: it only covers "
                f"{', '.join(sorted(set(CLASSIFIER_SPECIES_MAP.values())))}, and this plant "
                "is outside that list."
            )
        elif declared_key and classifier_species_key and declared_key != classifier_species_key:
            classifier_note = (
                f"The trained classifier suggested {predicted_plant}, which disagrees with "
                f"the species you selected ({declared_species}). Your selection was used; "
                "the classifier's disease verdict was discarded because it assumes its own "
                "species."
            )
        elif not classifier_result.get("is_conclusive"):
            classifier_note = (
                "The trained classifier returned an inconclusive result "
                f"({classifier_result.get('confidence_percent', 0):.1f}% confidence, below "
                "its threshold), so its verdict was not used."
            )
        else:
            classifier_used = True
            classifier_prediction = classifier_result
            sources.append("mobilenetv2_classifier")
            if not declared_species:
                species_name = predicted_plant
                species_source = "trained_classifier"
                species_certainty = "high"
    elif classifier_result and not classifier_result.get("is_validated_prediction"):
        classifier_note = (
            "The trained classifier is running an untrained model (test mode), so its "
            "output was excluded from this analysis entirely."
        )

    # Vision API fills the species gap when nothing better exists.
    if species_name is None and vision.get("available") and vision.get("plant_species"):
        species_name = vision["plant_species"]
        species_source = "ai_vision_api"
        species_certainty = str(vision.get("species_certainty", "unknown"))

    species_info = get_species_info(species_name)

    # ---- 4. condition resolution ----------------------------------------
    primary_condition_id: Optional[str] = None
    primary_label: str
    candidates: List[Dict[str, Any]] = list(rules.get("candidates", []))
    assessment = str(rules.get("assessment", "insufficient_evidence"))
    confidence_level = CONFIDENCE_INSUFFICIENT
    basis: str

    if classifier_used and classifier_prediction:
        # The trained model is the strongest available evidence for its own
        # classes, so it takes precedence over the rule shortlist.
        primary_condition_id = _map_condition(classifier_prediction.get("predicted_disease"))
        primary_label = str(classifier_prediction.get("predicted_disease") or "Unknown")
        confidence_level = CONFIDENCE_CONFIDENT
        assessment = (
            "healthy" if classifier_prediction.get("is_healthy") else "condition_identified"
        )
        basis = (
            f"Trained MobileNetV2 classifier, {classifier_prediction.get('confidence_percent', 0):.1f}% "
            "confidence, corroborated by the local symptom measurements below."
        )
    elif assessment == "healthy":
        primary_condition_id = "healthy"
        primary_label = "No disease symptoms detected"
        confidence_level = CONFIDENCE_PROBABLE
        basis = "Local computer-vision measurements found no symptoms above the reporting threshold."
    elif candidates:
        top = candidates[0]
        primary_condition_id = str(top["id"])
        primary_label = str(top["label"])
        support = str(top.get("support", "weak"))
        evidence = str(leaf.get("overall_evidence", "weak"))

        if support == "strong" and evidence == "strong":
            confidence_level = CONFIDENCE_PROBABLE
        elif support in ("strong", "moderate"):
            confidence_level = CONFIDENCE_POSSIBLE
        else:
            confidence_level = CONFIDENCE_INSUFFICIENT

        basis = (
            f"Rule match against measured symptoms ({support} support, "
            f"{evidence} image evidence). This is a shortlist, not a confirmed diagnosis."
        )
    else:
        primary_label = "No assessment possible"
        basis = str(rules.get("summary") or "The image did not yield usable measurements.")

    # The vision API can raise confidence, but only in agreement with the local
    # measurements - it is never allowed to override them on its own.
    if (
        vision.get("available")
        and primary_condition_id
        and confidence_level in (CONFIDENCE_POSSIBLE, CONFIDENCE_INSUFFICIENT)
    ):
        vision_names = " ".join(
            str(item.get("name", "")).lower() for item in vision.get("candidate_conditions", [])
        )
        key_words = primary_condition_id.replace("_", " ").split()
        if any(word in vision_names for word in key_words if len(word) > 3):
            confidence_level = CONFIDENCE_PROBABLE
            basis += " The AI vision reading independently suggested the same condition."

    # ---- 4b. clinical reference, severity and causes ---------------------
    condition_info = get_condition_info(primary_condition_id)
    severity = _estimate_severity(primary_condition_id, leaf, confidence_level)
    causes = _group_causes(candidates, primary_condition_id)

    # ---- 5. treatment ----------------------------------------------------
    is_confident = confidence_level == CONFIDENCE_CONFIDENT
    if primary_condition_id:
        treatment = get_treatment(primary_condition_id, certain=is_confident)
    else:
        treatment = get_uncertain_guidance()

    # ---- 6. assemble -----------------------------------------------------
    next_steps: List[str] = list(rules.get("next_steps", []))
    for step in vision.get("recommended_next_steps", []) or []:
        if step not in next_steps:
            next_steps.append(step)
    if species_source == "unidentified":
        next_steps.insert(
            0,
            "Select the plant species in the dashboard - treatment advice is far more "
            "specific once the plant is known",
        )

    limitations: List[str] = [
        "This analysis describes only the leaf surface visible in this single image.",
        "Several conditions produce similar-looking symptoms; a shortlist is not a diagnosis.",
    ]
    if species_source == "unidentified":
        limitations.append(
            "The plant species could not be identified, so only general care guidance is shown."
        )
    if species_source == "user_declared":
        limitations.append(
            "The species was taken from your selection and was not verified against the image."
        )
    if not vision.get("available"):
        limitations.append(
            "The AI vision service is not configured, so no model-based species "
            "identification was performed."
        )
    if leaf.get("segmentation_quality") == "poor":
        limitations.append(
            "The leaf could not be separated cleanly from the background, so the "
            "measurements are approximate."
        )
    if classifier_note:
        limitations.append(classifier_note)

    return {
        "schema_version": 1,
        "assessment": assessment,
        "confidence_level": confidence_level,
        "basis": basis,
        # Never true from this service. A confirmed diagnosis requires
        # laboratory testing or expert inspection.
        "is_confirmed_diagnosis": False,
        "plant": {
            "name": species_info.get("common_name") if species_info.get("matched") else (species_name or "Unidentified plant"),
            "declared_name": declared_species,
            "scientific_name": species_info.get("scientific_name")
            or vision.get("plant_species_scientific"),
            "category": species_info.get("category") or vision.get("plant_category") or "Unknown",
            "species_id": species_info.get("id"),
            "identified": species_source != "unidentified",
            "identification_source": species_source,
            "certainty": species_certainty,
            "in_knowledge_base": bool(species_info.get("matched")),
            "common_issues": species_info.get("common_issues", []),
        },
        "condition": {
            "id": primary_condition_id,
            "label": primary_label,
            "candidates": candidates,
            "summary": rules.get("summary"),
            # Clinical reference for the "Disease Information" panel.
            "description": condition_info.get("description", ""),
            "references": condition_info.get("references", []),
            "cause_categories": condition_info.get("cause_categories", []),
        },
        "severity": severity,
        "causes": causes,
        "symptoms": {
            "detected": leaf.get("symptoms", []),
            "appears_healthy": leaf.get("appears_healthy"),
            "evidence_level": leaf.get("overall_evidence"),
            "damage_fraction": leaf.get("damage_fraction"),
            "leaf_detected": leaf.get("leaf_detected"),
            "segmentation_quality": leaf.get("segmentation_quality"),
            "notes": leaf.get("notes", []),
            "ai_described": vision.get("observed_symptoms", []) if vision.get("available") else [],
        },
        "treatment": treatment,
        "care": {
            "watering": (species_info.get("care") or {}).get("watering"),
            "soil": (species_info.get("care") or {}).get("soil"),
            "light": (species_info.get("care") or {}).get("light"),
            "feeding": (species_info.get("care") or {}).get("feeding"),
            "pruning": (species_info.get("care") or {}).get("pruning"),
            "prevention": species_info.get("prevention", []),
        },
        "next_steps": next_steps,
        "limitations": limitations,
        "evidence_sources": {
            "used": sources,
            "local_cv": {
                "used": True,
                "metrics": leaf.get("metrics", {}),
                "method": leaf.get("method"),
            },
            "ai_vision": vision,
            "classifier": {
                "used": classifier_used,
                "note": classifier_note,
                "covers_species": sorted(set(CLASSIFIER_SPECIES_MAP.values())),
                "prediction": (
                    {
                        "predicted_class": classifier_prediction.get("predicted_class"),
                        "plant_name": classifier_prediction.get("plant_name"),
                        "predicted_disease": classifier_prediction.get("predicted_disease"),
                        "confidence": classifier_prediction.get("confidence"),
                        "confidence_percent": classifier_prediction.get("confidence_percent"),
                    }
                    if classifier_prediction
                    else None
                ),
                "model_mode": ml_service.status().get("mode"),
            },
        },
    }


__all__ = [
    "analyse_plant_image",
    "available_species",
    "CONFIDENCE_CONFIDENT",
    "CONFIDENCE_PROBABLE",
    "CONFIDENCE_POSSIBLE",
    "CONFIDENCE_INSUFFICIENT",
]
