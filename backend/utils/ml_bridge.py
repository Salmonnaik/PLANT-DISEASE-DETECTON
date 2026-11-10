"""
utils/ml_bridge.py
==================
The one place that makes the ``ml/`` package importable from the backend.

``ml/`` is a sibling of ``backend/`` rather than a sub-package, because the
training scripts must stay runnable on their own (``cd ml && python train.py``)
and must not depend on Flask. This module inserts ``ml/`` onto ``sys.path`` once
and re-exports what the backend needs, so no other backend file has to perform
path surgery.

TensorFlow is imported lazily by ``predict.py``, so importing this module is
cheap; only ``PlantDiseasePredictor.load()`` pulls TensorFlow into memory.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
ML_DIR = PROJECT_ROOT / "ml"

if not ML_DIR.is_dir():  # pragma: no cover
    raise ImportError(
        f"The ml/ directory was not found at {ML_DIR}. The backend expects the "
        "project layout plant-disease-detection/{backend,ml,frontend}."
    )

if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

# --- re-exports ------------------------------------------------------------
from disease_info import all_known_classes, get_disease_info, severity_rank  # noqa: E402
from label_utils import parse_label, parse_labels  # noqa: E402
from predict import (  # noqa: E402
    DEFAULT_CONFIDENCE_THRESHOLD,
    STATUS_DISEASED,
    STATUS_HEALTHY,
    STATUS_UNCERTAIN,
    STATUS_UNKNOWN,
    ModelNotLoadedError,
    PlantDiseasePredictor,
)
from preprocessing import (  # noqa: E402
    DEFAULT_QUALITY_THRESHOLDS,
    IMAGE_SIZE,
    ImageDecodeError,
    assess_image_quality,
    decode_image_bytes,
)

# Universal (species-agnostic) analysis layer. Independent of the trained
# classifier, so it works for any plant.
from condition_rules import evaluate_conditions  # noqa: E402
from leaf_analysis import LeafAnalysis, analyse_leaf  # noqa: E402
from plant_knowledge import (  # noqa: E402
    all_conditions,
    all_treatments,
    cause_categories,
    condition_ids,
    get_condition_info,
    get_species_info,
    get_treatment,
    get_uncertain_guidance,
    list_species,
    resolve_species_key,
    severity_scale,
)


def read_training_reports(reports_dir: Path) -> Dict[str, Any]:
    """
    Load the evaluation artefacts written by ``ml/evaluate.py``.

    Returns ``{"available": False, ...}`` when the model has not been evaluated
    yet, which is what the Analytics page renders as "train a model to see
    evaluation metrics" rather than as an error.
    """
    import json  # noqa: PLC0415

    directory = Path(reports_dir)
    metrics_path = directory / "metrics.json"

    if not metrics_path.is_file():
        return {
            "available": False,
            "reason": (
                "No evaluation report found. Run `python ml/train.py --dataset-dir ml/dataset` "
                "or `python ml/evaluate.py` to generate model metrics."
            ),
            "reports_dir": str(directory),
        }

    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "reason": f"metrics.json could not be parsed: {exc}",
            "reports_dir": str(directory),
        }

    history: Dict[str, List[float]] = {}
    history_path = directory / "training_history.json"
    if history_path.is_file():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = {}

    artefacts = {
        name: (directory / filename).is_file()
        for name, filename in {
            "confusion_matrix_png": "confusion_matrix.png",
            "confusion_matrix_csv": "confusion_matrix.csv",
            "training_curves_png": "training_curves.png",
            "classification_report": "classification_report.json",
            "model_summary": "model_summary.txt",
        }.items()
    }

    return {
        "available": True,
        "reports_dir": str(directory),
        "metrics": metrics,
        "training_history": history,
        "artefacts": artefacts,
    }


__all__ = [
    "ML_DIR",
    "PROJECT_ROOT",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_QUALITY_THRESHOLDS",
    "IMAGE_SIZE",
    "STATUS_HEALTHY",
    "STATUS_DISEASED",
    "STATUS_UNCERTAIN",
    "STATUS_UNKNOWN",
    "PlantDiseasePredictor",
    "ModelNotLoadedError",
    "ImageDecodeError",
    "decode_image_bytes",
    "assess_image_quality",
    "parse_label",
    "parse_labels",
    "get_disease_info",
    "all_known_classes",
    "severity_rank",
    "read_training_reports",
    # Universal analysis layer
    "LeafAnalysis",
    "analyse_leaf",
    "evaluate_conditions",
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
]
