"""
test_leaf_analysis.py
=====================
Discrimination test for the universal leaf analyser.

The point of this test is narrow and important: prove that the analysis
**responds to image content**. It renders a set of synthetic leaves, each with
one dominant visual condition, and asserts that each produces the symptom and
condition shortlist appropriate to it - and, critically, that a clean leaf
produces nothing and a blank wall is rejected outright.

If the pipeline ever starts returning a canned answer, every expectation here
fails at once.

These are synthetic shapes, not photographs. They verify the measurement and
rule logic; they say nothing about accuracy on real leaves, which needs
field-captured ground truth.

    python scripts/test_leaf_analysis.py
    python scripts/test_leaf_analysis.py --save-images out/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ml"))

try:
    import cv2
except ImportError:  # pragma: no cover
    print("OpenCV is required: pip install -r backend/requirements.txt")
    raise SystemExit(2)

from condition_rules import evaluate_conditions  # noqa: E402
from leaf_analysis import analyse_leaf  # noqa: E402

GREEN = "\033[92m"
RED = "\033[91m"
GREY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


# --------------------------------------------------------------------------- #
# Synthetic leaf rendering
# --------------------------------------------------------------------------- #

def render(kind: str, seed: int = 0, size: int = 440) -> np.ndarray:
    """Render a leaf exhibiting one dominant condition."""
    rng = np.random.default_rng(seed)
    grid_y, grid_x = np.mgrid[0:size, 0:size]

    image = np.full((size, size, 3), 28.0, np.float32)          # dark background
    leaf = ((grid_x - size / 2) ** 2 / (size * 0.36) ** 2
            + (grid_y - size / 2) ** 2 / (size * 0.27) ** 2) < 1.0
    image[leaf] = [58, 142, 52]                                  # healthy tissue

    for offset in range(-size // 2, size // 2, 18):              # veins
        vein = np.abs((grid_y - size / 2) - 0.5 * (grid_x - size / 2) - offset) < 1.5
        image[vein & leaf] = [92, 172, 78]

    def blobs(count: int, radius: Tuple[int, int], colour: Sequence[float], inset: int = 70) -> None:
        for _ in range(count):
            cx = rng.integers(inset, size - inset)
            cy = rng.integers(inset + 10, size - inset - 10)
            r = rng.integers(*radius)
            image[(((grid_x - cx) ** 2 + (grid_y - cy) ** 2) < r * r) & leaf] = colour

    if kind == "healthy":
        pass
    elif kind == "leaf_spots":
        blobs(14, (7, 12), [78, 52, 28])
    elif kind == "large_blight":
        for _ in range(2):
            cx = rng.integers(120, size - 120)
            cy = rng.integers(120, size - 120)
            patch = ((grid_x - cx) ** 2 / 5200 + (grid_y - cy) ** 2 / 3600) < 1.0
            image[patch & leaf] = [70, 54, 34]
    elif kind == "yellowing":
        image[leaf] = [178, 182, 52]
        for offset in range(-size // 2, size // 2, 18):
            vein = np.abs((grid_y - size / 2) - 0.5 * (grid_x - size / 2) - offset) < 1.5
            image[vein & leaf] = [60, 140, 50]
    elif kind == "powdery":
        blobs(9, (18, 30), [232, 234, 230])
    elif kind == "edge_scorch":
        leaf_u8 = leaf.astype(np.uint8)
        eroded = cv2.erode(leaf_u8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
        image[leaf & ~eroded.astype(bool)] = [84, 58, 30]
    elif kind == "holes":
        # Background colour punched through the leaf: a real gap.
        blobs(7, (11, 18), [28, 28, 28], inset=90)
    elif kind == "rust":
        blobs(30, (4, 7), [204, 102, 32], inset=60)
    elif kind == "blank_wall":
        image[:] = 215.0
    else:
        raise ValueError(f"unknown kind: {kind}")

    image += rng.normal(0, 7, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Expectations
# --------------------------------------------------------------------------- #
# expect_symptoms  these symptom ids must be reported
# forbid_symptoms  these must NOT be reported
# expect_top       the top-ranked candidate must be one of these
# assessment       required assessment value

CASES: Sequence[Dict[str, object]] = (
    {
        "kind": "healthy",
        "assessment": "healthy",
        "expect_symptoms": set(),
        "forbid_symptoms": {"brown_necrosis", "dark_spots", "yellowing", "powdery_coating",
                            "rust_coloured_pustules", "holes_and_damage", "margin_necrosis"},
        "expect_top": {"healthy"},
        "expect_healthy_flag": True,
    },
    {
        "kind": "leaf_spots",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"brown_necrosis"},
        "forbid_symptoms": {"rust_coloured_pustules", "powdery_coating", "holes_and_damage"},
        "expect_top": {"leaf_spot", "early_blight", "anthracnose", "bacterial_leaf_spot"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "large_blight",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"brown_necrosis"},
        "forbid_symptoms": {"rust_coloured_pustules", "powdery_coating"},
        "expect_top": {"late_blight", "early_blight", "anthracnose", "leaf_spot"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "yellowing",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"yellowing"},
        "forbid_symptoms": {"powdery_coating", "rust_coloured_pustules", "holes_and_damage"},
        "expect_top": {"nutrient_deficiency", "downy_mildew", "senescence"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "powdery",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"powdery_coating"},
        "forbid_symptoms": {"rust_coloured_pustules", "holes_and_damage"},
        "expect_top": {"powdery_mildew"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "edge_scorch",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"margin_necrosis"},
        "forbid_symptoms": {"powdery_coating", "rust_coloured_pustules", "holes_and_damage"},
        "expect_top": {"leaf_scorch"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "holes",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"holes_and_damage"},
        "forbid_symptoms": {"powdery_coating", "rust_coloured_pustules"},
        "expect_top": {"pest_damage"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "rust",
        "assessment": "symptoms_observed",
        "expect_symptoms": {"rust_coloured_pustules"},
        "forbid_symptoms": {"powdery_coating", "holes_and_damage"},
        "expect_top": {"rust"},
        "expect_healthy_flag": False,
    },
    {
        "kind": "blank_wall",
        "assessment": "insufficient_evidence",
        "expect_symptoms": set(),
        "forbid_symptoms": set(),
        "expect_top": set(),
        "expect_leaf_detected": False,
    },
)


def run(save_dir: Optional[Path] = None) -> int:
    passed = 0
    failed = 0
    failures: List[str] = []
    fingerprints: Dict[str, Tuple] = {}

    print(f"{BOLD}Universal leaf analysis - discrimination test{RESET}")
    print(f"{GREY}Synthetic images; verifies measurement and rule logic, not field accuracy.{RESET}\n")

    for index, case in enumerate(CASES):
        kind = str(case["kind"])
        image = render(kind, seed=200 + index)

        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(save_dir / f"{kind}.png"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

        analysis = analyse_leaf(image).to_dict()
        conditions = evaluate_conditions(analysis)

        reported: Set[str] = {str(item["id"]) for item in analysis["symptoms"]}
        top = conditions["candidates"][0]["id"] if conditions["candidates"] else None

        problems: List[str] = []

        if analysis["analysed"] and "expect_leaf_detected" in case:
            if analysis["leaf_detected"] != case["expect_leaf_detected"]:
                problems.append(
                    f"leaf_detected={analysis['leaf_detected']}, expected {case['expect_leaf_detected']}"
                )

        if conditions["assessment"] != case["assessment"]:
            problems.append(
                f"assessment={conditions['assessment']}, expected {case['assessment']}"
            )

        missing = set(case["expect_symptoms"]) - reported  # type: ignore[arg-type]
        if missing:
            problems.append(f"missing symptoms: {sorted(missing)}")

        wrongly = set(case["forbid_symptoms"]) & reported  # type: ignore[arg-type]
        if wrongly:
            problems.append(f"falsely reported: {sorted(wrongly)}")

        expect_top: Set[str] = set(case["expect_top"])  # type: ignore[arg-type]
        if expect_top and top not in expect_top:
            problems.append(f"top candidate={top}, expected one of {sorted(expect_top)}")

        if "expect_healthy_flag" in case:
            if analysis["appears_healthy"] != case["expect_healthy_flag"]:
                problems.append(
                    f"appears_healthy={analysis['appears_healthy']}, "
                    f"expected {case['expect_healthy_flag']}"
                )

        # Record a fingerprint so identical output across cases is detectable.
        fingerprints[kind] = (
            tuple(sorted(reported)),
            top,
            round(float(analysis["damage_fraction"]), 3),
        )

        status = f"{GREEN}PASS{RESET}" if not problems else f"{RED}FAIL{RESET}"
        symptom_text = ", ".join(sorted(reported)) or "none"
        print(f"  {status}  {kind:13s} {GREY}symptoms: {symptom_text}{RESET}")
        print(f"        {GREY}top candidate: {top or '-'}  "
              f"assessment: {conditions['assessment']}  "
              f"damage: {analysis['damage_fraction']:.3f}{RESET}")

        if problems:
            failed += 1
            for problem in problems:
                print(f"        {RED}{problem}{RESET}")
                failures.append(f"{kind}: {problem}")
        else:
            passed += 1

    # ---- the anti-hardcoding check -------------------------------------
    print(f"\n{BOLD}Distinctness{RESET}")
    unique = len(set(fingerprints.values()))
    total = len(fingerprints)
    if unique == total:
        print(f"  {GREEN}PASS{RESET}  all {total} cases produced a distinct result "
              f"{GREY}(no canned response){RESET}")
        passed += 1
    else:
        print(f"  {RED}FAIL{RESET}  only {unique} distinct results across {total} cases - "
              "the analysis may not be reading the image")
        failed += 1
        failures.append(f"distinctness: {unique}/{total} unique")

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"{BOLD}Summary:{RESET} {GREEN}{passed} passed{RESET}, "
          f"{RED if failed else GREY}{failed} failed{RESET}")
    if failures:
        print(f"\n{RED}Failures:{RESET}")
        for failure in failures:
            print(f"  - {failure}")
        print(f"{BOLD}{'=' * 62}{RESET}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(f"{BOLD}{'=' * 62}{RESET}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-images", type=Path, default=None,
                        help="Write the rendered test images to this directory")
    args = parser.parse_args(argv)
    return run(args.save_images)


if __name__ == "__main__":
    raise SystemExit(main())
