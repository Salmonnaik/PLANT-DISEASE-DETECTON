"""
create_test_model.py
====================
Creates an **untrained** MobileNetV2 classifier so the full pipeline
(ESP32-CAM -> Flask -> model -> dashboard) can be wired up and tested before
the PlantVillage dataset has been downloaded and trained on.

This exists only because a web API cannot be integration-tested without *some*
loadable model. It is deliberately and visibly marked as not real:

* ``saved_model/metadata.json`` is written with ``trained: false`` and
  ``test_mode: true``.
* ``PlantDiseasePredictor`` reports ``mode = "test"`` and sets
  ``is_validated_prediction = false`` on every response.
* ``/api/health`` returns ``model.is_test_mode = true``.
* The dashboard renders a permanent amber "TEST MODE" banner.

Because the classification head is randomly initialised, its outputs hover
around ``1 / num_classes``, which falls below the confidence threshold and is
therefore reported as "Uncertain" rather than as a disease.

Usage::

    python create_test_model.py
    python create_test_model.py --force          # overwrite an existing model
    python create_test_model.py --classes-from ./dataset

Replace it at any time by running the real training job::

    python train.py --dataset-dir dataset
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from label_utils import build_label_catalogue  # noqa: E402
from model_builder import BASE_MODEL_NAME, build_model, count_parameters  # noqa: E402
from preprocessing import discover_classes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("create_test_model")

ML_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = ML_DIR / "saved_model"
DEFAULT_LABELS_PATH = ML_DIR / "class_labels.json"
MODEL_FILENAME = "plant_disease_model.keras"

# The nine categories listed in the project specification, written with the
# PlantVillage folder-name convention so a later real training run on those
# classes produces identical labels.
SPEC_CLASSES: List[str] = [
    "Pepper,_bell___Bacterial_spot",
    "Pepper,_bell___healthy",
    "Potato___Early_blight",
    "Potato___Late_blight",
    "Potato___healthy",
    "Tomato___Early_blight",
    "Tomato___Late_blight",
    "Tomato___Leaf_Mold",
    "Tomato___Septoria_leaf_spot",
    "Tomato___healthy",
]


def resolve_classes(classes_from: Optional[Path]) -> tuple[List[str], str]:
    """Prefer the real dataset's class folders when they exist."""
    if classes_from:
        found = discover_classes(classes_from)
        if found:
            logger.info("Using %d class folders discovered in %s", len(found), classes_from)
            return found, f"dataset directory {classes_from}"
        logger.warning("No class folders found in %s; falling back to the spec class list.", classes_from)
    return sorted(SPEC_CLASSES), "project specification default class list"


def existing_model_is_trained(model_dir: Path) -> bool:
    metadata_path = model_dir / "metadata.json"
    if not metadata_path.is_file():
        return False
    try:
        return bool(json.loads(metadata_path.read_text(encoding="utf-8")).get("trained", False))
    except json.JSONDecodeError:
        return False


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an explicitly-labelled UNTRAINED model for integration testing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument(
        "--classes-from",
        type=Path,
        default=ML_DIR / "dataset",
        help="Read the class list from this dataset directory when it has class folders",
    )
    parser.add_argument(
        "--no-imagenet",
        action="store_true",
        help="Skip the ImageNet weight download (fully random weights)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even if a genuinely trained model is already present",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if existing_model_is_trained(args.model_dir) and not args.force:
        logger.error(
            "A TRAINED model already exists in %s. Refusing to replace it with an "
            "untrained test model. Pass --force if that is really what you want.",
            args.model_dir,
        )
        return 3

    try:
        import tensorflow as tf  # noqa: PLC0415
    except ImportError:
        logger.error("TensorFlow is not installed. Run: pip install -r ../backend/requirements.txt")
        return 2

    class_names, source = resolve_classes(args.classes_from)
    logger.info("Building an untrained %s head for %d classes.", BASE_MODEL_NAME, len(class_names))

    model = build_model(
        num_classes=len(class_names),
        image_size=(args.image_size, args.image_size),
        weights=None if args.no_imagenet else "imagenet",
    )
    # Intentionally not compiled: this model is only ever used for inference,
    # and saving an un-built optimizer makes Keras warn on every reload.

    args.model_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.model_dir / MODEL_FILENAME
    model.save(model_path)

    catalogue = build_label_catalogue(class_names)
    args.labels_path.parent.mkdir(parents=True, exist_ok=True)
    args.labels_path.write_text(json.dumps(catalogue, indent=2), encoding="utf-8")

    metadata = {
        "model_name": "plant_disease_mobilenetv2",
        "model_file": MODEL_FILENAME,
        "base_model": BASE_MODEL_NAME,
        "trained": False,
        "test_mode": True,
        "warning": (
            "UNTRAINED MODEL. The classification head is randomly initialised and has "
            "never seen a plant disease dataset. Its outputs are NOT valid diagnoses and "
            "exist only so the end-to-end pipeline can be integration tested. Replace it "
            "by running: python ml/train.py --dataset-dir ml/dataset"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tensorflow_version": tf.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "num_classes": len(class_names),
        "class_names": class_names,
        "class_source": source,
        "image_size": [args.image_size, args.image_size],
        "preprocessing": {
            "scaling": "in_model",
            "note": "Rescaling(1/127.5, offset=-1) is a layer inside the saved model.",
            "resize": "bilinear",
        },
        "training": {
            "imagenet_weights": not args.no_imagenet,
            "epochs_stage1": 0,
            "epochs_stage2": 0,
        },
        "parameters": count_parameters(model),
        "metrics": {},
        "suggested_confidence_threshold": 0.70,
    }
    (args.model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print()
    logger.info("Untrained test model written to : %s", model_path)
    logger.info("Class labels written to         : %s", args.labels_path)
    logger.info("Metadata written to             : %s", args.model_dir / "metadata.json")
    print()
    logger.warning("=" * 74)
    logger.warning("TEST MODE MODEL CREATED - predictions from it are NOT real diagnoses.")
    logger.warning("Train the real model with:  python train.py --dataset-dir dataset")
    logger.warning("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
