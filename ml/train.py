"""
train.py
========
Trains the MobileNetV2 plant-disease classifier.

Two-stage transfer learning:

    Stage 1 - freeze the ImageNet base, train only the new softmax head.
              Fast, and it stops large random gradients from destroying the
              pre-trained features.
    Stage 2 - unfreeze the top convolutional blocks and continue at a ~10x
              lower learning rate so the filters adapt to leaf textures.

Usage
-----
    python train.py                                   # dataset in ml/dataset
    python train.py --dataset-dir /data/PlantVillage
    python train.py --epochs 20 --fine-tune-epochs 10 --batch-size 32
    python train.py --max-images-per-class 300         # quick smoke run

Outputs
-------
    ml/saved_model/plant_disease_model.keras   trained model (Keras 3 format)
    ml/saved_model/metadata.json               provenance + metrics + settings
    ml/class_labels.json                       class order and parsed names
    ml/reports/*                               evaluation artefacts
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate import evaluate_model  # noqa: E402
from label_utils import build_label_catalogue  # noqa: E402
from model_builder import (  # noqa: E402
    BASE_MODEL_NAME,
    build_model,
    compile_model,
    count_parameters,
    model_summary_lines,
    unfreeze_top_layers,
)
from preprocessing import (  # noqa: E402
    DatasetValidationError,
    build_datasets,
    compute_class_weights,
    summarise_dataset_report,
    validate_dataset,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger("train")

ML_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = ML_DIR / "dataset"
DEFAULT_MODEL_DIR = ML_DIR / "saved_model"
DEFAULT_LABELS_PATH = ML_DIR / "class_labels.json"
DEFAULT_REPORT_DIR = ML_DIR / "reports"
MODEL_FILENAME = "plant_disease_model.keras"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def set_global_seed(seed: int) -> None:
    """Make the run as reproducible as TensorFlow allows."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import tensorflow as tf  # noqa: PLC0415

        tf.keras.utils.set_random_seed(seed)
    except ImportError:
        pass


def subsample_dataset(
    dataset_dir: Path,
    max_per_class: int,
    destination: Path,
) -> Path:
    """
    Build a capped copy of the dataset for quick experiments.

    Hard-links where the filesystem allows it, otherwise copies, so a 300
    images/class smoke run does not duplicate gigabytes.
    """
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    total = 0
    for class_dir in sorted(path for path in dataset_dir.iterdir() if path.is_dir()):
        images = sorted(
            item for item in class_dir.rglob("*")
            if item.is_file() and item.suffix.lower() in suffixes
        )
        selected = images[:max_per_class]
        if not selected:
            continue
        target_dir = destination / class_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for image in selected:
            target = target_dir / image.name
            try:
                target.hardlink_to(image)
            except (OSError, NotImplementedError):
                shutil.copy2(image, target)
            total += 1

    logger.info("Capped dataset built at %s (%d images, max %d/class).", destination, total, max_per_class)
    return destination


def build_callbacks(
    checkpoint_path: Path,
    log_dir: Path,
    patience: int,
    monitor: str = "val_accuracy",
):
    """Checkpoint the best epoch, stop early, and reduce the LR on plateau."""
    import tensorflow as tf  # noqa: PLC0415

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    return [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(checkpoint_path),
            monitor=monitor,
            mode="max",
            save_best_only=True,
            save_weights_only=False,
            verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor=monitor,
            mode="max",
            patience=patience,
            restore_best_weights=True,
            verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.3,
            patience=max(2, patience // 2),
            min_lr=1e-6,
            verbose=1,
        ),
        tf.keras.callbacks.CSVLogger(str(log_dir / "training_log.csv"), append=True),
    ]


def merge_histories(*histories: Dict[str, List[float]]) -> Dict[str, List[float]]:
    """Concatenate the stage-1 and stage-2 Keras history dictionaries."""
    merged: Dict[str, List[float]] = {}
    for history in histories:
        for key, values in history.items():
            merged.setdefault(key, []).extend(float(value) for value in values)
    return merged


def plot_training_curves(history: Dict[str, List[float]], output_path: Path, fine_tune_start: Optional[int]) -> Optional[Path]:
    """Accuracy and loss curves for the project report."""
    try:
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        logger.warning("matplotlib unavailable, skipping training curves (%s).", exc)
        return None

    epochs = range(1, len(history.get("loss", [])) + 1)
    if not epochs:
        return None

    figure, (left, right) = plt.subplots(1, 2, figsize=(13, 5))

    if "accuracy" in history:
        left.plot(epochs, history["accuracy"], label="train", color="#16a34a")
    if "val_accuracy" in history:
        left.plot(epochs, history["val_accuracy"], label="validation", color="#065f46", linestyle="--")
    left.set_title("Accuracy")
    left.set_xlabel("Epoch")
    left.set_ylabel("Accuracy")
    left.grid(alpha=0.25)
    left.legend()

    right.plot(epochs, history["loss"], label="train", color="#16a34a")
    if "val_loss" in history:
        right.plot(epochs, history["val_loss"], label="validation", color="#065f46", linestyle="--")
    right.set_title("Loss")
    right.set_xlabel("Epoch")
    right.set_ylabel("Categorical cross-entropy")
    right.grid(alpha=0.25)
    right.legend()

    if fine_tune_start and 0 < fine_tune_start < len(list(epochs)):
        for axis in (left, right):
            axis.axvline(fine_tune_start + 0.5, color="#b45309", linestyle=":", linewidth=1.5)
            axis.text(
                fine_tune_start + 0.6,
                axis.get_ylim()[1] * 0.95,
                "fine-tune",
                fontsize=8,
                color="#b45309",
            )

    figure.suptitle("MobileNetV2 transfer learning - training history")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)
    return output_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train the MobileNetV2 plant disease classifier.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)

    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=15, help="Stage 1 (frozen base) epochs")
    parser.add_argument("--fine-tune-epochs", type=int, default=8, help="Stage 2 epochs; 0 disables fine-tuning")
    parser.add_argument("--fine-tune-layers", type=int, default=40, help="How many top base layers to unfreeze")
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--fine-tune-learning-rate", type=float, default=1e-4)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--patience", type=int, default=5, help="EarlyStopping patience")

    parser.add_argument("--val-split", type=float, default=0.15)
    parser.add_argument("--test-split", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)

    parser.add_argument(
        "--max-images-per-class",
        type=int,
        default=0,
        help="Cap images per class for a fast trial run (0 = use everything)",
    )
    parser.add_argument("--no-class-weights", action="store_true", help="Disable inverse-frequency class weights")
    parser.add_argument("--no-imagenet", action="store_true", help="Train from random weights instead of ImageNet")
    parser.add_argument("--validate-only", action="store_true", help="Print the dataset report and exit")
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    started_at = time.time()

    # ---- 1. dataset validation -------------------------------------------
    logger.info("Validating dataset at %s", args.dataset_dir)
    try:
        report = validate_dataset(args.dataset_dir, raise_on_error=not args.validate_only)
    except DatasetValidationError as exc:
        logger.error("%s", exc)
        return 2

    print()
    print(summarise_dataset_report(report))
    print()

    if args.validate_only:
        return 0 if report["valid"] else 2

    try:
        import tensorflow as tf  # noqa: PLC0415
    except ImportError:
        logger.error("TensorFlow is not installed. Run: pip install -r ../backend/requirements.txt")
        return 2

    set_global_seed(args.seed)
    logger.info("TensorFlow %s on %s", tf.__version__, platform.platform())
    gpus = tf.config.list_physical_devices("GPU")
    logger.info("GPUs detected: %s", [gpu.name for gpu in gpus] if gpus else "none (training on CPU)")

    # ---- 2. optional capped copy for quick runs ---------------------------
    dataset_dir = args.dataset_dir
    if args.max_images_per_class and args.max_images_per_class > 0:
        dataset_dir = subsample_dataset(
            args.dataset_dir,
            args.max_images_per_class,
            ML_DIR / ".dataset_subset",
        )

    # ---- 3. data pipelines ------------------------------------------------
    logger.info("Building data pipelines ...")
    bundle = build_datasets(
        dataset_dir,
        image_size=(args.image_size, args.image_size),
        batch_size=args.batch_size,
        val_split=args.val_split,
        test_split=args.test_split,
        seed=args.seed,
    )
    class_names: List[str] = bundle["class_names"]
    logger.info(
        "Split: %d train batches / %d validation batches / %d test batches (batch size %d)",
        bundle["splits"]["train_batches"],
        bundle["splits"]["validation_batches"],
        bundle["splits"]["test_batches"],
        args.batch_size,
    )
    logger.info("Classes (%d): %s", len(class_names), ", ".join(class_names))

    class_weights = (
        None
        if args.no_class_weights
        else compute_class_weights(bundle["images_per_class"], class_names)
    )
    if class_weights:
        logger.info("Class weights: %s", class_weights)

    # ---- 4. model ---------------------------------------------------------
    logger.info("Building %s classifier ...", BASE_MODEL_NAME)
    model = build_model(
        num_classes=len(class_names),
        image_size=(args.image_size, args.image_size),
        dropout=args.dropout,
        weights=None if args.no_imagenet else "imagenet",
    )
    compile_model(model, learning_rate=args.learning_rate, label_smoothing=args.label_smoothing)
    model.summary()

    args.model_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = args.model_dir / MODEL_FILENAME

    # ---- 5. stage 1: train the head --------------------------------------
    logger.info("=" * 72)
    logger.info("Stage 1/2 - training the classification head (base frozen), %d epochs", args.epochs)
    logger.info("=" * 72)
    stage1 = model.fit(
        bundle["train"],
        validation_data=bundle["validation"],
        epochs=args.epochs,
        class_weight=class_weights,
        callbacks=build_callbacks(checkpoint_path, args.report_dir, args.patience),
        verbose=1,
    )
    history = dict(stage1.history)
    stage1_epochs = len(history.get("loss", []))
    fine_tune_start: Optional[int] = None

    # ---- 6. stage 2: fine-tune -------------------------------------------
    if args.fine_tune_epochs > 0:
        logger.info("=" * 72)
        logger.info(
            "Stage 2/2 - fine-tuning the top %d base layers at lr=%g, %d epochs",
            args.fine_tune_layers,
            args.fine_tune_learning_rate,
            args.fine_tune_epochs,
        )
        logger.info("=" * 72)
        unfrozen = unfreeze_top_layers(model, args.fine_tune_layers)
        compile_model(
            model,
            learning_rate=args.fine_tune_learning_rate,
            label_smoothing=args.label_smoothing,
        )
        logger.info("Trainable parameters now: %s", count_parameters(model))

        stage2 = model.fit(
            bundle["train"],
            validation_data=bundle["validation"],
            epochs=stage1_epochs + args.fine_tune_epochs,
            initial_epoch=stage1_epochs,
            class_weight=class_weights,
            callbacks=build_callbacks(checkpoint_path, args.report_dir, args.patience),
            verbose=1,
        )
        history = merge_histories(history, dict(stage2.history))
        fine_tune_start = stage1_epochs
        logger.info("Fine-tuning finished (%d layers were trainable).", unfrozen)

    # ---- 7. restore the best checkpoint ----------------------------------
    if checkpoint_path.is_file():
        logger.info("Reloading the best checkpoint from %s", checkpoint_path)
        model = tf.keras.models.load_model(checkpoint_path)
    else:
        logger.warning("No checkpoint was written; saving the final in-memory model.")
        model.save(checkpoint_path)

    # ---- 8. evaluation ----------------------------------------------------
    metrics = evaluate_model(model, bundle["test"], class_names, report_dir=args.report_dir)

    curves = plot_training_curves(
        history, args.report_dir / "training_curves.png", fine_tune_start
    )
    (args.report_dir / "training_history.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )
    (args.report_dir / "model_summary.txt").write_text(
        "\n".join(model_summary_lines(model)), encoding="utf-8"
    )

    # ---- 9. labels + metadata --------------------------------------------
    catalogue = build_label_catalogue(class_names)
    args.labels_path.parent.mkdir(parents=True, exist_ok=True)
    args.labels_path.write_text(json.dumps(catalogue, indent=2), encoding="utf-8")
    logger.info("Class labels written to %s", args.labels_path)

    elapsed = time.time() - started_at
    metadata: Dict[str, Any] = {
        "model_name": "plant_disease_mobilenetv2",
        "model_file": MODEL_FILENAME,
        "base_model": BASE_MODEL_NAME,
        "trained": True,
        "test_mode": False,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_duration_seconds": round(elapsed, 1),
        "tensorflow_version": tf.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "num_classes": len(class_names),
        "class_names": class_names,
        "image_size": [args.image_size, args.image_size],
        "preprocessing": {
            "scaling": "in_model",
            "note": "The saved model contains a Rescaling(1/127.5, offset=-1) layer, "
                    "so callers feed float32 RGB pixels in the 0..255 range.",
            "resize": "bilinear",
        },
        "dataset": {
            "directory": str(Path(dataset_dir).resolve()),
            "total_images": bundle["total_images"],
            "images_per_class": bundle["images_per_class"],
            "val_split": args.val_split,
            "test_split": args.test_split,
            "seed": args.seed,
            "max_images_per_class": args.max_images_per_class or None,
        },
        "training": {
            "epochs_stage1": stage1_epochs,
            "epochs_stage2": max(0, len(history.get("loss", [])) - stage1_epochs),
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "fine_tune_learning_rate": args.fine_tune_learning_rate,
            "fine_tune_layers": args.fine_tune_layers,
            "dropout": args.dropout,
            "label_smoothing": args.label_smoothing,
            "class_weights_used": class_weights is not None,
            "imagenet_weights": not args.no_imagenet,
            "augmentation": [
                "RandomFlip(horizontal_and_vertical)",
                "RandomRotation(0.25)",
                "RandomZoom(0.2)",
                "RandomTranslation(0.1, 0.1)",
                "RandomContrast(0.2)",
                "RandomBrightness(0.2)",
            ],
        },
        "parameters": count_parameters(model),
        "metrics": {
            "accuracy": metrics["accuracy"],
            "top3_accuracy": metrics["top3_accuracy"],
            "healthy_vs_diseased_accuracy": metrics["healthy_vs_diseased_accuracy"],
            "macro_precision": metrics["macro"]["precision"],
            "macro_recall": metrics["macro"]["recall"],
            "macro_f1": metrics["macro"]["f1_score"],
            "weighted_f1": metrics["weighted"]["f1_score"],
            "test_samples": metrics["test_samples"],
        },
        "suggested_confidence_threshold": metrics["suggested_confidence_threshold"],
        "artefacts": {
            **metrics.get("report_files", {}),
            "training_curves": str(curves) if curves else None,
            "training_history": str(args.report_dir / "training_history.json"),
        },
    }
    metadata_path = args.model_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print()
    logger.info("Model saved      : %s", checkpoint_path)
    logger.info("Metadata saved   : %s", metadata_path)
    logger.info("Labels saved     : %s", args.labels_path)
    logger.info("Reports saved    : %s", args.report_dir)
    logger.info("Test accuracy    : %.2f%%", metrics["accuracy"] * 100)
    logger.info("Macro F1-score   : %.4f", metrics["macro"]["f1_score"])
    logger.info("Total time       : %.1f minutes", elapsed / 60.0)
    logger.info("Restart the Flask backend so it picks up the new model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
