"""
model_builder.py
================
Builds the MobileNetV2 transfer-learning classifier used by the project.

Architecture
------------
    Input (224, 224, 3)  float32 RGB, 0..255
      -> Rescaling(1/127.5, offset=-1)        # MobileNetV2's expected range
      -> MobileNetV2 base (ImageNet weights, include_top=False)
      -> GlobalAveragePooling2D
      -> Dropout
      -> Dense(num_classes, softmax)

Why MobileNetV2: it reaches high accuracy on PlantVillage with ~2.3M
parameters, trains on a CPU-only laptop in a reasonable time, and is small
enough that a single Flask worker can hold it in memory while serving.

Keeping the ``Rescaling`` layer *inside* the model means every consumer
(``predict.py``, the Flask service, a future TFLite export) gets identical
normalisation for free.
"""

from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

logger = logging.getLogger(__name__)

BASE_MODEL_NAME = "MobileNetV2"
DEFAULT_IMAGE_SIZE: Tuple[int, int] = (224, 224)


def _keras():
    try:
        import tensorflow as tf  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "TensorFlow is required to build the model. "
            "Install it with: pip install -r backend/requirements.txt"
        ) from exc
    return tf, tf.keras


def load_base_model(
    image_size: Sequence[int] = DEFAULT_IMAGE_SIZE,
    weights: str | None = "imagenet",
):
    """
    Instantiate the MobileNetV2 feature extractor.

    ImageNet weights are downloaded once (~9 MB) to ``~/.keras/models``. If the
    machine is offline the function degrades to randomly initialised weights and
    says so loudly, because a model trained from scratch on a small dataset will
    perform far worse.
    """
    _, keras = _keras()
    input_shape = (int(image_size[0]), int(image_size[1]), 3)

    try:
        base = keras.applications.MobileNetV2(
            input_shape=input_shape,
            include_top=False,
            weights=weights,
        )
        if weights == "imagenet":
            logger.info("Loaded MobileNetV2 with ImageNet weights.")
        return base
    except Exception as exc:  # network failure while fetching weights
        if weights is None:
            raise
        logger.warning(
            "Could not load ImageNet weights (%s). Falling back to random "
            "initialisation - transfer learning is disabled and accuracy will "
            "be much lower. Connect to the internet once to cache the weights.",
            exc,
        )
        return keras.applications.MobileNetV2(
            input_shape=input_shape,
            include_top=False,
            weights=None,
        )


def build_model(
    num_classes: int,
    image_size: Sequence[int] = DEFAULT_IMAGE_SIZE,
    dropout: float = 0.3,
    weights: str | None = "imagenet",
    base_trainable: bool = False,
):
    """Create the full classifier with the convolutional base frozen."""
    if num_classes < 2:
        raise ValueError(f"num_classes must be >= 2, got {num_classes}.")

    _, keras = _keras()
    layers = keras.layers

    base = load_base_model(image_size=image_size, weights=weights)
    base.trainable = base_trainable

    inputs = layers.Input(shape=(int(image_size[0]), int(image_size[1]), 3), name="leaf_image")
    x = layers.Rescaling(1.0 / 127.5, offset=-1.0, name="rescaling")(inputs)
    # training=False keeps the base's BatchNormalization statistics frozen,
    # which is required when the base is not being trained.
    x = base(x, training=False)
    x = layers.GlobalAveragePooling2D(name="global_pool")(x)
    x = layers.Dropout(dropout, name="head_dropout")(x)
    outputs = layers.Dense(num_classes, activation="softmax", name="predictions")(x)

    model = keras.Model(inputs, outputs, name="plant_disease_mobilenetv2")
    model.base_model_name = BASE_MODEL_NAME  # type: ignore[attr-defined]
    return model


def compile_model(model, learning_rate: float = 1e-3, label_smoothing: float = 0.0):
    """Compile with Adam + categorical cross-entropy and top-k accuracy."""
    _, keras = _keras()
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss=keras.losses.CategoricalCrossentropy(label_smoothing=label_smoothing),
        metrics=[
            keras.metrics.CategoricalAccuracy(name="accuracy"),
            keras.metrics.TopKCategoricalAccuracy(k=3, name="top3_accuracy"),
        ],
    )
    return model


def find_base_model(model):
    """Return the nested MobileNetV2 sub-model inside a built classifier."""
    for layer in model.layers:
        if layer.name.lower().startswith("mobilenet"):
            return layer
    raise ValueError("No MobileNetV2 base layer found in this model.")


def unfreeze_top_layers(model, num_layers: int = 40) -> int:
    """
    Unfreeze the last ``num_layers`` convolutional blocks for fine-tuning.

    BatchNormalization layers stay frozen on purpose: updating their running
    statistics with small batches destabilises fine-tuning and is the most
    common cause of a sudden accuracy collapse at the start of stage two.

    Returns the number of layers made trainable.
    """
    base = find_base_model(model)
    base.trainable = True

    total = len(base.layers)
    cutoff = max(0, total - int(num_layers))
    unfrozen = 0

    for index, layer in enumerate(base.layers):
        if index < cutoff:
            layer.trainable = False
            continue
        if layer.__class__.__name__ == "BatchNormalization":
            layer.trainable = False
            continue
        layer.trainable = True
        unfrozen += 1

    logger.info(
        "Fine-tuning enabled: %d of %d base layers trainable (BatchNorm kept frozen).",
        unfrozen,
        total,
    )
    return unfrozen


def model_summary_lines(model) -> List[str]:
    """Capture ``model.summary()`` as a list of strings (for report files)."""
    lines: List[str] = []
    model.summary(print_fn=lines.append)
    return lines


def count_parameters(model) -> dict:
    """Trainable / non-trainable parameter counts."""
    import numpy as np  # noqa: PLC0415

    trainable = int(sum(np.prod(v.shape) for v in model.trainable_weights))
    non_trainable = int(sum(np.prod(v.shape) for v in model.non_trainable_weights))
    return {
        "trainable": trainable,
        "non_trainable": non_trainable,
        "total": trainable + non_trainable,
    }


__all__ = [
    "BASE_MODEL_NAME",
    "DEFAULT_IMAGE_SIZE",
    "build_model",
    "compile_model",
    "load_base_model",
    "find_base_model",
    "unfreeze_top_layers",
    "model_summary_lines",
    "count_parameters",
]
