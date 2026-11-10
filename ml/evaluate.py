"""
evaluate.py
===========
Scores a trained model on the held-out test split and writes the artefacts the
dashboard's Analytics page and the project report both need:

    ml/reports/metrics.json               accuracy / precision / recall / F1
    ml/reports/classification_report.json per-class scores
    ml/reports/confusion_matrix.csv       raw counts
    ml/reports/confusion_matrix.png       normalised heat-map
    ml/reports/evaluation_summary.txt     printable text summary

Run directly::

    python evaluate.py
    python evaluate.py --model saved_model/plant_disease_model.keras --dataset-dir dataset

``evaluate.py`` reproduces the exact test split used during training by reusing
``preprocessing.build_datasets`` with the same ``--seed``, ``--val-split`` and
``--test-split`` values, so the score is computed on images the model never saw.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Allow `python ml/evaluate.py` as well as `python evaluate.py` from inside ml/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from preprocessing import build_datasets  # noqa: E402
from label_utils import parse_labels  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
logger = logging.getLogger("evaluate")

ML_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = ML_DIR / "saved_model" / "plant_disease_model.keras"
DEFAULT_LABELS_PATH = ML_DIR / "class_labels.json"
DEFAULT_DATASET_DIR = ML_DIR / "dataset"
DEFAULT_REPORT_DIR = ML_DIR / "reports"


# --------------------------------------------------------------------------- #
# Prediction collection
# --------------------------------------------------------------------------- #

def collect_predictions(model, dataset) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Run the model over a batched ``(images, one_hot_labels)`` dataset.

    Returns ``(y_true, y_pred, y_prob)`` where ``y_prob`` holds the full softmax
    matrix, needed for top-3 accuracy and confidence analysis.
    """
    true_batches: List[np.ndarray] = []
    prob_batches: List[np.ndarray] = []

    for images, labels in dataset:
        probabilities = model.predict(images, verbose=0)
        prob_batches.append(np.asarray(probabilities))
        labels_np = np.asarray(labels)
        true_batches.append(labels_np.argmax(axis=1) if labels_np.ndim > 1 else labels_np)

    if not prob_batches:
        raise RuntimeError(
            "The test split produced no batches. Lower --batch-size or add more images."
        )

    y_prob = np.concatenate(prob_batches, axis=0)
    y_true = np.concatenate(true_batches, axis=0).astype(int)
    y_pred = y_prob.argmax(axis=1).astype(int)
    return y_true, y_pred, y_prob


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    class_names: Sequence[str],
) -> Dict[str, Any]:
    """Accuracy, macro/weighted precision-recall-F1, top-3 accuracy, per class scores."""
    from sklearn.metrics import (  # noqa: PLC0415
        accuracy_score,
        classification_report,
        confusion_matrix,
        precision_recall_fscore_support,
    )

    labels = list(range(len(class_names)))

    accuracy = float(accuracy_score(y_true, y_pred))
    macro = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    weighted = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0
    )
    per_class = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )

    k = min(3, y_prob.shape[1])
    top_k_indices = np.argsort(-y_prob, axis=1)[:, :k]
    top3_accuracy = float(np.mean([t in row for t, row in zip(y_true, top_k_indices)]))

    cm = confusion_matrix(y_true, y_pred, labels=labels)

    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=list(class_names),
        output_dict=True,
        zero_division=0,
    )

    parsed = parse_labels(list(class_names))
    healthy_indices = {i for i, info in enumerate(parsed) if info["is_healthy"]}

    # Binary healthy-vs-diseased view: the decision a farmer actually acts on.
    binary_true = np.array([1 if label in healthy_indices else 0 for label in y_true])
    binary_pred = np.array([1 if label in healthy_indices else 0 for label in y_pred])
    binary_accuracy = float(np.mean(binary_true == binary_pred))

    per_class_scores = [
        {
            "class": class_names[index],
            "plant": parsed[index]["plant"],
            "disease": parsed[index]["disease"],
            "precision": round(float(per_class[0][index]), 4),
            "recall": round(float(per_class[1][index]), 4),
            "f1_score": round(float(per_class[2][index]), 4),
            "support": int(per_class[3][index]),
        }
        for index in labels
    ]

    confidences = y_prob.max(axis=1)
    correct_mask = y_true == y_pred

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "num_classes": len(class_names),
        "test_samples": int(len(y_true)),
        "accuracy": round(accuracy, 4),
        "top3_accuracy": round(top3_accuracy, 4),
        "healthy_vs_diseased_accuracy": round(binary_accuracy, 4),
        "macro": {
            "precision": round(float(macro[0]), 4),
            "recall": round(float(macro[1]), 4),
            "f1_score": round(float(macro[2]), 4),
        },
        "weighted": {
            "precision": round(float(weighted[0]), 4),
            "recall": round(float(weighted[1]), 4),
            "f1_score": round(float(weighted[2]), 4),
        },
        "confidence": {
            "mean": round(float(np.mean(confidences)), 4),
            "mean_when_correct": round(float(np.mean(confidences[correct_mask])), 4)
            if correct_mask.any()
            else None,
            "mean_when_wrong": round(float(np.mean(confidences[~correct_mask])), 4)
            if (~correct_mask).any()
            else None,
        },
        "per_class": per_class_scores,
        "confusion_matrix": cm.tolist(),
        "class_names": list(class_names),
        "classification_report": report,
    }


def suggest_confidence_threshold(metrics: Dict[str, Any]) -> float:
    """
    Pick a sensible default for the "uncertain" cut-off.

    Sits midway between the mean confidence of wrong predictions and the mean
    confidence of correct ones, clamped to a practical 0.5 - 0.85 band.
    """
    confidence = metrics.get("confidence", {})
    correct = confidence.get("mean_when_correct")
    wrong = confidence.get("mean_when_wrong")
    if correct is None or wrong is None:
        return 0.70
    midpoint = (float(correct) + float(wrong)) / 2.0
    return round(min(0.85, max(0.50, midpoint)), 2)


# --------------------------------------------------------------------------- #
# Artefacts
# --------------------------------------------------------------------------- #

def save_confusion_matrix_csv(cm: Sequence[Sequence[int]], class_names: Sequence[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["true_class \\ predicted_class", *class_names])
        for name, row in zip(class_names, cm):
            writer.writerow([name, *row])


def save_confusion_matrix_plot(
    cm: Sequence[Sequence[int]],
    class_names: Sequence[str],
    path: Path,
    normalise: bool = True,
) -> Optional[Path]:
    """Render the confusion matrix as a PNG heat-map. Returns None if matplotlib is missing."""
    try:
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        logger.warning("matplotlib unavailable, skipping confusion matrix plot (%s).", exc)
        return None

    matrix = np.asarray(cm, dtype=float)
    if normalise:
        row_sums = matrix.sum(axis=1, keepdims=True)
        matrix = np.divide(matrix, row_sums, out=np.zeros_like(matrix), where=row_sums != 0)

    size = max(6.0, 0.62 * len(class_names) + 3.0)
    figure, axes = plt.subplots(figsize=(size, size * 0.86))
    image = axes.imshow(matrix, cmap="Greens", vmin=0.0, vmax=1.0 if normalise else matrix.max())

    axes.set_xticks(range(len(class_names)))
    axes.set_yticks(range(len(class_names)))
    axes.set_xticklabels(class_names, rotation=55, ha="right", fontsize=8)
    axes.set_yticklabels(class_names, fontsize=8)
    axes.set_xlabel("Predicted class")
    axes.set_ylabel("True class")
    axes.set_title(
        "Confusion matrix (row-normalised)" if normalise else "Confusion matrix (counts)"
    )

    threshold = matrix.max() / 2.0 if matrix.size else 0.5
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            value = matrix[row, column]
            if value <= 0:
                continue
            axes.text(
                column,
                row,
                f"{value:.2f}" if normalise else f"{int(value)}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if value > threshold else "#14532d",
            )

    figure.colorbar(image, ax=axes, fraction=0.045, pad=0.04)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def build_summary_text(metrics: Dict[str, Any]) -> str:
    lines = [
        "Model evaluation summary",
        "========================",
        f"Evaluated at              : {metrics['evaluated_at']}",
        f"Test samples              : {metrics['test_samples']}",
        f"Classes                   : {metrics['num_classes']}",
        "",
        f"Top-1 accuracy            : {metrics['accuracy'] * 100:.2f}%",
        f"Top-3 accuracy            : {metrics['top3_accuracy'] * 100:.2f}%",
        f"Healthy vs diseased acc.  : {metrics['healthy_vs_diseased_accuracy'] * 100:.2f}%",
        "",
        f"Macro precision           : {metrics['macro']['precision']:.4f}",
        f"Macro recall              : {metrics['macro']['recall']:.4f}",
        f"Macro F1-score            : {metrics['macro']['f1_score']:.4f}",
        f"Weighted F1-score         : {metrics['weighted']['f1_score']:.4f}",
        "",
        "Per-class scores",
        "----------------",
    ]
    width = max((len(item["class"]) for item in metrics["per_class"]), default=10)
    lines.append(
        f"{'class'.ljust(width)}  precision  recall   f1       support"
    )
    for item in metrics["per_class"]:
        lines.append(
            f"{item['class'].ljust(width)}  "
            f"{item['precision']:<9.4f}  {item['recall']:<7.4f} "
            f"{item['f1_score']:<8.4f} {item['support']}"
        )
    return "\n".join(lines) + "\n"


def write_reports(metrics: Dict[str, Any], report_dir: Path) -> Dict[str, str]:
    """Persist every evaluation artefact. Returns a map of artefact -> path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    class_names = metrics["class_names"]

    slim = {key: value for key, value in metrics.items() if key != "classification_report"}

    paths: Dict[str, str] = {}

    metrics_path = report_dir / "metrics.json"
    metrics_path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    paths["metrics"] = str(metrics_path)

    report_path = report_dir / "classification_report.json"
    report_path.write_text(
        json.dumps(metrics["classification_report"], indent=2), encoding="utf-8"
    )
    paths["classification_report"] = str(report_path)

    cm_csv = report_dir / "confusion_matrix.csv"
    save_confusion_matrix_csv(metrics["confusion_matrix"], class_names, cm_csv)
    paths["confusion_matrix_csv"] = str(cm_csv)

    cm_png = save_confusion_matrix_plot(
        metrics["confusion_matrix"], class_names, report_dir / "confusion_matrix.png"
    )
    if cm_png:
        paths["confusion_matrix_png"] = str(cm_png)

    summary_path = report_dir / "evaluation_summary.txt"
    summary_path.write_text(build_summary_text(metrics), encoding="utf-8")
    paths["summary"] = str(summary_path)

    return paths


# --------------------------------------------------------------------------- #
# High level entry point
# --------------------------------------------------------------------------- #

def evaluate_model(
    model,
    test_dataset,
    class_names: Sequence[str],
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> Dict[str, Any]:
    """Evaluate an in-memory model and write all report artefacts."""
    logger.info("Running inference over the test split ...")
    y_true, y_pred, y_prob = collect_predictions(model, test_dataset)
    logger.info("Scoring %d test images across %d classes ...", len(y_true), len(class_names))

    metrics = compute_metrics(y_true, y_pred, y_prob, class_names)
    metrics["suggested_confidence_threshold"] = suggest_confidence_threshold(metrics)
    metrics["report_files"] = write_reports(metrics, report_dir)

    print()
    print(build_summary_text(metrics))
    logger.info("Reports written to %s", report_dir)
    return metrics


def load_class_names(labels_path: Path) -> List[str]:
    """Read the raw class order from ``class_labels.json``."""
    if not labels_path.is_file():
        raise FileNotFoundError(
            f"Class label file not found: {labels_path}\n"
            "Train a model first (python train.py) so the labels are generated."
        )
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("raw_labels"):
        return list(payload["raw_labels"])
    if isinstance(payload, dict) and payload.get("classes"):
        return [item["raw"] for item in payload["classes"]]
    if isinstance(payload, list):
        return list(payload)
    raise ValueError(f"Unrecognised class label file format: {labels_path}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a trained plant disease model on the held-out test split.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH, help="Path to the .keras model file")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR, help="Dataset root")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH, help="class_labels.json path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Where to write reports")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--val-split", type=float, default=0.15, help="Must match the training run")
    parser.add_argument("--test-split", type=float, default=0.15, help="Must match the training run")
    parser.add_argument("--seed", type=int, default=42, help="Must match the training run")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not args.model.is_file():
        logger.error(
            "Model file not found: %s\nTrain a model first:  python train.py --dataset-dir dataset",
            args.model,
        )
        return 2

    try:
        import tensorflow as tf  # noqa: PLC0415
    except ImportError:
        logger.error("TensorFlow is not installed. Run: pip install -r ../backend/requirements.txt")
        return 2

    logger.info("Loading model: %s", args.model)
    model = tf.keras.models.load_model(args.model)

    class_names = load_class_names(args.labels)

    logger.info("Rebuilding the test split (seed=%d) ...", args.seed)
    bundle = build_datasets(
        args.dataset_dir,
        image_size=(args.image_size, args.image_size),
        batch_size=args.batch_size,
        val_split=args.val_split,
        test_split=args.test_split,
        seed=args.seed,
    )

    if list(bundle["class_names"]) != list(class_names):
        logger.error(
            "Dataset classes do not match the saved labels.\n  dataset: %s\n  labels : %s",
            bundle["class_names"],
            class_names,
        )
        return 3

    evaluate_model(model, bundle["test"], class_names, report_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
