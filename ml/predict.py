"""
predict.py
==========
The inference pipeline. This is the single place where an image becomes a
prediction; the Flask backend wraps :class:`PlantDiseasePredictor` rather than
reimplementing any of it.

Guarantees
----------
* Every probability comes from ``model.predict`` - nothing is hardcoded.
* The model can only ever return a class from ``class_labels.json``, which is
  written by ``train.py`` from the dataset's own folder names.
* A prediction is marked **inconclusive** (and no disease name is reported) when
  the image fails the quality gate or when the top confidence falls below the
  configured threshold.
* If the loaded model is an untrained bootstrap model, every result carries
  ``model.trained = false`` and ``is_validated_prediction = false`` so the UI
  can never present it as a real diagnosis.

CLI
---
    python predict.py path/to/leaf.jpg
    python predict.py leaf.jpg --threshold 0.8 --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from disease_info import get_disease_info  # noqa: E402
from label_utils import parse_label, parse_labels  # noqa: E402
from preprocessing import (  # noqa: E402
    DEFAULT_QUALITY_THRESHOLDS,
    IMAGE_SIZE,
    ImageDecodeError,
    assess_image_quality,
    decode_image_bytes,
    load_image_file,
    preprocess_for_model,
)

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = ML_DIR / "saved_model" / "plant_disease_model.keras"
DEFAULT_LABELS_PATH = ML_DIR / "class_labels.json"
DEFAULT_METADATA_PATH = ML_DIR / "saved_model" / "metadata.json"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70

STATUS_HEALTHY = "healthy"
STATUS_DISEASED = "diseased"
STATUS_UNCERTAIN = "uncertain"
STATUS_UNKNOWN = "unknown"

ImageInput = Union[bytes, bytearray, np.ndarray, str, Path]


class ModelNotLoadedError(RuntimeError):
    """Raised when a prediction is requested before a model is available."""


class PlantDiseasePredictor:
    """
    Thread-safe wrapper around the trained Keras model.

    Loading is lazy and explicit: construct the object cheaply at import time,
    then call :meth:`load` (or let :meth:`predict` trigger it) so that a missing
    model file degrades into a clear status message instead of a crash at
    startup.
    """

    def __init__(
        self,
        model_path: Union[str, Path] = DEFAULT_MODEL_PATH,
        labels_path: Union[str, Path] = DEFAULT_LABELS_PATH,
        metadata_path: Union[str, Path] = DEFAULT_METADATA_PATH,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        quality_thresholds: Optional[Dict[str, float]] = None,
        enforce_quality_gate: bool = True,
        attach_disease_info: bool = True,
    ) -> None:
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)
        self.metadata_path = Path(metadata_path)
        self.confidence_threshold = float(confidence_threshold)
        self.quality_thresholds = {**DEFAULT_QUALITY_THRESHOLDS, **(quality_thresholds or {})}
        self.enforce_quality_gate = bool(enforce_quality_gate)
        self.attach_disease_info = bool(attach_disease_info)

        self._model = None
        self._lock = threading.Lock()
        self._raw_labels: List[str] = []
        self._parsed_labels: List[Dict[str, Any]] = []
        self._metadata: Dict[str, Any] = {}
        self._image_size = tuple(IMAGE_SIZE)
        self._scaling = "in_model"
        self._load_error: Optional[str] = None
        self._loaded_at: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def is_trained(self) -> bool:
        """False for the explicitly labelled untrained bootstrap model."""
        return bool(self._metadata.get("trained", False))

    @property
    def mode(self) -> str:
        """``"trained"`` for a real model, ``"test"`` for the bootstrap model."""
        if not self.is_loaded:
            return "unavailable"
        return "trained" if self.is_trained else "test"

    @property
    def class_names(self) -> List[str]:
        return list(self._raw_labels)

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _read_labels(self) -> List[str]:
        if not self.labels_path.is_file():
            raise FileNotFoundError(
                f"Class label file missing: {self.labels_path}\n"
                "Run `python train.py` (with a dataset) or "
                "`python create_test_model.py` to generate it."
            )
        payload = json.loads(self.labels_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if payload.get("raw_labels"):
                return list(payload["raw_labels"])
            if payload.get("classes"):
                return [item["raw"] for item in payload["classes"]]
        if isinstance(payload, list):
            return list(payload)
        raise ValueError(f"Unrecognised class label file format: {self.labels_path}")

    def _read_metadata(self) -> Dict[str, Any]:
        if not self.metadata_path.is_file():
            logger.warning(
                "metadata.json not found at %s; assuming an untrained model until "
                "training writes it.",
                self.metadata_path,
            )
            return {"trained": False, "test_mode": True, "note": "metadata.json missing"}
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def load(self, force: bool = False) -> bool:
        """
        Load the model, labels and metadata. Returns True on success.

        Never raises: failures are recorded in :attr:`load_error` and surfaced
        through :meth:`status`, which is what ``/api/health`` reports.
        """
        with self._lock:
            if self._model is not None and not force:
                return True

            self._load_error = None
            try:
                if not self.model_path.is_file():
                    raise FileNotFoundError(
                        f"Model file not found: {self.model_path}\n"
                        "Train a model with `python ml/train.py --dataset-dir ml/dataset`, "
                        "or create an explicitly labelled untrained test model with "
                        "`python ml/create_test_model.py`."
                    )

                try:
                    import tensorflow as tf  # noqa: PLC0415
                except ImportError as exc:
                    raise ImportError(
                        "TensorFlow is not installed. Run: "
                        "pip install -r backend/requirements.txt"
                    ) from exc

                self._raw_labels = self._read_labels()
                self._parsed_labels = parse_labels(self._raw_labels)
                self._metadata = self._read_metadata()

                size = self._metadata.get("image_size") or list(IMAGE_SIZE)
                self._image_size = (int(size[0]), int(size[1]))
                self._scaling = str(
                    (self._metadata.get("preprocessing") or {}).get("scaling", "in_model")
                )

                logger.info("Loading Keras model from %s ...", self.model_path)
                started = time.time()
                model = tf.keras.models.load_model(self.model_path)

                output_units = int(model.output_shape[-1])
                if output_units != len(self._raw_labels):
                    raise ValueError(
                        f"Model/label mismatch: the model outputs {output_units} classes "
                        f"but {self.labels_path.name} lists {len(self._raw_labels)}. "
                        "Re-run training so both files are regenerated together."
                    )

                self._model = model
                self._loaded_at = time.time()
                logger.info(
                    "Model ready in %.2fs - %d classes, mode=%s",
                    self._loaded_at - started,
                    len(self._raw_labels),
                    self.mode,
                )
                if not self.is_trained:
                    logger.warning(
                        "This model is an UNTRAINED bootstrap model (test mode). Its outputs "
                        "are not valid diagnoses and every API response is tagged accordingly."
                    )
                return True

            except Exception as exc:  # noqa: BLE001 - reported, not raised
                self._model = None
                self._load_error = str(exc)
                logger.error("Model could not be loaded: %s", exc)
                return False

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._loaded_at = None

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        """Everything ``/api/health`` and the dashboard banner need."""
        metrics = (self._metadata.get("metrics") or {}) if self._metadata else {}
        return {
            "loaded": self.is_loaded,
            "trained": self.is_trained,
            "mode": self.mode,
            "is_test_mode": self.is_loaded and not self.is_trained,
            "model_path": str(self.model_path),
            "model_file_exists": self.model_path.is_file(),
            "labels_path": str(self.labels_path),
            "labels_file_exists": self.labels_path.is_file(),
            "num_classes": len(self._raw_labels),
            "class_names": list(self._raw_labels),
            "image_size": list(self._image_size),
            "input_scaling": self._scaling,
            "confidence_threshold": self.confidence_threshold,
            "base_model": self._metadata.get("base_model"),
            "trained_at": self._metadata.get("created_at"),
            "tensorflow_version": self._metadata.get("tensorflow_version"),
            "metrics": metrics,
            "error": self._load_error,
        }

    def classes(self) -> Dict[str, Any]:
        """Supported plants and conditions, for ``/api/classes``."""
        plants: Dict[str, List[Dict[str, Any]]] = {}
        for index, info in enumerate(self._parsed_labels):
            plant = str(info["plant"])
            plants.setdefault(plant, []).append(
                {
                    "index": index,
                    "class": info["raw"],
                    "disease": info["disease"],
                    "is_healthy": info["is_healthy"],
                    "severity": get_disease_info(str(info["raw"])).get("severity", "unknown"),
                }
            )
        return {
            "num_classes": len(self._parsed_labels),
            "classes": self._parsed_labels,
            "plants": plants,
            "plant_names": sorted(plants.keys()),
            "model_mode": self.mode,
        }

    # ------------------------------------------------------------------ #
    # Prediction
    # ------------------------------------------------------------------ #

    @staticmethod
    def _as_array(image: ImageInput) -> np.ndarray:
        if isinstance(image, np.ndarray):
            return image
        if isinstance(image, (bytes, bytearray)):
            return decode_image_bytes(bytes(image))
        if isinstance(image, (str, Path)):
            return load_image_file(image)
        raise TypeError(f"Unsupported image input type: {type(image)!r}")

    def _inconclusive(
        self,
        status: str,
        reason: str,
        quality: Dict[str, Any],
        warnings: List[str],
        candidates: Optional[List[Dict[str, Any]]] = None,
        all_probabilities: Optional[List[Dict[str, Any]]] = None,
        confidence: float = 0.0,
        elapsed_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Build an explicit unknown/uncertain result with no disease claimed.

        ``candidates`` holds the top few classes so the operator can see what the
        model was leaning toward; ``all_probabilities`` is the complete softmax
        vector and sums to 1. Both are empty when the quality gate rejected the
        image before the model ever ran.
        """
        return {
            "success": True,
            "is_conclusive": False,
            "is_validated_prediction": False,
            "plant_name": "Unknown",
            "predicted_class": None,
            "predicted_disease": "Uncertain" if status == STATUS_UNCERTAIN else "Unknown",
            "display_label": "Uncertain result" if status == STATUS_UNCERTAIN else "Unknown / unusable image",
            "detection_status": status,
            "is_healthy": None,
            "confidence": round(float(confidence), 4),
            "confidence_percent": round(float(confidence) * 100.0, 2),
            "confidence_threshold": self.confidence_threshold,
            "reason": reason,
            "top_predictions": candidates or [],
            "class_probabilities": all_probabilities if all_probabilities is not None else [],
            "disease_info": None,
            "image_quality": quality,
            "model": {
                "mode": self.mode,
                "trained": self.is_trained,
                "base_model": self._metadata.get("base_model"),
                "num_classes": len(self._raw_labels),
            },
            "inference_ms": round(elapsed_ms, 1),
            "warnings": warnings,
        }

    def predict(
        self,
        image: ImageInput,
        confidence_threshold: Optional[float] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Classify one leaf image.

        Raises :class:`ModelNotLoadedError` if no model is available and
        :class:`ImageDecodeError` if the input is not a readable image. Every
        other outcome - including "I don't know" - comes back as a normal result
        dictionary.
        """
        if not self.is_loaded and not self.load():
            raise ModelNotLoadedError(
                self._load_error or "No trained model is available for inference."
            )

        threshold = (
            self.confidence_threshold
            if confidence_threshold is None
            else float(confidence_threshold)
        )
        started = time.perf_counter()

        array = self._as_array(image)
        quality = assess_image_quality(array, self.quality_thresholds)

        warnings: List[str] = []
        if not self.is_trained:
            warnings.append(
                "TEST MODE: this model has not been trained on any dataset. The numbers "
                "below come from an untrained network and are not a real diagnosis. "
                "Train a model with ml/train.py to get valid predictions."
            )

        # Quality gate - report "unknown" instead of guessing from a bad image.
        if self.enforce_quality_gate and not quality["passed"]:
            elapsed = (time.perf_counter() - started) * 1000.0
            return self._inconclusive(
                status=STATUS_UNKNOWN,
                reason="Image quality is too poor to classify: " + " ".join(quality["issues"]),
                quality=quality,
                warnings=warnings + quality["issues"],
                elapsed_ms=elapsed,
            )

        tensor = preprocess_for_model(array, self._image_size, self._scaling)

        with self._lock:
            probabilities = self._model.predict(tensor, verbose=0)  # type: ignore[union-attr]

        probabilities = np.asarray(probabilities, dtype=np.float64)[0]
        total = float(probabilities.sum())
        if total > 0:
            probabilities = probabilities / total  # guard against tiny numerical drift

        order = np.argsort(-probabilities)
        ranked = [
            {
                "class": self._raw_labels[index],
                "plant": self._parsed_labels[index]["plant"],
                "disease": self._parsed_labels[index]["disease"],
                "is_healthy": self._parsed_labels[index]["is_healthy"],
                "probability": round(float(probabilities[index]), 6),
                "probability_percent": round(float(probabilities[index]) * 100.0, 2),
            }
            for index in order
        ]
        top_predictions = ranked[: max(1, int(top_k))]

        best_index = int(order[0])
        confidence = float(probabilities[best_index])
        elapsed = (time.perf_counter() - started) * 1000.0

        # Confidence gate - below the threshold we name no disease.
        if confidence < threshold:
            return self._inconclusive(
                status=STATUS_UNCERTAIN,
                reason=(
                    f"Top confidence {confidence * 100:.1f}% is below the "
                    f"{threshold * 100:.0f}% threshold, so no diagnosis is reported. "
                    "Re-capture the leaf filling the frame with even lighting."
                ),
                quality=quality,
                warnings=warnings,
                candidates=top_predictions,
                all_probabilities=ranked,
                confidence=confidence,
                elapsed_ms=elapsed,
            )

        label = self._parsed_labels[best_index]
        is_healthy = bool(label["is_healthy"])

        result: Dict[str, Any] = {
            "success": True,
            "is_conclusive": True,
            # True only when a genuinely trained model produced this result.
            "is_validated_prediction": self.is_trained,
            "plant_name": str(label["plant"]),
            "predicted_class": str(label["raw"]),
            "predicted_disease": str(label["disease"]),
            "display_label": str(label["display"]),
            "detection_status": STATUS_HEALTHY if is_healthy else STATUS_DISEASED,
            "is_healthy": is_healthy,
            "confidence": round(confidence, 4),
            "confidence_percent": round(confidence * 100.0, 2),
            "confidence_threshold": threshold,
            "reason": None,
            "top_predictions": top_predictions,
            "class_probabilities": ranked,
            "image_quality": quality,
            "model": {
                "mode": self.mode,
                "trained": self.is_trained,
                "base_model": self._metadata.get("base_model"),
                "num_classes": len(self._raw_labels),
            },
            "inference_ms": round(elapsed, 1),
            "warnings": warnings,
        }

        if self.attach_disease_info:
            result["disease_info"] = get_disease_info(str(label["raw"]))
        else:
            result["disease_info"] = None

        return result

    def predict_batch(
        self,
        images: Sequence[ImageInput],
        confidence_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Convenience loop for scoring several images (used by CLI tools)."""
        results: List[Dict[str, Any]] = []
        for item in images:
            try:
                results.append(self.predict(item, confidence_threshold))
            except (ImageDecodeError, FileNotFoundError) as exc:
                results.append({"success": False, "error": str(exc), "input": str(item)})
        return results


# --------------------------------------------------------------------------- #
# Module level convenience
# --------------------------------------------------------------------------- #

_default_predictor: Optional[PlantDiseasePredictor] = None


def get_predictor(**kwargs: Any) -> PlantDiseasePredictor:
    """Process-wide singleton, so the model is held in memory only once."""
    global _default_predictor
    if _default_predictor is None:
        _default_predictor = PlantDiseasePredictor(**kwargs)
    return _default_predictor


def predict_image(path: Union[str, Path], **kwargs: Any) -> Dict[str, Any]:
    """One-shot helper: ``predict_image("leaf.jpg")``."""
    return get_predictor().predict(path, **kwargs)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _format_human(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    for warning in result.get("warnings", []):
        lines.append(f"[!] {warning}")
    if result.get("warnings"):
        lines.append("")

    status = result["detection_status"]
    if result["is_conclusive"]:
        lines += [
            f"Plant       : {result['plant_name']}",
            f"Condition   : {result['predicted_disease']}",
            f"Status      : {status.upper()}",
            f"Confidence  : {result['confidence_percent']:.2f}%",
        ]
        info = result.get("disease_info") or {}
        if info.get("description"):
            lines += ["", "Reference   : " + info["description"]]
    else:
        lines += [
            f"Result      : {result['display_label']}",
            f"Status      : {status.upper()}",
            f"Reason      : {result['reason']}",
        ]
        if result.get("top_predictions"):
            lines.append("")
            lines.append("Closest candidates:")
            for item in result["top_predictions"][:3]:
                lines.append(
                    f"  {item['probability_percent']:6.2f}%  {item['plant']} - {item['disease']}"
                )

    quality = result.get("image_quality", {}).get("metrics", {})
    if quality:
        lines += [
            "",
            f"Image       : {quality.get('width')}x{quality.get('height')}px, "
            f"sharpness {quality.get('sharpness')}, brightness {quality.get('brightness')}",
        ]
    lines.append(f"Inference   : {result['inference_ms']} ms  (model mode: {result['model']['mode']})")
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify one or more leaf images with the trained model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("images", nargs="+", help="Image file path(s)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--no-quality-gate", action="store_true", help="Classify even low-quality images")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a summary")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    args = parse_args(argv)

    predictor = PlantDiseasePredictor(
        model_path=args.model,
        labels_path=args.labels,
        metadata_path=args.metadata,
        confidence_threshold=args.threshold,
        enforce_quality_gate=not args.no_quality_gate,
    )
    if not predictor.load():
        print(f"ERROR: {predictor.load_error}", file=sys.stderr)
        return 2

    exit_code = 0
    for index, image_path in enumerate(args.images):
        try:
            result = predictor.predict(image_path)
        except (ImageDecodeError, FileNotFoundError) as exc:
            print(f"ERROR [{image_path}]: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if index:
                print("\n" + "-" * 60 + "\n")
            print(f"File        : {image_path}")
            print(_format_human(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
