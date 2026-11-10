"""
services/ml_service.py
======================
Owns the single in-process instance of :class:`PlantDiseasePredictor`.

Responsibilities:

* build the predictor from Flask configuration (paths, confidence threshold,
  image-quality thresholds),
* load the model once and keep it warm,
* enforce the ``ALLOW_TEST_MODE_MODEL`` policy, so a deployment can refuse to
  serve predictions from the untrained bootstrap model,
* translate ML-layer exceptions into :class:`ApiError` subclasses.

A MobileNetV2 graph is ~30 MB of resident memory, so exactly one instance is
shared across requests rather than one per request.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np

from utils.errors import ImageValidationError, ModelUnavailableError
from utils.ml_bridge import (
    ImageDecodeError,
    ModelNotLoadedError,
    PlantDiseasePredictor,
    all_known_classes,
    read_training_reports,
)

logger = logging.getLogger(__name__)

ImageInput = Union[bytes, bytearray, np.ndarray, str, Path]


class MLService:
    """Thin application-facing facade over the ML inference pipeline."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._predictor = PlantDiseasePredictor(
            model_path=config.MODEL_PATH,
            labels_path=config.LABELS_PATH,
            metadata_path=config.MODEL_METADATA_PATH,
            confidence_threshold=config.CONFIDENCE_THRESHOLD,
            quality_thresholds=config.quality_thresholds(),
            enforce_quality_gate=config.ENFORCE_QUALITY_GATE,
            attach_disease_info=True,
        )
        self._reports_dir = Path(config.REPORTS_DIR)
        self._allow_test_mode = bool(config.ALLOW_TEST_MODE_MODEL)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def load(self, force: bool = False) -> bool:
        """Load the model. Logs, but never raises - status is reported instead."""
        with self._lock:
            loaded = self._predictor.load(force=force)

        if not loaded:
            logger.warning("ML model is NOT available: %s", self._predictor.load_error)
            return False

        if self.is_test_mode:
            if self._allow_test_mode:
                logger.warning(
                    "Running in TEST MODE with an UNTRAINED model. Predictions are not "
                    "real diagnoses; every API response is flagged with "
                    "is_validated_prediction=false. Train a model with ml/train.py."
                )
            else:
                logger.error(
                    "An untrained model was found but ALLOW_TEST_MODE_MODEL is false, "
                    "so predictions are disabled. Train a real model or set "
                    "ALLOW_TEST_MODE_MODEL=true for integration testing."
                )
        return True

    def reload(self) -> bool:
        logger.info("Reloading the ML model from disk ...")
        return self.load(force=True)

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def predictor(self) -> PlantDiseasePredictor:
        return self._predictor

    @property
    def is_loaded(self) -> bool:
        return self._predictor.is_loaded

    @property
    def is_test_mode(self) -> bool:
        """A model is loaded, but it has never been trained."""
        return self._predictor.is_loaded and not self._predictor.is_trained

    @property
    def can_predict(self) -> bool:
        if not self._predictor.is_loaded:
            return False
        return self._predictor.is_trained or self._allow_test_mode

    @property
    def confidence_threshold(self) -> float:
        return self._predictor.confidence_threshold

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    def status(self) -> Dict[str, Any]:
        """Model status for ``/api/health`` and the dashboard's mode banner."""
        status = self._predictor.status()
        status["allow_test_mode_model"] = self._allow_test_mode
        status["can_predict"] = self.can_predict

        if not status["loaded"]:
            status["message"] = (
                status.get("error")
                or "No model is loaded. Train one with ml/train.py, or create an "
                   "untrained test model with ml/create_test_model.py."
            )
        elif self.is_test_mode and not self._allow_test_mode:
            status["message"] = (
                "An untrained model is present but test mode is disabled, so "
                "predictions are refused. Train a real model to enable detection."
            )
        elif self.is_test_mode:
            status["message"] = (
                "TEST MODE: the loaded model is untrained. Its outputs are not valid "
                "diagnoses and exist only for end-to-end pipeline testing."
            )
        else:
            accuracy = (status.get("metrics") or {}).get("accuracy")
            status["message"] = (
                f"Trained model ready ({status['num_classes']} classes"
                + (f", test accuracy {float(accuracy) * 100:.2f}%" if accuracy else "")
                + ")."
            )
        return status

    def classes(self) -> Dict[str, Any]:
        """Supported plants/conditions plus reference text, for ``/api/classes``."""
        if not self._predictor.is_loaded:
            self.load()
        if not self._predictor.is_loaded:
            raise ModelUnavailableError(
                self._predictor.load_error
                or "No model is loaded, so the supported class list is unknown.",
                {"model_status": self.status()},
            )

        payload = self._predictor.classes()
        payload["reference_entries"] = sorted(all_known_classes().keys())
        payload["confidence_threshold"] = self.confidence_threshold
        return payload

    def evaluation_reports(self) -> Dict[str, Any]:
        """Training/evaluation artefacts for the Analytics page."""
        return read_training_reports(self._reports_dir)

    # ------------------------------------------------------------------ #
    # Inference
    # ------------------------------------------------------------------ #

    def _require_ready(self) -> None:
        if not self._predictor.is_loaded:
            self.load()

        if not self._predictor.is_loaded:
            raise ModelUnavailableError(
                "No trained model is available, so images cannot be classified.\n"
                "Fix it with one of:\n"
                "  1. python ml/train.py --dataset-dir ml/dataset   (train on PlantVillage)\n"
                "  2. python ml/create_test_model.py                (untrained model, test mode only)\n"
                f"Loader said: {self._predictor.load_error}",
                {"model_status": self.status()},
            )

        if self.is_test_mode and not self._allow_test_mode:
            raise ModelUnavailableError(
                "The only available model is untrained and ALLOW_TEST_MODE_MODEL is "
                "disabled, so this server will not return predictions that could be "
                "mistaken for real diagnoses. Train a model with ml/train.py.",
                {"model_status": self.status()},
            )

    def predict(
        self,
        image: ImageInput,
        confidence_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Classify one image.

        Raises :class:`ModelUnavailableError` when no usable model exists and
        :class:`ImageValidationError` when the bytes are not a decodable image.
        An inconclusive outcome is a normal successful result, not an error.
        """
        self._require_ready()

        try:
            result = self._predictor.predict(image, confidence_threshold=confidence_threshold)
        except ImageDecodeError as exc:
            raise ImageValidationError(f"The image could not be decoded: {exc}") from exc
        except ModelNotLoadedError as exc:
            raise ModelUnavailableError(str(exc), {"model_status": self.status()}) from exc

        result["model_mode"] = result.get("model", {}).get("mode", "unknown")
        return result


# --------------------------------------------------------------------------- #
# Module-level singleton
# --------------------------------------------------------------------------- #

_service: Optional[MLService] = None
_init_lock = threading.Lock()


def init_ml_service(config: Any, eager: bool = True) -> MLService:
    """Create the singleton. Called once from the application factory."""
    global _service
    with _init_lock:
        _service = MLService(config)
    if eager:
        _service.load()
    return _service


def get_ml_service() -> MLService:
    """Access the singleton; raises if the app factory never ran."""
    if _service is None:
        raise RuntimeError(
            "MLService has not been initialised. init_ml_service(config) must run "
            "inside create_app() before any request is handled."
        )
    return _service


__all__ = ["MLService", "init_ml_service", "get_ml_service"]
