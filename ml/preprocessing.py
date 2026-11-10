"""
preprocessing.py
================
All image and dataset preparation logic lives here so that training,
evaluation and inference share exactly the same pipeline.

Two independent groups of helpers:

1. Inference helpers (``decode_image_bytes``, ``resize_for_model``,
   ``assess_image_quality``, ``preprocess_for_model``). These only need
   Pillow / NumPy / OpenCV and are safe to import in a web process.

2. Dataset helpers (``validate_dataset``, ``build_datasets``,
   ``build_augmentation_pipeline``). These import TensorFlow lazily, so the
   module can still be imported on a machine without TensorFlow.

Normalisation note
------------------
The saved model contains its own ``Rescaling(1/127.5, offset=-1)`` layer, which
is the normalisation MobileNetV2 expects. Therefore the pipeline here feeds the
network float32 RGB pixels in the ``0..255`` range and the network normalises
internally. This removes any chance of a train/serve normalisation mismatch.
``saved_model/metadata.json`` records this with ``preprocessing.scaling =
"in_model"``; if a model was trained with external scaling instead, set it to
``"mobilenet_v2"`` and ``preprocess_for_model`` will apply it here.
"""

from __future__ import annotations

import io
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

IMAGE_SIZE: Tuple[int, int] = (224, 224)   # MobileNetV2 native input size
CHANNELS = 3
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Image quality gates. Anything outside these ranges produces an
# "unknown / poor image quality" result instead of a disease prediction.
DEFAULT_QUALITY_THRESHOLDS: Dict[str, float] = {
    "min_side_pixels": 64.0,     # reject thumbnails
    "min_sharpness": 30.0,       # variance of the Laplacian
    "min_brightness": 25.0,      # mean luminance (0..255)
    "max_brightness": 240.0,
    "min_contrast": 12.0,        # standard deviation of luminance
    "min_plant_pixel_ratio": 0.04,  # fraction of plant-like (green/brown) pixels
}

try:  # OpenCV is used for resizing and sharpness when available.
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore
    _HAS_CV2 = False


# --------------------------------------------------------------------------- #
# Inference helpers
# --------------------------------------------------------------------------- #

class ImageDecodeError(ValueError):
    """Raised when the supplied bytes are not a readable image."""


def decode_image_bytes(data: bytes) -> np.ndarray:
    """
    Decode raw bytes into an RGB ``uint8`` NumPy array.

    EXIF orientation is applied, palette/grayscale/alpha images are converted to
    3-channel RGB. Raises :class:`ImageDecodeError` for unreadable input.
    """
    if not data:
        raise ImageDecodeError("Empty image payload.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            return np.asarray(image, dtype=np.uint8)
    except UnidentifiedImageError as exc:
        raise ImageDecodeError("File is not a recognised image format.") from exc
    except OSError as exc:
        raise ImageDecodeError(f"Image file appears to be truncated or corrupt: {exc}") from exc


def load_image_file(path: str | os.PathLike[str]) -> np.ndarray:
    """Read an image from disk into an RGB ``uint8`` array."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Image not found: {file_path}")
    return decode_image_bytes(file_path.read_bytes())


def resize_for_model(
    image: np.ndarray,
    image_size: Sequence[int] = IMAGE_SIZE,
) -> np.ndarray:
    """Resize an RGB array to ``image_size`` using bilinear interpolation."""
    target_h, target_w = int(image_size[0]), int(image_size[1])
    if image.shape[0] == target_h and image.shape[1] == target_w:
        return image.astype(np.float32)

    if _HAS_CV2:
        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)
    else:  # Pillow fallback
        with Image.fromarray(image) as pil_image:
            resized = np.asarray(
                pil_image.resize((target_w, target_h), Image.BILINEAR), dtype=np.uint8
            )
    return resized.astype(np.float32)


def _to_luminance(image: np.ndarray) -> np.ndarray:
    """Convert an RGB array to a float32 luminance channel in 0..255."""
    if _HAS_CV2:
        return cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return image.astype(np.float32) @ weights


def _laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the Laplacian - the standard cheap focus/blur measure."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0

    if _HAS_CV2:
        # The destination depth has to be compatible with the source depth:
        # OpenCV does not implement float32 -> CV_64F for this filter, so the
        # input is normalised to float32/CV_32F explicitly.
        return float(cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F).var())

    kernel_response = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(np.var(kernel_response))


def _plant_pixel_ratio(image: np.ndarray) -> float:
    """
    Fraction of pixels that look like plant tissue.

    Healthy leaves are green; blighted / rusted tissue is yellow-brown. Both are
    captured by looking for pixels where the red+green response clearly exceeds
    blue, which excludes grey walls, sky, paper and most indoor backgrounds.
    """
    rgb = image.astype(np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    greenish = (green > blue + 12) & (green > 40)
    brownish = (red > blue + 25) & (green > blue + 8) & (red > 50)
    plant_like = greenish | brownish
    return float(np.count_nonzero(plant_like) / plant_like.size)


def assess_image_quality(
    image: np.ndarray,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Measure whether an image is good enough to classify.

    Returns ``{"passed": bool, "issues": [...], "metrics": {...}}``. The caller
    (inference pipeline) converts a failed check into an explicit
    "unknown / poor image quality" response rather than a disease name.
    """
    limits = {**DEFAULT_QUALITY_THRESHOLDS, **(thresholds or {})}

    if image.ndim != 3 or image.shape[2] != CHANNELS:
        return {
            "passed": False,
            "issues": ["Image is not a 3-channel colour image."],
            "metrics": {},
        }

    height, width = image.shape[:2]
    gray = _to_luminance(image)

    metrics = {
        "width": int(width),
        "height": int(height),
        "sharpness": round(_laplacian_variance(gray), 2),
        "brightness": round(float(np.mean(gray)), 2),
        "contrast": round(float(np.std(gray)), 2),
        "plant_pixel_ratio": round(_plant_pixel_ratio(image), 4),
    }

    issues: List[str] = []
    if min(height, width) < limits["min_side_pixels"]:
        issues.append(
            f"Resolution too low ({width}x{height}px); "
            f"at least {int(limits['min_side_pixels'])}px on the short side is required."
        )
    if metrics["sharpness"] < limits["min_sharpness"]:
        issues.append("Image is out of focus or motion blurred.")
    if metrics["brightness"] < limits["min_brightness"]:
        issues.append("Image is too dark - switch on the white LED or add light.")
    if metrics["brightness"] > limits["max_brightness"]:
        issues.append("Image is over-exposed - reduce the LED brightness or move the light back.")
    if metrics["contrast"] < limits["min_contrast"]:
        issues.append("Image is almost flat (very low contrast); the leaf may be out of frame.")
    if metrics["plant_pixel_ratio"] < limits["min_plant_pixel_ratio"]:
        issues.append("No leaf-like region detected - frame a single leaf filling most of the view.")

    return {"passed": not issues, "issues": issues, "metrics": metrics}


def preprocess_for_model(
    image: np.ndarray,
    image_size: Sequence[int] = IMAGE_SIZE,
    scaling: str = "in_model",
) -> np.ndarray:
    """
    Turn an RGB array into a batched tensor ready for ``model.predict``.

    ``scaling``:
        ``"in_model"``     - leave pixels in 0..255 (model has a Rescaling layer).
        ``"mobilenet_v2"`` - scale to -1..1 here (model has no Rescaling layer).
        ``"zero_one"``     - scale to 0..1 here.
    """
    resized = resize_for_model(image, image_size)

    if scaling == "mobilenet_v2":
        resized = (resized / 127.5) - 1.0
    elif scaling == "zero_one":
        resized = resized / 255.0
    elif scaling != "in_model":
        raise ValueError(f"Unknown scaling mode: {scaling!r}")

    return np.expand_dims(resized.astype(np.float32), axis=0)


# --------------------------------------------------------------------------- #
# Dataset helpers (TensorFlow)
# --------------------------------------------------------------------------- #

def _import_tensorflow():
    """Import TensorFlow on demand with an actionable error message."""
    try:
        import tensorflow as tf  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "TensorFlow is required for dataset loading and training.\n"
            "Install it with:  pip install -r backend/requirements.txt"
        ) from exc
    return tf


def discover_classes(dataset_dir: str | os.PathLike[str]) -> List[str]:
    """Return sorted class directory names - the same order Keras uses."""
    root = Path(dataset_dir)
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def count_images_per_class(dataset_dir: str | os.PathLike[str]) -> Dict[str, int]:
    """Count readable image files inside every class directory."""
    root = Path(dataset_dir)
    counts: Dict[str, int] = {}
    for class_name in discover_classes(root):
        class_dir = root / class_name
        counts[class_name] = sum(
            1
            for item in class_dir.rglob("*")
            if item.is_file() and item.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
        )
    return counts


class DatasetValidationError(RuntimeError):
    """Raised when the dataset directory cannot be used for training."""


def validate_dataset(
    dataset_dir: str | os.PathLike[str],
    min_images_per_class: int = 20,
    raise_on_error: bool = True,
) -> Dict[str, Any]:
    """
    Check that ``dataset_dir`` is a usable ``class_name/image.jpg`` tree.

    Returns a report dictionary. When ``raise_on_error`` is True (the default
    for training) a :class:`DatasetValidationError` is raised with setup
    instructions instead of failing later with an obscure Keras error.
    """
    root = Path(dataset_dir)
    errors: List[str] = []
    warnings: List[str] = []

    if not root.exists():
        errors.append(f"Dataset directory does not exist: {root}")
    elif not root.is_dir():
        errors.append(f"Dataset path is not a directory: {root}")

    classes = discover_classes(root) if root.is_dir() else []
    counts = count_images_per_class(root) if classes else {}

    if root.is_dir() and not classes:
        errors.append(
            f"No class sub-directories found inside {root}. Expected layout:\n"
            "    ml/dataset/\n"
            "      Tomato___Early_blight/   img001.jpg ...\n"
            "      Tomato___healthy/        img001.jpg ...\n"
            "      Potato___Late_blight/    img001.jpg ..."
        )
    if classes and len(classes) < 2:
        errors.append(
            f"Only one class ({classes[0]}) was found. Classification needs at least two."
        )

    empty = [name for name, count in counts.items() if count == 0]
    if empty:
        errors.append("These class directories contain no images: " + ", ".join(sorted(empty)))

    sparse = {
        name: count
        for name, count in counts.items()
        if 0 < count < min_images_per_class
    }
    for name, count in sorted(sparse.items()):
        warnings.append(
            f"Class '{name}' has only {count} images (recommended minimum "
            f"is {min_images_per_class}); results for it will be unreliable."
        )

    total = sum(counts.values())
    if counts:
        largest, smallest = max(counts.values()), min(counts.values())
        if smallest > 0 and largest / smallest > 10:
            warnings.append(
                f"Severe class imbalance detected (largest class {largest} images, "
                f"smallest {smallest}). Training applies class weights to compensate."
            )

    report = {
        "dataset_dir": str(root.resolve()) if root.exists() else str(root),
        "valid": not errors,
        "num_classes": len(classes),
        "classes": classes,
        "images_per_class": counts,
        "total_images": total,
        "errors": errors,
        "warnings": warnings,
    }

    if errors and raise_on_error:
        raise DatasetValidationError(
            "Dataset validation failed:\n  - " + "\n  - ".join(errors)
            + "\n\nDownload the PlantVillage dataset and extract the class folders "
              "into ml/dataset/ (see docs/installation.md, section 'Dataset')."
        )
    return report


def build_augmentation_pipeline(seed: int = 42):
    """
    Keras augmentation layers applied to the training split only.

    Leaf photographs have no canonical orientation, so flips and rotations are
    safe. Brightness/contrast jitter models the variation introduced by the
    ESP32-CAM's white LED at different distances.
    """
    tf = _import_tensorflow()
    layers = tf.keras.layers

    return tf.keras.Sequential(
        [
            layers.RandomFlip("horizontal_and_vertical", seed=seed),
            layers.RandomRotation(0.25, fill_mode="reflect", seed=seed),
            layers.RandomZoom(0.2, fill_mode="reflect", seed=seed),
            layers.RandomTranslation(0.1, 0.1, fill_mode="reflect", seed=seed),
            layers.RandomContrast(0.2, seed=seed),
            layers.RandomBrightness(0.2, value_range=(0.0, 255.0), seed=seed),
        ],
        name="data_augmentation",
    )


def build_datasets(
    dataset_dir: str | os.PathLike[str],
    image_size: Sequence[int] = IMAGE_SIZE,
    batch_size: int = 32,
    val_split: float = 0.15,
    test_split: float = 0.15,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Build deterministic train / validation / test ``tf.data`` pipelines.

    Keras' ``image_dataset_from_directory`` only produces two subsets, so the
    held-out portion (``val_split + test_split``) is loaded once and then cut in
    two at batch granularity. Because ``seed`` drives the shuffle, re-running
    with the same seed reproduces the identical test split - which is what lets
    ``evaluate.py`` score a model it did not train.
    """
    tf = _import_tensorflow()

    if not 0.0 < val_split < 1.0 or not 0.0 < test_split < 1.0:
        raise ValueError("val_split and test_split must each be between 0 and 1.")
    holdout = val_split + test_split
    if holdout >= 0.9:
        raise ValueError("val_split + test_split must leave at least 10% for training.")

    image_size = (int(image_size[0]), int(image_size[1]))

    train_ds = tf.keras.utils.image_dataset_from_directory(
        dataset_dir,
        labels="inferred",
        label_mode="categorical",
        image_size=image_size,
        batch_size=batch_size,
        shuffle=True,
        seed=seed,
        validation_split=holdout,
        subset="training",
        interpolation="bilinear",
    )
    holdout_ds = tf.keras.utils.image_dataset_from_directory(
        dataset_dir,
        labels="inferred",
        label_mode="categorical",
        image_size=image_size,
        batch_size=batch_size,
        shuffle=True,
        seed=seed,
        validation_split=holdout,
        subset="validation",
        interpolation="bilinear",
    )

    class_names: List[str] = list(train_ds.class_names)

    holdout_batches = int(holdout_ds.cardinality().numpy())
    if holdout_batches <= 1:
        raise DatasetValidationError(
            "The validation/test hold-out contains a single batch. Add more images "
            "or lower --batch-size so the split can be divided."
        )
    val_batches = max(1, int(round(holdout_batches * (val_split / holdout))))
    val_batches = min(val_batches, holdout_batches - 1)

    val_ds = holdout_ds.take(val_batches)
    test_ds = holdout_ds.skip(val_batches)

    autotune = tf.data.AUTOTUNE
    augment = build_augmentation_pipeline(seed=seed)

    train_prepared = (
        train_ds.shuffle(min(1000, batch_size * 20), seed=seed, reshuffle_each_iteration=True)
        .map(lambda x, y: (augment(x, training=True), y), num_parallel_calls=autotune)
        .prefetch(autotune)
    )
    val_prepared = val_ds.cache().prefetch(autotune)
    test_prepared = test_ds.cache().prefetch(autotune)

    counts = count_images_per_class(dataset_dir)
    total = sum(counts.values())

    return {
        "train": train_prepared,
        "validation": val_prepared,
        "test": test_prepared,
        "class_names": class_names,
        "num_classes": len(class_names),
        "image_size": image_size,
        "batch_size": batch_size,
        "seed": seed,
        "splits": {
            "train_batches": int(train_ds.cardinality().numpy()),
            "validation_batches": val_batches,
            "test_batches": holdout_batches - val_batches,
            "val_split": val_split,
            "test_split": test_split,
        },
        "images_per_class": counts,
        "total_images": total,
    }


def compute_class_weights(images_per_class: Dict[str, int], class_names: Sequence[str]) -> Dict[int, float]:
    """
    Inverse-frequency class weights keyed by class index.

    PlantVillage is noticeably imbalanced (e.g. far more tomato images than
    pepper), so without weighting the model drifts toward the majority classes.
    """
    counts = [max(1, int(images_per_class.get(name, 0))) for name in class_names]
    total = float(sum(counts))
    n_classes = len(counts)
    return {
        index: round(total / (n_classes * count), 4)
        for index, count in enumerate(counts)
    }


def summarise_dataset_report(report: Dict[str, Any]) -> str:
    """Human readable dataset report used by the training CLI."""
    lines = [
        "Dataset report",
        "--------------",
        f"Location      : {report['dataset_dir']}",
        f"Classes       : {report['num_classes']}",
        f"Total images  : {report['total_images']}",
    ]
    if report["images_per_class"]:
        lines.append("Images / class:")
        width = max(len(name) for name in report["images_per_class"])
        for name, count in sorted(report["images_per_class"].items()):
            lines.append(f"  {name.ljust(width)}  {count}")
    for warning in report["warnings"]:
        lines.append(f"  [warning] {warning}")
    for error in report["errors"]:
        lines.append(f"  [error]   {error}")
    return "\n".join(lines)


__all__ = [
    "IMAGE_SIZE",
    "CHANNELS",
    "SUPPORTED_IMAGE_SUFFIXES",
    "DEFAULT_QUALITY_THRESHOLDS",
    "ImageDecodeError",
    "DatasetValidationError",
    "decode_image_bytes",
    "load_image_file",
    "resize_for_model",
    "assess_image_quality",
    "preprocess_for_model",
    "discover_classes",
    "count_images_per_class",
    "validate_dataset",
    "build_augmentation_pipeline",
    "build_datasets",
    "compute_class_weights",
    "summarise_dataset_report",
]


if __name__ == "__main__":
    import json as _json
    import sys as _sys

    target = _sys.argv[1] if len(_sys.argv) > 1 else str(Path(__file__).parent / "dataset")
    print(summarise_dataset_report(validate_dataset(target, raise_on_error=False)))
    print()
    print(_json.dumps({"image_size": IMAGE_SIZE, "opencv_available": _HAS_CV2}, indent=2))
