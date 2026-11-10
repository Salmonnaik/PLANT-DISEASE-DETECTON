"""
utils/image_utils.py
====================
Upload validation and on-disk storage for leaf images.

Validation is deliberately layered, because a filename extension proves
nothing:

1. the part/field must actually be present,
2. the payload must be non-empty and within the size limit,
3. the magic bytes must identify a supported image format,
4. the bytes must decode into a real raster image.

Only after all four does anything get written to disk.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utils.errors import ImageValidationError

logger = logging.getLogger(__name__)

# Magic-byte signatures -> canonical extension.
MAGIC_SIGNATURES: Tuple[Tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"BM", "bmp"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")

# JPEG structural markers.
JPEG_SOI = b"\xff\xd8"          # Start Of Image
JPEG_EOI = b"\xff\xd9"          # End Of Image

# Smallest plausible JPEG from the ESP32-CAM. A frame grab that partially
# failed, or a Wi-Fi transfer cut short, typically yields a few hundred bytes
# that still begin with a valid SOI marker, so a size floor catches what the
# magic-byte check cannot.
MIN_JPEG_BYTES = 1024


def describe_jpeg_integrity(data: bytes) -> Dict[str, Any]:
    """
    Structural inspection of a JPEG payload.

    Pillow can decode a JPEG whose trailing scan data was truncated, filling
    the missing rows with grey, so "it decoded" is not proof the transfer
    completed. Checking for the End Of Image marker catches an interrupted
    ESP32-CAM upload that would otherwise be classified as a legitimate - but
    half-grey - image.
    """
    return {
        "has_soi": data[:2] == JPEG_SOI,
        # The EOI marker can be followed by padding bytes on some encoders, so
        # the tail is searched rather than compared exactly.
        "has_eoi": JPEG_EOI in data[-64:],
        "size_bytes": len(data),
        "meets_size_floor": len(data) >= MIN_JPEG_BYTES,
    }


def sniff_image_format(data: bytes) -> Optional[str]:
    """Identify an image format from its leading bytes, or None if unknown."""
    if len(data) < 12:
        return None
    for signature, extension in MAGIC_SIGNATURES:
        if data.startswith(signature):
            return extension
    # WebP: "RIFF" .... "WEBP"
    if data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def extension_of(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower().strip()


def is_allowed_extension(filename: Optional[str], allowed: Set[str]) -> bool:
    extension = extension_of(filename)
    if not extension:
        return False
    normalised = "jpg" if extension == "jpeg" else extension
    return normalised in {("jpg" if item == "jpeg" else item) for item in allowed}


def validate_image_bytes(
    data: bytes,
    allowed_extensions: Set[str],
    max_bytes: int,
    origin: str = "upload",
) -> Dict[str, Any]:
    """
    Validate raw image bytes. Returns metadata; raises :class:`ImageValidationError`.

    Decoding happens here (via ``ml.preprocessing``) so a truncated JPEG from a
    flaky Wi-Fi link is rejected with a clear message instead of blowing up
    later inside TensorFlow.
    """
    if not data:
        raise ImageValidationError(
            f"The {origin} contained no image data (0 bytes). "
            "If this came from the ESP32-CAM, the frame buffer was empty - retry the capture."
        )

    size = len(data)
    if size > max_bytes:
        raise ImageValidationError(
            f"Image is {size / (1024 * 1024):.2f} MB, which exceeds the "
            f"{max_bytes / (1024 * 1024):.0f} MB limit.",
            {"size_bytes": size, "max_bytes": max_bytes},
        )

    sniffed = sniff_image_format(data)
    if sniffed is None:
        raise ImageValidationError(
            "The uploaded file is not a recognised image. Supported formats: "
            + ", ".join(sorted(allowed_extensions))
            + ".",
            {"first_bytes_hex": data[:8].hex()},
        )

    allowed_normalised = {("jpg" if item == "jpeg" else item) for item in allowed_extensions}
    if sniffed not in allowed_normalised:
        raise ImageValidationError(
            f"Image format '{sniffed}' is not accepted. Supported formats: "
            + ", ".join(sorted(allowed_extensions))
            + ".",
            {"detected_format": sniffed},
        )

    # JPEG structural check. Only applied to JPEG because PNG/BMP/WebP
    # truncation is reliably caught by the decoder below.
    integrity: Dict[str, Any] = {}
    if sniffed == "jpg":
        integrity = describe_jpeg_integrity(data)

        if not integrity["meets_size_floor"]:
            raise ImageValidationError(
                f"The {origin} produced only {size} bytes, which is too small to be a "
                f"real photograph (minimum {MIN_JPEG_BYTES} bytes). The camera's frame "
                "grab most likely failed part-way - retry the capture.",
                {"integrity": integrity},
            )

        if not integrity["has_eoi"]:
            raise ImageValidationError(
                f"The JPEG from the {origin} is truncated: its End Of Image marker is "
                "missing, so the transfer was cut short. On the ESP32-CAM this usually "
                "means a weak Wi-Fi signal or a brown-out during the upload - reduce the "
                "frame size and check the 5V supply.",
                {"integrity": integrity},
            )

    # Final gate: it must actually decode.
    try:
        from utils.ml_bridge import decode_image_bytes  # noqa: PLC0415

        array = decode_image_bytes(data)
    except Exception as exc:  # noqa: BLE001
        raise ImageValidationError(
            f"The image could not be decoded: {exc}", {"detected_format": sniffed}
        ) from exc

    height, width = int(array.shape[0]), int(array.shape[1])
    if width < 16 or height < 16:
        raise ImageValidationError(
            f"Image is only {width}x{height} pixels, which is far too small to classify.",
            {"width": width, "height": height},
        )

    return {
        "size_bytes": size,
        "format": sniffed,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(data).hexdigest(),
        "integrity": integrity or None,
    }


def read_uploaded_file(
    file_storage: FileStorage,
    allowed_extensions: Set[str],
    max_bytes: int,
) -> Tuple[bytes, Dict[str, Any]]:
    """Read and validate a multipart file part."""
    if file_storage is None or not file_storage.filename:
        raise ImageValidationError(
            "No file was selected. Attach an image under the form field named 'image'."
        )

    if not is_allowed_extension(file_storage.filename, allowed_extensions):
        raise ImageValidationError(
            f"'{file_storage.filename}' has an unsupported extension. Allowed: "
            + ", ".join(sorted(allowed_extensions))
            + ".",
            {"filename": file_storage.filename},
        )

    data = file_storage.read()
    metadata = validate_image_bytes(data, allowed_extensions, max_bytes, origin="upload")
    metadata["original_filename"] = secure_filename(file_storage.filename)
    metadata["content_type"] = file_storage.mimetype
    return data, metadata


def build_filename(prefix: str, extension: str, original: Optional[str] = None) -> str:
    """
    Timestamped, collision-proof filename.

    ``esp32cam_20261110-141503_7f3a9c.jpg`` - sortable, shows the source, and the
    random suffix keeps two captures in the same second from colliding.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    token = secrets.token_hex(3)
    safe_prefix = SAFE_NAME_PATTERN.sub("", prefix) or "image"
    extension = (extension or "jpg").lower().lstrip(".")
    if extension == "jpeg":
        extension = "jpg"

    name = f"{safe_prefix}_{stamp}_{token}"
    if original:
        stem = SAFE_NAME_PATTERN.sub("-", Path(secure_filename(original)).stem)[:32].strip("-")
        if stem:
            name = f"{name}_{stem}"
    return f"{name}.{extension}"


def save_image(
    data: bytes,
    upload_folder: Path,
    prefix: str = "upload",
    extension: str = "jpg",
    original_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write bytes under ``upload_folder/YYYY/MM/`` and return path information.

    The year/month sub-folders keep the directory listable after months of
    captures. ``relative_path`` (POSIX separators) is what goes into the
    database and into the ``/uploads/...`` URL.
    """
    now = datetime.now(timezone.utc)
    sub_directory = Path(f"{now:%Y}") / f"{now:%m}"
    target_directory = Path(upload_folder) / sub_directory
    target_directory.mkdir(parents=True, exist_ok=True)

    filename = build_filename(prefix, extension, original_filename)
    absolute_path = target_directory / filename
    absolute_path.write_bytes(data)

    relative_path = (sub_directory / filename).as_posix()
    logger.debug("Saved %d bytes to %s", len(data), absolute_path)

    return {
        "absolute_path": str(absolute_path),
        "relative_path": relative_path,
        "filename": filename,
        "url": f"/uploads/{relative_path}",
        "size_bytes": len(data),
    }


def delete_image(upload_folder: Path, relative_path: Optional[str]) -> bool:
    """
    Delete a stored image, refusing to escape ``upload_folder``.

    Without the containment check a crafted ``image_path`` such as
    ``../../config.py`` could delete project files when a history row is removed.
    """
    if not relative_path:
        return False

    root = Path(upload_folder).resolve()
    candidate = (root / relative_path).resolve()

    if not str(candidate).startswith(str(root) + os.sep) and candidate != root:
        logger.warning("Refusing to delete '%s': outside the upload folder.", relative_path)
        return False

    if not candidate.is_file():
        return False

    try:
        candidate.unlink()
        return True
    except OSError as exc:  # pragma: no cover
        logger.warning("Could not delete %s: %s", candidate, exc)
        return False


def directory_usage(upload_folder: Path) -> Dict[str, Any]:
    """Image count and total size, reported on the device/health pages."""
    root = Path(upload_folder)
    if not root.is_dir():
        return {"files": 0, "total_bytes": 0, "total_mb": 0.0}

    files = 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            files += 1
            total += item.stat().st_size
    return {"files": files, "total_bytes": total, "total_mb": round(total / (1024 * 1024), 2)}


__all__ = [
    "MAGIC_SIGNATURES",
    "MIN_JPEG_BYTES",
    "describe_jpeg_integrity",
    "sniff_image_format",
    "extension_of",
    "is_allowed_extension",
    "validate_image_bytes",
    "read_uploaded_file",
    "build_filename",
    "save_image",
    "delete_image",
    "directory_usage",
]
