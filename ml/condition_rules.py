"""
condition_rules.py
==================
Maps measured leaf symptoms onto *possible* conditions.

This is the inference layer between `leaf_analysis.py` (which only measures)
and the user. Three principles govern it:

1. **Possibilities, not a diagnosis.** Every candidate carries
   ``is_diagnosis: False`` and the evidence that put it on the list. Several
   conditions produce indistinguishable symptoms on a single photograph, so the
   output is a ranked shortlist, not an answer.

2. **No invented numbers.** Support is reported as ``strong`` / ``moderate`` /
   ``weak``, derived from how many rule criteria the measurements satisfied.
   There is no probability, because a rule match is not a probability and
   printing one would imply a calibration that does not exist.

3. **Damage is not automatically disease.** The rule set deliberately includes
   non-pathogenic explanations - nutrient deficiency, drought and salt scorch,
   insect feeding, mechanical injury, natural senescence - because the most
   common cause of a damaged leaf is often not an infection. A rule set
   containing only diseases would find a disease in every image.

Each rule also lists ``confirm_by``: what a person should look at next to tell
the shortlisted candidates apart. That is the genuinely useful output when the
image alone cannot decide.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

SUPPORT_LEVELS = ("weak", "moderate", "strong")


@dataclass
class ConditionCandidate:
    """One possible explanation for the observed symptoms."""

    id: str
    label: str
    category: str                      # fungal | bacterial | viral | pest | abiotic | none
    support: str                       # weak | moderate | strong
    is_disease: bool
    matched_evidence: List[str] = field(default_factory=list)
    conflicting_evidence: List[str] = field(default_factory=list)
    possible_causes: List[str] = field(default_factory=list)
    confirm_by: List[str] = field(default_factory=list)
    # Never true from this module. Present so downstream consumers cannot
    # accidentally treat a rule match as a confirmed diagnosis.
    is_diagnosis: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Rule definitions
# --------------------------------------------------------------------------- #
# required_any   at least one of these symptoms must be present
# required_all   all of these symptoms must be present
# supporting     each present symptom strengthens the match
# conflicting    each present symptom weakens the match
# metric_checks  (metric key, comparison, threshold, human description)
# patterns       lesion patterns that strengthen the match

RULES: Sequence[Dict[str, Any]] = (
    {
        "id": "healthy",
        "label": "No disease symptoms detected",
        "category": "none",
        "is_disease": False,
        "healthy_rule": True,
        "possible_causes": [],
        "confirm_by": [
            "Check the underside of the leaf, where mildews and mites appear first",
            "Inspect older, lower leaves - most foliar diseases start there",
        ],
    },
    {
        "id": "leaf_spot",
        "label": "Leaf spot (general fungal or bacterial spotting)",
        "category": "fungal",
        "is_disease": True,
        "required_any": ["dark_spots", "brown_necrosis"],
        "supporting": ["yellowing"],
        "conflicting": ["powdery_coating", "margin_necrosis"],
        "patterns": ["many_small_round_spots", "many_small_irregular_spots", "scattered_lesions"],
        "metric_checks": [
            ("lesions.count", ">=", 3, "three or more discrete lesions were counted"),
            ("lesions.mean_area_fraction", "<=", 0.02, "lesions are small relative to the leaf"),
        ],
        "possible_causes": [
            "Several fungal genera (Septoria, Cercospora, Alternaria) and some bacteria",
            "Prolonged leaf wetness from overhead watering or rain splash",
            "Spores carried from infected crop debris left on the soil",
        ],
        "confirm_by": [
            "Look for tiny dark fruiting bodies in the centre of the spots with a hand lens",
            "Check whether spots have a yellow halo, which suggests a bacterial cause",
            "Note whether spots are limited by leaf veins (angular) or cross them (round)",
        ],
    },
    {
        "id": "bacterial_leaf_spot",
        "label": "Bacterial leaf spot",
        "category": "bacterial",
        "is_disease": True,
        "required_all": ["dark_spots"],
        "supporting": ["yellowing", "brown_necrosis"],
        "conflicting": ["powdery_coating"],
        "patterns": ["many_small_irregular_spots", "many_small_round_spots"],
        "metric_checks": [
            ("lesions.count", ">=", 4, "numerous small lesions were counted"),
            ("chlorotic_yellow_fraction", ">=", 0.03, "yellowing surrounds the lesions"),
        ],
        "possible_causes": [
            "Xanthomonas or Pseudomonas species, usually seed-borne or splash-spread",
            "Warm, wet, windy weather",
            "Handling or harvesting the crop while the foliage is wet",
        ],
        "confirm_by": [
            "Hold the leaf to the light: bacterial spots often look water-soaked at the edge",
            "Check whether lesions are angular, bounded by the veins",
            "Look for the same spotting on stems and fruit",
        ],
    },
    {
        "id": "early_blight",
        "label": "Early blight",
        "category": "fungal",
        "is_disease": True,
        "required_any": ["brown_necrosis"],
        "supporting": ["yellowing", "dark_spots"],
        # Necrosis confined to the leaf edge is a scorch pattern, not a
        # spotting pathogen, so it argues against blight.
        "conflicting": ["powdery_coating", "margin_necrosis"],
        "patterns": ["few_round_lesions", "scattered_lesions", "many_small_round_spots"],
        "metric_checks": [
            ("necrotic_brown_fraction", ">=", 0.02, "a measurable area of brown necrosis is present"),
            ("interior_necrosis_fraction", ">=", 0.02, "necrosis is present within the leaf, not only at the edge"),
        ],
        "possible_causes": [
            "Alternaria solani, which overwinters in crop debris",
            "Plants under nitrogen or drought stress, which lose lower leaves fastest",
            "Warm temperatures with alternating wet and dry periods",
        ],
        "confirm_by": [
            "Look for concentric rings inside the lesion, giving a target-board pattern",
            "Check whether the lowest, oldest leaves are worst affected",
            "Confirm the host: early blight is a solanaceous disease (tomato, potato)",
        ],
    },
    {
        "id": "late_blight",
        "label": "Late blight",
        "category": "fungal",
        "is_disease": True,
        "required_any": ["brown_necrosis", "dark_spots"],
        "supporting": ["distorted_outline"],
        # A continuous necrotic rim reads as one large blob to the lesion
        # detector, which would otherwise look exactly like a blight patch.
        "conflicting": ["powdery_coating", "holes_and_damage", "margin_necrosis"],
        "patterns": ["large_irregular_patches"],
        "metric_checks": [
            ("lesions.largest_area_fraction", ">=", 0.06, "at least one large irregular lesion was measured"),
            ("necrotic_brown_fraction", ">=", 0.05, "a substantial area of the leaf is necrotic"),
        ],
        "possible_causes": [
            "Phytophthora infestans - cool, wet, humid conditions",
            "Infected seed tubers or nearby volunteer plants",
            "Dense canopy that stays wet for long periods",
        ],
        "confirm_by": [
            "URGENT: look for white fuzzy growth on the underside of the lesion edge in humid air",
            "Check whether lesions are greasy and water-soaked rather than dry and papery",
            "Late blight spreads within days - re-inspect the plant tomorrow",
        ],
    },
    {
        "id": "powdery_mildew",
        "label": "Powdery mildew",
        "category": "fungal",
        "is_disease": True,
        "required_all": ["powdery_coating"],
        "supporting": ["yellowing", "distorted_outline"],
        "conflicting": [],
        "metric_checks": [
            ("powdery_white_fraction", ">=", 0.015, "a pale, desaturated surface film was measured"),
        ],
        "possible_causes": [
            "Several powdery mildew fungi, which need no free water to infect",
            "Warm days with cool, humid nights",
            "Poor air circulation and shaded, crowded foliage",
        ],
        "confirm_by": [
            "Try wiping the white film with a finger - powdery mildew rubs off, mineral deposits do not",
            "Check the upper leaf surface first; this is where it usually starts",
            "Distinguish from downy mildew, which grows on the underside and looks greyish, not white",
        ],
    },
    {
        "id": "downy_mildew",
        "label": "Downy mildew",
        "category": "fungal",
        "is_disease": True,
        "required_any": ["yellowing"],
        "supporting": ["brown_necrosis", "powdery_coating"],
        "conflicting": ["holes_and_damage"],
        "metric_checks": [
            ("chlorotic_yellow_fraction", ">=", 0.06, "distinct yellow patches are present"),
        ],
        "possible_causes": [
            "Oomycete pathogens requiring cool temperatures and high humidity",
            "Extended leaf wetness, especially overnight",
            "Air-borne spores from nearby infected plantings",
        ],
        "confirm_by": [
            "Examine the UNDERSIDE directly beneath the yellow patches for greyish-purple fuzz",
            "Check whether the yellow patches are angular, bounded by the veins",
            "Compare with simple nutrient chlorosis, which is uniform rather than patchy",
        ],
    },
    {
        "id": "rust",
        "label": "Rust disease",
        "category": "fungal",
        "is_disease": True,
        "required_all": ["rust_coloured_pustules"],
        "supporting": ["yellowing", "brown_necrosis"],
        "conflicting": ["powdery_coating"],
        "metric_checks": [
            ("rust_orange_fraction", ">=", 0.004, "reddish-orange pustule colour was measured"),
        ],
        "possible_causes": [
            "Rust fungi, many with a narrow host range",
            "Moderate temperatures with dew or frequent light rain",
            "Spores blown from alternate host plants nearby",
        ],
        "confirm_by": [
            "Rub a pustule with white paper - rust leaves an orange powder stain",
            "Check whether pustules are raised and erupt through the surface",
            "Look at the leaf underside, where pustules are usually denser",
        ],
    },
    {
        "id": "anthracnose",
        "label": "Anthracnose",
        "category": "fungal",
        "is_disease": True,
        "required_any": ["dark_spots", "brown_necrosis"],
        "supporting": ["holes_and_damage"],
        "conflicting": ["powdery_coating", "margin_necrosis"],
        "patterns": ["few_round_lesions", "large_irregular_patches"],
        "metric_checks": [
            ("dark_spot_fraction", ">=", 0.01, "dark, well-defined lesions are present"),
            ("lesions.mean_circularity", ">=", 0.35, "lesions are roughly rounded rather than streaked"),
        ],
        "possible_causes": [
            "Colletotrichum species, spread by rain splash",
            "Warm, wet weather and extended fruit or leaf wetness",
            "Infected plant debris or pruning wounds",
        ],
        "confirm_by": [
            "Look for sunken lesions, sometimes with a salmon-pink spore mass in the centre when humid",
            "Check twigs and fruit, which anthracnose commonly also attacks",
            "Note whether lesion centres have dried and dropped out, leaving a hole",
        ],
    },
    {
        "id": "leaf_scorch",
        "label": "Leaf scorch or marginal burn",
        "category": "abiotic",
        "is_disease": False,
        "required_all": ["margin_necrosis"],
        "supporting": ["brown_necrosis", "distorted_outline"],
        "conflicting": ["powdery_coating", "rust_coloured_pustules"],
        "metric_checks": [
            ("margin_necrosis_fraction", ">=", 0.06, "necrosis is concentrated in the edge band"),
        ],
        "possible_causes": [
            "Water stress - either drought or waterlogged roots that cannot take water up",
            "Salt accumulation from over-fertilising or hard water",
            "Wind burn, heat stress, or sun scorch on a leaf not acclimatised to full sun",
            "Root damage or a pot that has become root-bound",
            "Some bacterial scorch diseases also cause this pattern, so it is not always abiotic",
        ],
        "confirm_by": [
            "Check soil moisture at root depth rather than at the surface",
            "Review recent fertiliser applications and whether the pot drains freely",
            "Look at whether the whole plant is affected uniformly, which points to a root or water cause",
        ],
    },
    {
        "id": "mosaic_virus",
        "label": "Mosaic-like symptoms (possible virus)",
        "category": "viral",
        "is_disease": True,
        "required_all": ["mottling"],
        "supporting": ["distorted_outline", "yellowing"],
        "conflicting": ["powdery_coating", "margin_necrosis", "rust_coloured_pustules"],
        "metric_checks": [
            ("mottling_score", ">=", 0.17, "green tone varies in large patches across the leaf"),
        ],
        "possible_causes": [
            "Mosaic viruses, spread mechanically by hands and tools or by insect vectors",
            "Infected seed or propagation material",
            "Aphid, whitefly or thrips feeding transmitting virus between plants",
            "Note: variegated cultivars and mineral deficiencies can mimic mosaic patterning",
        ],
        "confirm_by": [
            "Check whether new growth is distorted, narrowed or strap-like",
            "Confirm the plant is not a naturally variegated variety",
            "Look for stunting compared with healthy neighbours - laboratory testing is the only certain confirmation",
        ],
    },
    {
        "id": "pest_damage",
        "label": "Insect or pest feeding damage",
        "category": "pest",
        "is_disease": False,
        "required_all": ["holes_and_damage"],
        "supporting": ["distorted_outline", "yellowing"],
        "conflicting": [],
        "metric_checks": [
            ("hole_fraction", ">=", 0.004, "gaps enclosed by the leaf outline were measured"),
        ],
        "possible_causes": [
            "Chewing insects - caterpillars, beetles, grasshoppers, slugs or snails",
            "Leaf miners, which leave winding pale tunnels rather than open holes",
            "Mechanical injury from wind, hail or handling, which can look similar",
        ],
        "confirm_by": [
            "Inspect the undersides and leaf axils for the insect itself, eggs or frass",
            "Check at dusk or night, when many chewing pests feed",
            "Ragged edges suggest chewing; clean round holes suggest beetles; silvery trails suggest slugs",
        ],
    },
    {
        "id": "nutrient_deficiency",
        "label": "Nutrient deficiency or chlorosis",
        "category": "abiotic",
        "is_disease": False,
        "required_all": ["yellowing"],
        "supporting": [],
        "conflicting": ["holes_and_damage", "powdery_coating", "rust_coloured_pustules", "dark_spots"],
        "metric_checks": [
            ("chlorotic_yellow_fraction", ">=", 0.08, "a large proportion of the leaf is yellowed"),
            ("necrotic_brown_fraction", "<=", 0.04, "little or no necrotic tissue accompanies the yellowing"),
            ("lesions.count", "<=", 2, "few or no discrete lesions are present"),
        ],
        "possible_causes": [
            "Nitrogen shortage - uniform paling, oldest leaves first",
            "Iron or manganese shortage - yellowing between green veins, youngest leaves first",
            "Magnesium shortage - yellowing between veins on older leaves",
            "Soil pH locking up nutrients that are physically present",
            "Waterlogged or compacted roots unable to take nutrients up",
        ],
        "confirm_by": [
            "Note the pattern: are the veins still green while the tissue between them yellows?",
            "Note which leaves are affected - oldest first suggests nitrogen or magnesium, youngest first suggests iron",
            "A soil test for pH and nutrients is the only way to be sure",
        ],
    },
    {
        "id": "senescence",
        "label": "Natural ageing of an old leaf",
        "category": "abiotic",
        "is_disease": False,
        "required_any": ["yellowing", "brown_necrosis"],
        "supporting": [],
        "conflicting": ["powdery_coating", "rust_coloured_pustules", "mottling", "holes_and_damage"],
        "metric_checks": [
            ("lesions.count", "<=", 3, "few discrete lesions - the change is diffuse rather than spotted"),
        ],
        "possible_causes": [
            "Normal senescence: the plant reclaims nutrients from its oldest leaves",
            "End of the growing season or post-fruiting decline",
        ],
        "confirm_by": [
            "Check whether only the lowest, oldest leaves are affected while new growth is healthy",
            "If the rest of the plant is vigorous, this needs no treatment beyond removing the old leaf",
        ],
    },
)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #

def _metric(metrics: Dict[str, Any], path: str) -> Optional[float]:
    """Read a possibly nested metric, e.g. ``lesions.count``."""
    node: Any = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    try:
        return float(node)
    except (TypeError, ValueError):
        return None


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    if operator == "<":
        return value < threshold
    raise ValueError(f"Unsupported comparison operator: {operator!r}")


def _evaluate_rule(
    rule: Dict[str, Any],
    symptom_ids: set[str],
    severities: Dict[str, str],
    metrics: Dict[str, Any],
) -> Optional[ConditionCandidate]:
    """Score one rule against the measurements. Returns None if it does not apply."""
    required_all = set(rule.get("required_all", ()))
    required_any = set(rule.get("required_any", ()))

    if required_all and not required_all.issubset(symptom_ids):
        return None
    if required_any and not (required_any & symptom_ids):
        return None
    if not required_all and not required_any:
        return None

    matched: List[str] = []
    conflicting: List[str] = []

    # Required symptoms, reported with their measured severity.
    for symptom_id in sorted((required_all | required_any) & symptom_ids):
        severity = severities.get(symptom_id, "present")
        matched.append(f"{symptom_id.replace('_', ' ')} present ({severity})")

    supporting_hits = 0
    for symptom_id in rule.get("supporting", ()):
        if symptom_id in symptom_ids:
            supporting_hits += 1
            matched.append(f"supporting sign: {symptom_id.replace('_', ' ')}")

    for symptom_id in rule.get("conflicting", ()):
        if symptom_id in symptom_ids:
            conflicting.append(
                f"{symptom_id.replace('_', ' ')} is present, which is not typical of this condition"
            )

    # Quantitative criteria.
    metric_hits = 0
    metric_total = 0
    for path, operator, threshold, description in rule.get("metric_checks", ()):
        metric_total += 1
        value = _metric(metrics, path)
        if value is None:
            continue
        if _compare(value, operator, float(threshold)):
            metric_hits += 1
            matched.append(description)
        else:
            conflicting.append(f"not met: {description}")

    # Lesion morphology.
    pattern = str(_nested_str(metrics, "lesions.pattern") or "none")
    patterns = rule.get("patterns")
    pattern_hit = False
    if patterns:
        if pattern in patterns:
            pattern_hit = True
            matched.append(f"lesion pattern is {pattern.replace('_', ' ')}")
        elif pattern not in ("none", ""):
            conflicting.append(
                f"lesion pattern is {pattern.replace('_', ' ')}, which is less typical here"
            )

    # Support level. Deliberately conservative: "strong" needs the quantitative
    # criteria satisfied as well as the symptom pattern, and any conflicting
    # evidence caps the result.
    metric_ratio = (metric_hits / metric_total) if metric_total else 1.0
    has_moderate_plus = any(
        severities.get(symptom_id) in ("moderate", "severe")
        for symptom_id in (required_all | required_any) & symptom_ids
    )

    if metric_ratio >= 0.99 and has_moderate_plus and (supporting_hits or pattern_hit):
        support = "strong"
    elif metric_ratio >= 0.5 and (has_moderate_plus or supporting_hits or pattern_hit):
        support = "moderate"
    else:
        support = "weak"

    if conflicting and support == "strong":
        support = "moderate"
    if len(conflicting) >= 3 and support == "moderate":
        support = "weak"

    return ConditionCandidate(
        id=str(rule["id"]),
        label=str(rule["label"]),
        category=str(rule["category"]),
        support=support,
        is_disease=bool(rule.get("is_disease", True)),
        matched_evidence=matched,
        conflicting_evidence=conflicting,
        possible_causes=list(rule.get("possible_causes", ())),
        confirm_by=list(rule.get("confirm_by", ())),
    )


def _nested_str(metrics: Dict[str, Any], path: str) -> Optional[str]:
    node: Any = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return str(node) if node is not None else None


def evaluate_conditions(analysis: Dict[str, Any], max_candidates: int = 4) -> Dict[str, Any]:
    """
    Produce a ranked shortlist of possible conditions from a leaf analysis.

    ``analysis`` is the dictionary returned by
    ``leaf_analysis.analyse_leaf(...).to_dict()``.

    Returns a dictionary with ``candidates``, an ``assessment`` string
    (``healthy`` / ``symptoms_observed`` / ``insufficient_evidence``) and the
    next steps to take.
    """
    if not analysis.get("analysed") or not analysis.get("leaf_detected"):
        return {
            "assessment": "insufficient_evidence",
            "candidates": [],
            "summary": (
                analysis.get("reason")
                or "No leaf region could be measured, so no assessment is possible."
            ),
            "next_steps": [
                "Photograph a single leaf filling most of the frame",
                "Use even, indirect lighting and a plain, contrasting background",
                "Hold the camera steady and let it focus before capturing",
            ],
        }

    symptoms = analysis.get("symptoms", []) or []
    symptom_ids = {str(item["id"]) for item in symptoms}
    severities = {str(item["id"]): str(item["severity"]) for item in symptoms}
    metrics = analysis.get("metrics", {}) or {}

    # ---- healthy -------------------------------------------------------
    if analysis.get("appears_healthy") and not symptom_ids:
        healthy_rule = next(rule for rule in RULES if rule.get("healthy_rule"))
        green = _metric(metrics, "healthy_green_fraction") or 0.0
        candidate = ConditionCandidate(
            id=str(healthy_rule["id"]),
            label=str(healthy_rule["label"]),
            category="none",
            support="moderate",
            is_disease=False,
            matched_evidence=[
                f"{green * 100:.0f}% of the leaf area is healthy green tissue",
                "No lesions, yellowing, powdery coating or holes exceeded the reporting threshold",
            ],
            conflicting_evidence=[],
            possible_causes=[],
            confirm_by=list(healthy_rule["confirm_by"]),
        )
        return {
            "assessment": "healthy",
            "candidates": [candidate.to_dict()],
            "summary": (
                "No disease symptoms were measurable on this leaf. This describes the "
                "leaf surface that is visible in the image only - early infections and "
                "underside symptoms will not show up."
            ),
            "next_steps": [
                "Keep monitoring weekly, checking leaf undersides and lower foliage",
                "Maintain even watering and good airflow around the plant",
            ],
        }

    # ---- symptomatic ---------------------------------------------------
    candidates: List[ConditionCandidate] = []
    for rule in RULES:
        if rule.get("healthy_rule"):
            continue
        candidate = _evaluate_rule(rule, symptom_ids, severities, metrics)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            -SUPPORT_LEVELS.index(item.support),
            -len(item.matched_evidence),
            len(item.conflicting_evidence),
        )
    )
    shortlist = candidates[:max_candidates]

    if not shortlist:
        return {
            "assessment": "insufficient_evidence",
            "candidates": [],
            "summary": (
                "Some irregularities were measured but they do not match any condition "
                "pattern closely enough to shortlist. The symptoms may be too early, or "
                "the image may not show them clearly."
            ),
            "next_steps": [
                "Re-photograph the most affected leaf, including its underside",
                "Describe what changed recently: watering, feeding, weather, repotting",
                "Re-check in three to five days to see whether symptoms progress",
            ],
        }

    strongest = shortlist[0]
    evidence_level = str(analysis.get("overall_evidence", "weak"))

    disease_candidates = [item for item in shortlist if item.is_disease]
    non_disease = [item for item in shortlist if not item.is_disease]

    summary_parts: List[str] = []
    if strongest.support == "strong":
        summary_parts.append(
            f"The measured symptoms are most consistent with {strongest.label.lower()}"
        )
    else:
        summary_parts.append(
            f"The measured symptoms are only loosely consistent with {strongest.label.lower()}"
        )
    if len(shortlist) > 1:
        others = ", ".join(item.label.lower() for item in shortlist[1:])
        summary_parts.append(f"other possibilities that fit the same evidence: {others}")
    if non_disease and disease_candidates:
        summary_parts.append(
            "note that non-disease causes are also on this list - damage alone does not "
            "mean infection"
        )

    next_steps = [
        "Work through the 'what to check next' items to narrow the list down",
        "Photograph the leaf underside and a second affected leaf",
    ]
    if evidence_level in ("weak", "insufficient"):
        next_steps.insert(
            0,
            "Image evidence is limited - retake the photograph closer, in even light, "
            "before acting on any of these possibilities",
        )
    if any(item.id == "late_blight" for item in shortlist):
        next_steps.insert(
            0,
            "Late blight is on the shortlist. If confirmed it spreads within days - "
            "inspect the whole planting today",
        )

    return {
        "assessment": "symptoms_observed",
        "candidates": [item.to_dict() for item in shortlist],
        "summary": ". ".join(part[0].upper() + part[1:] for part in summary_parts) + ".",
        "next_steps": next_steps,
    }


__all__ = [
    "ConditionCandidate",
    "RULES",
    "SUPPORT_LEVELS",
    "evaluate_conditions",
]
