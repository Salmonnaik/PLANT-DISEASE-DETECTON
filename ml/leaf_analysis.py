"""
leaf_analysis.py
================
Universal leaf symptom analysis by classical computer vision.

Purpose
-------
The trained MobileNetV2 classifier can only output one of the classes it was
trained on. This module is species-agnostic: it *measures* what is visible on
any leaf - colour distribution, lesion blobs, margin necrosis, powdery
coating, holes, mottling, shape distortion - and reports those measurements.

The critical distinction this module exists to preserve:

    OBSERVATION  "4.2% of the leaf area is brown necrotic tissue, in 7 discrete
                  roundish blobs averaging 0.6% of leaf area each"   <- measured
    DIAGNOSIS    "this is Septoria leaf spot"                        <- inferred

This file only ever produces the first kind of statement. Mapping symptoms to
possible conditions happens in ``condition_rules.py``, and that layer is
explicit that its output is a list of possibilities consistent with the
evidence, not a diagnosis.

Nothing here is a neural network and nothing here is random: the same image
always produces the same numbers, and every reported symptom carries the
measurement that triggered it.

Honest limitations
------------------
* It cannot identify the plant species. Colour and blob geometry do not encode
  species. Species identification requires either the user telling us, or a
  vision model (see ``backend/services/vision_service.py``).
* It measures appearance, not cause. Brown margin necrosis looks the same
  whether it came from drought, salt burn, or a fungal pathogen.
* Thresholds are tuned for a reasonably lit photograph of a single leaf against
  a contrasting background. A cluttered background degrades segmentation, which
  is why ``leaf_coverage`` and ``segmentation_quality`` are reported so callers
  can discount a poor measurement.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore
    _HAS_CV2 = False


# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #

# Working resolution. Large enough to resolve small lesions, small enough that
# the whole analysis stays well under a second on a CPU.
ANALYSIS_MAX_SIDE = 512

# HSV ranges, in OpenCV's scale: H 0-179, S 0-255, V 0-255.
# Chosen to be deliberately conservative - a pixel that is ambiguous is left
# unclassified rather than counted toward a symptom.
HSV_RANGES: Dict[str, Dict[str, Tuple[int, int]]] = {
    # Healthy chlorophyll-rich tissue.
    "healthy_green": {"h": (33, 88), "s": (55, 255), "v": (35, 255)},
    # Chlorosis: yellowing from nutrient loss, virus, or early senescence.
    "chlorotic_yellow": {"h": (20, 33), "s": (70, 255), "v": (90, 255)},
    # Necrosis: dead brown tissue. Brown and rust-orange share almost the same
    # hue, so brightness is what separates them - dead tissue is dark.
    "necrotic_brown": {"h": (5, 25), "s": (45, 255), "v": (28, 150)},
    # Rust pustules: the same hue family as brown but bright and highly
    # saturated. Without the value floor every brown lesion also reads as rust.
    "rust_orange": {"h": (3, 20), "s": (110, 255), "v": (150, 255)},
}

# Very dark pixels inside the leaf: black spots / sunken anthracnose lesions.
DARK_V_MAX = 58
# Desaturated bright pixels inside the leaf: powdery mildew coating.
POWDERY_S_MAX = 48
POWDERY_V_MIN = 172

# Symptom reporting thresholds, as a fraction of leaf area.
# Below "mild" the finding is not reported at all - every leaf has a few stray
# pixels, and reporting those as symptoms would make the output noise.
SEVERITY_BANDS: Dict[str, Tuple[float, float, float]] = {
    #                        mild,  moderate, severe
    "necrotic_brown":       (0.015, 0.060, 0.180),
    "chlorotic_yellow":     (0.040, 0.130, 0.320),
    "dark_spots":           (0.004, 0.020, 0.070),
    "powdery_white":        (0.012, 0.050, 0.150),
    "rust_pustules":        (0.004, 0.020, 0.070),
    "margin_necrosis":      (0.060, 0.170, 0.380),
    "holes":                (0.004, 0.020, 0.060),
}

SEVERITY_ORDER = ("none", "mild", "moderate", "severe")


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #

@dataclass
class Symptom:
    """One measured, named observation."""

    id: str
    label: str
    severity: str                 # mild | moderate | severe
    # The measurement that triggered this symptom, in words the user can check
    # against the image.
    evidence: str
    metric: float                 # the raw fraction or count behind `evidence`
    category: str                 # colour | lesion | structure | surface

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LeafAnalysis:
    """Everything measured from one image."""

    analysed: bool
    reason: Optional[str] = None

    leaf_detected: bool = False
    leaf_coverage: float = 0.0            # leaf pixels / image pixels
    segmentation_quality: str = "unknown"  # good | fair | poor
    appears_healthy: bool = False
    overall_evidence: str = "insufficient"  # strong | moderate | weak | insufficient
    damage_fraction: float = 0.0           # non-healthy tissue / leaf area

    symptoms: List[Symptom] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysed": self.analysed,
            "reason": self.reason,
            "leaf_detected": self.leaf_detected,
            "leaf_coverage": round(self.leaf_coverage, 4),
            "segmentation_quality": self.segmentation_quality,
            "appears_healthy": self.appears_healthy,
            "overall_evidence": self.overall_evidence,
            "damage_fraction": round(self.damage_fraction, 4),
            "symptoms": [symptom.to_dict() for symptom in self.symptoms],
            "symptom_ids": [symptom.id for symptom in self.symptoms],
            "metrics": self.metrics,
            "notes": self.notes,
            "method": "classical computer vision (OpenCV) - measurements only, not a diagnosis",
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _severity_for(key: str, value: float) -> str:
    """Map a measured fraction onto none/mild/moderate/severe."""
    mild, moderate, severe = SEVERITY_BANDS[key]
    if value >= severe:
        return "severe"
    if value >= moderate:
        return "moderate"
    if value >= mild:
        return "mild"
    return "none"


def _downscale(image: np.ndarray, max_side: int = ANALYSIS_MAX_SIDE) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    if _HAS_CV2:
        return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
    # Nearest-neighbour fallback keeps the module importable without OpenCV.
    row_index = (np.linspace(0, height - 1, new_size[1])).astype(int)
    column_index = (np.linspace(0, width - 1, new_size[0])).astype(int)
    return image[row_index][:, column_index]


def _in_hsv_range(hsv: np.ndarray, spec: Dict[str, Tuple[int, int]]) -> np.ndarray:
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (
        (hue >= spec["h"][0])
        & (hue <= spec["h"][1])
        & (saturation >= spec["s"][0])
        & (saturation <= spec["s"][1])
        & (value >= spec["v"][0])
        & (value <= spec["v"][1])
    )


def _tissue_mask(image: np.ndarray) -> np.ndarray:
    """
    Strict per-pixel test for plant tissue.

    Two conditions must both hold:

    * **Chroma.** The pixel must be noticeably coloured. A grey desk, a white
      sheet of paper and deep shadow all have near-zero chroma, which is what
      lets this reject them regardless of brightness. This is the test that
      does the real work.
    * **Hue direction.** Green, yellow-green, brown-orange and red all place
      red and/or green clearly above blue. Nothing plant-coloured is
      blue-dominant, so sky and blue fabric are excluded.

    Deliberately conservative. Pale powdery coating and black lesions fail this
    test and are recovered later as regions *enclosed* by tissue, which is a far
    more reliable way to include them than loosening the colour test would be.
    """
    rgb = image.astype(np.int16)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    brightest = rgb.max(axis=2)
    chroma = brightest - rgb.min(axis=2)

    green_dominant = (green - blue) >= 12
    warm_dominant = ((red - blue) >= 20) & ((green - blue) >= 5)
    red_dominant = ((red - green) >= 20) & ((red - blue) >= 25)

    tissue = (chroma >= 20) & (green_dominant | warm_dominant | red_dominant)
    # Exclude blown highlights and near-black pixels, where hue is meaningless.
    tissue &= (brightest > 26) & (brightest < 251)
    return tissue


def _segment_leaf(image: np.ndarray) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """
    Separate leaf from background.

    Returns ``(masks, info)`` where ``masks`` contains:

    ``core``     pixels that passed the strict tissue test
    ``extent``   the leaf outline, i.e. core plus everything enclosed by it
    ``holes``    enclosed regions whose colour matches the background - real
                 gaps in the leaf (insect feeding, shot-hole, tears)
    ``surface``  enclosed regions that do *not* match the background - powdery
                 coating, black lesions, bleached patches

    All colour fractions are measured against ``extent``, so a leaf that is 30%
    covered in white mildew still reports sensible percentages. Separating
    ``holes`` from ``surface`` by comparison against the measured background
    colour is what stops a hole showing a dark desk from being counted as a
    black lesion.
    """
    info: Dict[str, Any] = {}
    tissue = _tissue_mask(image)

    if not _HAS_CV2:
        info["method"] = "numpy threshold (OpenCV unavailable)"
        empty = np.zeros_like(tissue)
        return {"core": tissue, "extent": tissue, "holes": empty, "surface": empty}, info

    mask = tissue.astype(np.uint8) * 255

    # OPEN before CLOSE. This order matters: sensor noise on a flat background
    # puts a few percent of isolated pixels through the colour test, and closing
    # first would bridge them into one solid mass that swallows the whole frame.
    # Opening removes them while leaving any real region intact.
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel, iterations=1)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    empty = np.zeros(tissue.shape, dtype=bool)

    if count <= 1:
        info["method"] = "no tissue region found"
        info["component_count"] = 0
        info["largest_component_share"] = 0.0
        return {"core": empty, "extent": empty, "holes": empty, "surface": empty}, info

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_index = int(np.argmax(areas)) + 1
    core = labels == largest_index

    total_tissue = int(np.count_nonzero(mask))
    info["method"] = "largest connected tissue component"
    info["component_count"] = int(count - 1)
    # Share of all detected tissue belonging to the chosen component. Low means
    # several leaves or a leafy background, so the measurement covers only one.
    info["largest_component_share"] = (
        round(int(areas.max()) / total_tissue, 4) if total_tissue else 0.0
    )

    # ---- leaf outline: fill everything enclosed by the core ------------
    core_u8 = core.astype(np.uint8) * 255
    flood = core_u8.copy()
    flood_mask = np.zeros((flood.shape[0] + 2, flood.shape[1] + 2), np.uint8)
    # Seed from a corner. If the leaf touches that corner the fill does nothing
    # useful, so pad the image by one pixel first to guarantee a background seed.
    padded = cv2.copyMakeBorder(flood, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    pad_mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, pad_mask, (0, 0), 255)
    exterior = padded[1:-1, 1:-1] == 255
    enclosed = (~core) & (~exterior)
    extent = core | enclosed

    # ---- tell holes from surface anomalies -----------------------------
    holes = empty.copy()
    surface = enclosed.copy()

    if enclosed.any():
        # Estimate background colour from exterior pixels near the leaf, which
        # is what would show through a hole.
        dilated = cv2.dilate(
            extent.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)),
            iterations=1,
        ).astype(bool)
        ring = dilated & ~extent
        reference = ring if np.count_nonzero(ring) > 50 else exterior

        if np.count_nonzero(reference) > 20:
            background_rgb = np.median(image[reference].astype(np.float32), axis=0)
            distance = np.linalg.norm(
                image.astype(np.float32) - background_rgb[None, None, :], axis=2
            )
            # Within this RGB distance of the background, an enclosed region is
            # a genuine gap rather than something on the leaf surface.
            holes = enclosed & (distance < 48)
            surface = enclosed & ~holes
            info["background_rgb"] = [int(value) for value in background_rgb]

    return {"core": core, "extent": extent, "holes": holes, "surface": surface}, info


def _lesion_blob_stats(lesion_mask: np.ndarray, leaf_area: int) -> Dict[str, Any]:
    """
    Describe discrete lesions.

    Blob geometry is what separates "many small round spots" (consistent with
    leaf spot or rust) from "a few large irregular patches" (consistent with
    blight). That distinction is the most diagnostically useful thing classical
    CV can offer here, so it is measured explicitly.
    """
    empty = {
        "count": 0,
        "mean_area_fraction": 0.0,
        "largest_area_fraction": 0.0,
        "mean_circularity": 0.0,
        "pattern": "none",
    }
    if not _HAS_CV2 or leaf_area <= 0:
        return empty

    mask = lesion_mask.astype(np.uint8) * 255
    # Remove single-pixel noise before counting blobs.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # Ignore blobs below 0.02% of leaf area: dust, sensor noise, vein shadow.
    min_area = max(6.0, leaf_area * 0.0002)

    areas: List[float] = []
    circularities: List[float] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        areas.append(area)
        if perimeter > 0:
            circularities.append(min(1.0, 4.0 * np.pi * area / (perimeter**2)))

    if not areas:
        return empty

    mean_fraction = float(np.mean(areas)) / leaf_area
    largest_fraction = float(np.max(areas)) / leaf_area
    mean_circularity = float(np.mean(circularities)) if circularities else 0.0

    # Qualitative pattern label, used by the rule layer.
    if len(areas) >= 5 and mean_fraction < 0.012 and mean_circularity >= 0.45:
        pattern = "many_small_round_spots"
    elif len(areas) >= 5 and mean_fraction < 0.012:
        pattern = "many_small_irregular_spots"
    elif largest_fraction >= 0.08:
        pattern = "large_irregular_patches"
    elif len(areas) <= 4 and mean_circularity >= 0.45:
        pattern = "few_round_lesions"
    else:
        pattern = "scattered_lesions"

    return {
        "count": len(areas),
        "mean_area_fraction": round(mean_fraction, 5),
        "largest_area_fraction": round(largest_fraction, 5),
        "mean_circularity": round(mean_circularity, 3),
        "pattern": pattern,
    }


def _inset_mask(mask: np.ndarray) -> np.ndarray:
    """
    Erode a mask inward by a few pixels to exclude its boundary band.

    The inset scales with leaf size so it removes the same proportion of a
    small and a large leaf, and never erodes so far that the region collapses.
    """
    if not _HAS_CV2 or not mask.any():
        return mask

    area = int(np.count_nonzero(mask))
    radius = int(np.clip(round(0.008 * np.sqrt(area)), 2, 6))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    eroded = cv2.erode(mask.astype(np.uint8), kernel, iterations=1).astype(bool)

    # If erosion removed almost everything the leaf is very thin; keep the
    # original rather than ending up with nothing to measure.
    if np.count_nonzero(eroded) < 0.35 * area:
        return mask
    return eroded


def _margin_interior_split(leaf_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Split the leaf into a margin band and an interior region.

    Necrosis concentrated at the edge points to scorch, salt or drought stress;
    the same amount scattered through the interior points to a spotting
    pathogen. Without this split the two are indistinguishable.
    """
    if not _HAS_CV2:
        return leaf_mask, leaf_mask

    mask = leaf_mask.astype(np.uint8)
    # Band width scales with leaf size so it means the same thing on a small
    # and a large leaf.
    area = int(mask.sum())
    radius = max(3, int(round(0.035 * np.sqrt(max(area, 1)))))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    interior = cv2.erode(mask, kernel, iterations=1).astype(bool)
    margin = leaf_mask & ~interior
    return margin, interior


def _shape_stats(leaf_mask: np.ndarray) -> Dict[str, Any]:
    """Solidity and compactness, as proxies for curling and margin loss."""
    result = {"solidity": 1.0, "compactness": 1.0}
    if not _HAS_CV2:
        return result

    mask = leaf_mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return result

    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area <= 0:
        return result

    hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
    perimeter = float(cv2.arcLength(contour, True))

    result["solidity"] = round(area / hull_area, 3) if hull_area > 0 else 1.0
    # 1.0 for a perfect circle, lower for a ragged or lobed outline.
    result["compactness"] = (
        round(min(1.0, 4.0 * np.pi * area / (perimeter**2)), 3) if perimeter > 0 else 1.0
    )
    return result


def _mottling_score(image: np.ndarray, leaf_mask: np.ndarray) -> float:
    """
    Patchiness of green tone across the leaf.

    Mosaic virus symptoms appear as alternating light and dark green areas at a
    coarser scale than the vein pattern. Comparing a heavily blurred green
    channel against its own mean inside the leaf picks up that large-scale
    variation while ignoring fine vein texture.
    """
    if not _HAS_CV2 or not leaf_mask.any():
        return 0.0

    green = image[..., 1].astype(np.float32)
    blurred = cv2.GaussianBlur(green, (0, 0), sigmaX=9)
    values = blurred[leaf_mask]
    if values.size < 50:
        return 0.0

    mean = float(values.mean())
    if mean <= 1e-6:
        return 0.0
    # Coefficient of variation of the low-frequency green signal.
    return float(np.clip(values.std() / mean, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def analyse_leaf(image: np.ndarray) -> LeafAnalysis:
    """
    Measure visible symptoms on any leaf image.

    Species-agnostic and deterministic. Returns a :class:`LeafAnalysis` whose
    ``symptoms`` list contains only findings that exceeded their reporting
    threshold, each carrying the measurement behind it.
    """
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        return LeafAnalysis(analysed=False, reason="Input is not a 3-channel colour image.")

    working = _downscale(image)
    total_pixels = int(working.shape[0] * working.shape[1])

    masks, segmentation_info = _segment_leaf(working)
    extent_mask = masks["extent"]
    surface_mask = masks["surface"]
    coverage = int(np.count_nonzero(extent_mask)) / total_pixels if total_pixels else 0.0

    # Pull the measurement region a few pixels inside the leaf outline.
    #
    # This matters for real photographs. JPEG compression rings at the
    # high-contrast leaf/background boundary, and the leaf's own edge is a
    # gradient rather than a step, so a band of intermediate pixels hugs the
    # outline. Measured directly, those pixels read as brown or dark and every
    # single image reports "browning at the leaf edges". Eroding first removes
    # the artefact; genuine marginal scorch extends well inside this band and
    # is still detected.
    leaf_mask = _inset_mask(extent_mask)
    hole_mask = masks["holes"]
    if _HAS_CV2 and hole_mask.any():
        # Grow holes slightly for the same reason: the blur ring around a gap
        # is neither background nor leaf tissue.
        hole_mask = cv2.dilate(
            hole_mask.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            iterations=1,
        ).astype(bool)

    leaf_area = int(np.count_nonzero(leaf_mask))
    segmentation_info["inset_pixels_removed"] = int(
        np.count_nonzero(extent_mask) - leaf_area
    )

    analysis = LeafAnalysis(analysed=True)
    analysis.leaf_coverage = coverage

    # Too little tissue to measure anything meaningful.
    if leaf_area < 0.03 * total_pixels or leaf_area < 900:
        analysis.leaf_detected = False
        analysis.segmentation_quality = "poor"
        analysis.overall_evidence = "insufficient"
        analysis.reason = (
            f"No clear leaf region was found - only {coverage * 100:.1f}% of the frame "
            "looks like plant tissue. Fill more of the frame with a single leaf against "
            "a plain background."
        )
        analysis.metrics = {"leaf_coverage": round(coverage, 4), "segmentation": segmentation_info}
        return analysis

    analysis.leaf_detected = True

    # How much to trust these measurements.
    component_share = float(segmentation_info.get("largest_component_share", 1.0))
    if coverage >= 0.25 and component_share >= 0.75:
        analysis.segmentation_quality = "good"
    elif coverage >= 0.10 and component_share >= 0.5:
        analysis.segmentation_quality = "fair"
    else:
        analysis.segmentation_quality = "poor"
        analysis.notes.append(
            "The leaf outline could not be separated cleanly from the background, so "
            "these measurements are approximate. Use a plain, contrasting background."
        )
    if component_share < 0.75 and segmentation_info.get("component_count", 1) > 1:
        analysis.notes.append(
            "More than one leaf-like region is in the frame; only the largest was "
            "measured. Photograph one leaf at a time."
        )

    # ---- colour composition -------------------------------------------
    if _HAS_CV2:
        hsv = cv2.cvtColor(working, cv2.COLOR_RGB2HSV)
    else:
        analysis.notes.append(
            "OpenCV is unavailable, so colour analysis used a reduced code path."
        )
        hsv = np.zeros_like(working)

    # Holes are excluded from every colour measurement: what shows through a
    # gap is the background, and counting it as leaf tissue would turn a hole
    # over a dark desk into a "black lesion".
    surface_area = leaf_mask & ~hole_mask

    def fraction(mask: np.ndarray) -> float:
        return float(np.count_nonzero(mask & surface_area)) / leaf_area

    healthy_mask = _in_hsv_range(hsv, HSV_RANGES["healthy_green"]) & surface_area
    yellow_mask = _in_hsv_range(hsv, HSV_RANGES["chlorotic_yellow"]) & surface_area
    brown_mask = _in_hsv_range(hsv, HSV_RANGES["necrotic_brown"]) & surface_area
    rust_mask = _in_hsv_range(hsv, HSV_RANGES["rust_orange"]) & surface_area
    dark_mask = (hsv[..., 2] < DARK_V_MAX) & surface_area
    powdery_mask = (
        (hsv[..., 1] < POWDERY_S_MAX) & (hsv[..., 2] > POWDERY_V_MIN) & surface_area
    )
    # An enclosed pale patch is powdery coating even if it is slightly tinted;
    # the enclosure itself is the evidence that it sits on the leaf.
    powdery_mask |= surface_mask & (hsv[..., 1] < POWDERY_S_MAX + 20) & (hsv[..., 2] > 150)

    healthy_fraction = fraction(healthy_mask)
    yellow_fraction = fraction(yellow_mask)
    brown_fraction = fraction(brown_mask)
    rust_fraction = fraction(rust_mask)
    dark_fraction = fraction(dark_mask)
    powdery_fraction = fraction(powdery_mask)

    # ---- lesions --------------------------------------------------------
    lesion_mask = (brown_mask | dark_mask) & surface_area
    lesion_stats = _lesion_blob_stats(lesion_mask, leaf_area)

    # ---- margin vs interior --------------------------------------------
    margin_mask, interior_mask = _margin_interior_split(leaf_mask)
    margin_area = int(np.count_nonzero(margin_mask & ~hole_mask))
    interior_area = int(np.count_nonzero(interior_mask & ~hole_mask))
    margin_necrosis = (
        float(np.count_nonzero((brown_mask | dark_mask) & margin_mask)) / margin_area
        if margin_area
        else 0.0
    )
    interior_necrosis = (
        float(np.count_nonzero((brown_mask | dark_mask) & interior_mask)) / interior_area
        if interior_area
        else 0.0
    )

    # ---- holes ----------------------------------------------------------
    hole_pixels = int(np.count_nonzero(hole_mask))
    hole_fraction = hole_pixels / leaf_area if leaf_area else 0.0

    # ---- shape and mottling ---------------------------------------------
    # Shape is measured on the true outline, not the inset region.
    shape = _shape_stats(extent_mask)
    # Mottling is measured on healthy-coloured tissue only. Including lesions
    # would make any spotted leaf look mottled, and mosaic patterning is
    # specifically a variation *within* green tissue.
    mottling = _mottling_score(working, healthy_mask)

    damage_fraction = float(
        np.count_nonzero(
            (yellow_mask | brown_mask | dark_mask | powdery_mask | rust_mask | hole_mask)
        )
        / leaf_area
    )

    analysis.damage_fraction = damage_fraction
    analysis.metrics = {
        "leaf_coverage": round(coverage, 4),
        "healthy_green_fraction": round(healthy_fraction, 4),
        "chlorotic_yellow_fraction": round(yellow_fraction, 4),
        "necrotic_brown_fraction": round(brown_fraction, 4),
        "dark_spot_fraction": round(dark_fraction, 4),
        "powdery_white_fraction": round(powdery_fraction, 4),
        "rust_orange_fraction": round(rust_fraction, 4),
        "damage_fraction": round(damage_fraction, 4),
        "margin_necrosis_fraction": round(margin_necrosis, 4),
        "interior_necrosis_fraction": round(interior_necrosis, 4),
        "hole_fraction": round(hole_fraction, 4),
        "mottling_score": round(mottling, 4),
        "lesions": lesion_stats,
        "shape": shape,
        "segmentation": segmentation_info,
    }

    # ---- symptom extraction --------------------------------------------
    symptoms: List[Symptom] = []

    def add(key: str, symptom_id: str, label: str, value: float, evidence: str, category: str) -> None:
        severity = _severity_for(key, value)
        if severity != "none":
            symptoms.append(
                Symptom(
                    id=symptom_id,
                    label=label,
                    severity=severity,
                    evidence=evidence,
                    metric=round(value, 4),
                    category=category,
                )
            )

    add(
        "necrotic_brown",
        "brown_necrosis",
        "Brown dead tissue",
        brown_fraction,
        f"{brown_fraction * 100:.1f}% of the leaf area is brown necrotic tissue",
        "colour",
    )
    add(
        "chlorotic_yellow",
        "yellowing",
        "Yellowing (chlorosis)",
        yellow_fraction,
        f"{yellow_fraction * 100:.1f}% of the leaf area is yellowed rather than green",
        "colour",
    )
    add(
        "dark_spots",
        "dark_spots",
        "Dark or black spots",
        dark_fraction,
        f"{dark_fraction * 100:.1f}% of the leaf area is very dark"
        + (
            f", in {lesion_stats['count']} discrete lesions"
            if lesion_stats["count"]
            else ""
        ),
        "lesion",
    )
    add(
        "powdery_white",
        "powdery_coating",
        "White powder-like coating",
        powdery_fraction,
        f"{powdery_fraction * 100:.1f}% of the leaf surface is pale and desaturated, "
        "consistent with a powdery coating",
        "surface",
    )
    add(
        "rust_pustules",
        "rust_coloured_pustules",
        "Rust-coloured pustules",
        rust_fraction,
        f"{rust_fraction * 100:.1f}% of the leaf area is reddish-orange",
        "lesion",
    )
    add(
        "holes",
        "holes_and_damage",
        "Holes or missing tissue",
        hole_fraction,
        f"Gaps equal to {hole_fraction * 100:.1f}% of the leaf area are enclosed within "
        "the leaf outline",
        "structure",
    )

    # Margin necrosis is only meaningful relative to the interior; a uniformly
    # necrotic leaf is not "edge scorch".
    if margin_necrosis >= SEVERITY_BANDS["margin_necrosis"][0] and margin_necrosis > interior_necrosis * 1.8:
        symptoms.append(
            Symptom(
                id="margin_necrosis",
                label="Browning concentrated at the leaf edges",
                severity=_severity_for("margin_necrosis", margin_necrosis),
                evidence=(
                    f"{margin_necrosis * 100:.1f}% of the edge band is necrotic against "
                    f"{interior_necrosis * 100:.1f}% of the interior"
                ),
                metric=round(margin_necrosis, 4),
                category="structure",
            )
        )

    if mottling >= 0.17 and healthy_fraction > 0.25:
        symptoms.append(
            Symptom(
                id="mottling",
                label="Mottled light and dark green patches",
                severity="moderate" if mottling >= 0.26 else "mild",
                evidence=f"Large-scale green tone varies by {mottling * 100:.0f}% across the leaf",
                metric=round(mottling, 4),
                category="colour",
            )
        )

    if shape["solidity"] <= 0.86:
        symptoms.append(
            Symptom(
                id="distorted_outline",
                label="Curled, distorted or ragged leaf outline",
                severity="moderate" if shape["solidity"] <= 0.76 else "mild",
                evidence=(
                    f"Leaf fills only {shape['solidity'] * 100:.0f}% of its convex outline, "
                    "indicating curling, rolling or lost tissue"
                ),
                metric=shape["solidity"],
                category="structure",
            )
        )

    if lesion_stats["pattern"] != "none" and lesion_stats["count"] >= 3:
        analysis.notes.append(
            f"Lesion pattern: {lesion_stats['pattern'].replace('_', ' ')} "
            f"({lesion_stats['count']} lesions, mean size "
            f"{lesion_stats['mean_area_fraction'] * 100:.2f}% of leaf area, "
            f"roundness {lesion_stats['mean_circularity']:.2f})."
        )

    analysis.symptoms = sorted(
        symptoms,
        key=lambda item: (-SEVERITY_ORDER.index(item.severity), -item.metric),
    )

    # ---- overall judgement ---------------------------------------------
    # "Appears healthy" requires that nothing at all was reported. Calling a
    # leaf healthy while also listing a symptom would be self-contradictory,
    # and the UI would have to decide which of the two to believe.
    analysis.appears_healthy = (
        healthy_fraction >= 0.80 and damage_fraction <= 0.06 and not analysis.symptoms
    )

    severe_count = sum(1 for item in analysis.symptoms if item.severity == "severe")
    moderate_count = sum(1 for item in analysis.symptoms if item.severity == "moderate")

    if analysis.segmentation_quality == "poor":
        analysis.overall_evidence = "weak"
    elif severe_count >= 1 or moderate_count >= 2:
        analysis.overall_evidence = "strong"
    elif moderate_count == 1 or len(analysis.symptoms) >= 2:
        analysis.overall_evidence = "moderate"
    elif analysis.symptoms:
        analysis.overall_evidence = "weak"
    elif analysis.appears_healthy:
        analysis.overall_evidence = "moderate"
    else:
        analysis.overall_evidence = "insufficient"

    return analysis


__all__ = [
    "LeafAnalysis",
    "Symptom",
    "analyse_leaf",
    "SEVERITY_BANDS",
    "SEVERITY_ORDER",
]


if __name__ == "__main__":  # quick manual check: python ml/leaf_analysis.py image.jpg
    import json
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("usage: python leaf_analysis.py <image> [<image> ...]")
        raise SystemExit(1)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from preprocessing import load_image_file  # noqa: E402

    for path in sys.argv[1:]:
        report = analyse_leaf(load_image_file(path))
        print(f"\n=== {path} ===")
        print(json.dumps(report.to_dict(), indent=2))
