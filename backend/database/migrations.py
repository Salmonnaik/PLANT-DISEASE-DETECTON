"""
migrations.py
=============
Forward-only, idempotent schema migrations for existing databases.

Why this exists
---------------
``schema.sql`` is written with ``CREATE TABLE IF NOT EXISTS``, which is fine for
a fresh install but does nothing for a database that already holds detection
records: a column added to ``schema.sql`` never appears in an existing file.
These migrations close that gap without touching the stored rows.

Rules followed here
-------------------
* **Additive only.** Columns are added, never dropped or retyped, so an older
  build of the backend keeps working against a migrated database.
* **Idempotent.** Every step checks the current state first, so running it twice
  is harmless. Applied versions are also recorded in ``schema_migrations``.
* **Non-destructive.** No migration deletes or rewrites a user's detection
  history; backfills only populate columns that are NULL.

SQLite's ``ALTER TABLE`` cannot add a CHECK constraint to an existing table, so
``camera_source`` is validated in Python (``models/detection.py``) rather than
by the database. Rebuilding the table to add the constraint would mean copying
every row, which is a far worse trade for a value we control at one insert site.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Camera sources recorded in detection_history.camera_source.
#   laptop_webcam - captured in the browser from the laptop/USB webcam
#   esp32_cam     - captured by the ESP32-CAM module
#   file_upload   - an existing image file uploaded by the operator
CAMERA_SOURCE_WEBCAM = "laptop_webcam"
CAMERA_SOURCE_ESP32 = "esp32_cam"
CAMERA_SOURCE_FILE = "file_upload"
CAMERA_SOURCE_UNKNOWN = "unknown"

VALID_CAMERA_SOURCES = (
    CAMERA_SOURCE_WEBCAM,
    CAMERA_SOURCE_ESP32,
    CAMERA_SOURCE_FILE,
    CAMERA_SOURCE_UNKNOWN,
)


# --------------------------------------------------------------------------- #
# Introspection helpers
# --------------------------------------------------------------------------- #

def table_columns(connection: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
    except sqlite3.Error:
        return []


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return column in table_columns(connection, table)


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT    NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
        )
        """
    )


def applied_versions(connection: sqlite3.Connection) -> List[int]:
    _ensure_migration_table(connection)
    return [
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    ]


# --------------------------------------------------------------------------- #
# Migration 001 - camera_source on detection_history
# --------------------------------------------------------------------------- #

def _migration_001_camera_source(connection: sqlite3.Connection) -> str:
    """
    Add ``detection_history.camera_source`` and backfill it from ``source``.

    The pre-existing ``source`` column only distinguished ``upload`` from
    ``esp32cam``. With a laptop webcam added, "upload" becomes ambiguous: it
    could be a webcam frame posted from the browser or a file picked from disk.
    ``camera_source`` records which, while ``source`` is left untouched so
    nothing that already reads it breaks.
    """
    if not table_exists(connection, "detection_history"):
        return "detection_history does not exist yet; nothing to migrate."

    notes: List[str] = []

    if not column_exists(connection, "detection_history", "camera_source"):
        connection.execute("ALTER TABLE detection_history ADD COLUMN camera_source TEXT")
        notes.append("added column camera_source")
    else:
        notes.append("column camera_source already present")

    # Backfill only NULL rows. Historic 'upload' rows predate webcam support,
    # so they can only have been file uploads.
    cursor = connection.execute(
        """
        UPDATE detection_history
           SET camera_source = CASE
                 WHEN source = 'esp32cam' THEN ?
                 WHEN source = 'upload'   THEN ?
                 ELSE ?
               END
         WHERE camera_source IS NULL OR camera_source = ''
        """,
        (CAMERA_SOURCE_ESP32, CAMERA_SOURCE_FILE, CAMERA_SOURCE_UNKNOWN),
    )
    if cursor.rowcount and cursor.rowcount > 0:
        notes.append(f"backfilled {cursor.rowcount} existing row(s)")

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_camera_source "
        "ON detection_history (camera_source)"
    )
    notes.append("index idx_detection_camera_source ensured")

    return "; ".join(notes)


# --------------------------------------------------------------------------- #
# Migration 002 - app_settings key/value store
# --------------------------------------------------------------------------- #

def _migration_002_app_settings(connection: sqlite3.Connection) -> str:
    """
    Add ``app_settings`` so runtime configuration can be changed from the UI.

    Needed for the Camera Management page: the ESP32-CAM's IP address must be
    editable from the dashboard and survive a backend restart. Putting it in the
    database rather than rewriting ``.env`` keeps the file the user owns under
    their control, and keeps the setting per-database.
    """
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
        )
        """
    )
    return "app_settings table ensured"


# --------------------------------------------------------------------------- #
# Migration 003 - device_status camera capability columns
# --------------------------------------------------------------------------- #

def _migration_003_device_columns(connection: sqlite3.Connection) -> str:
    """
    Add ``frame_size`` and ``psram_found`` to ``device_status``.

    The firmware already reports both; recording them lets the Device page
    explain a low-resolution capture (no PSRAM forces a smaller frame) instead
    of leaving the user guessing.
    """
    if not table_exists(connection, "device_status"):
        return "device_status does not exist yet; nothing to migrate."

    added: List[str] = []
    for column, definition in (
        ("frame_size", "TEXT"),
        ("psram_found", "INTEGER"),
    ):
        if not column_exists(connection, "device_status", column):
            connection.execute(f"ALTER TABLE device_status ADD COLUMN {column} {definition}")
            added.append(column)

    return f"added columns: {', '.join(added)}" if added else "columns already present"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

MigrationFn = Callable[[sqlite3.Connection], str]

def _migration_004_universal_analysis(connection: sqlite3.Connection) -> str:
    """
    Add columns for the universal (species-agnostic) analysis.

    These let a detection record describe a plant the classifier was never
    trained on. ``plant_species`` holds the identified or declared species,
    ``species_source`` records how we know it (so a user's declaration is never
    confused with a model's identification), and ``analysis`` stores the full
    report as JSON for the result page.

    ``plant_name`` is left as-is for backward compatibility; existing readers
    keep working and existing rows are untouched.
    """
    if not table_exists(connection, "detection_history"):
        return "detection_history does not exist yet; nothing to migrate."

    added: List[str] = []
    for column, definition in (
        ("plant_species", "TEXT"),
        # user_declared | ai_vision_api | trained_classifier | unidentified
        ("species_source", "TEXT"),
        # classifier | universal
        ("analysis_mode", "TEXT"),
        # confident | probable | possible | insufficient
        ("confidence_level", "TEXT"),
        # JSON: the full universal analysis report
        ("analysis", "TEXT"),
        # JSON: the measured symptom list, duplicated for cheap querying
        ("symptoms", "TEXT"),
    ):
        if not column_exists(connection, "detection_history", column):
            connection.execute(
                f"ALTER TABLE detection_history ADD COLUMN {column} {definition}"
            )
            added.append(column)

    # Existing rows came from the classifier path by definition.
    cursor = connection.execute(
        "UPDATE detection_history SET analysis_mode = 'classifier' WHERE analysis_mode IS NULL"
    )
    backfilled = cursor.rowcount or 0

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_plant_species "
        "ON detection_history (plant_species)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_detection_analysis_mode "
        "ON detection_history (analysis_mode)"
    )

    parts = []
    if added:
        parts.append(f"added columns: {', '.join(added)}")
    else:
        parts.append("columns already present")
    if backfilled:
        parts.append(f"backfilled analysis_mode on {backfilled} existing row(s)")
    parts.append("indexes ensured")
    return "; ".join(parts)


MIGRATIONS: Tuple[Tuple[int, str, MigrationFn], ...] = (
    (1, "add_camera_source_to_detection_history", _migration_001_camera_source),
    (2, "add_app_settings_table", _migration_002_app_settings),
    (3, "add_device_camera_columns", _migration_003_device_columns),
    (4, "add_universal_analysis_columns", _migration_004_universal_analysis),
)


def run_migrations(connection: sqlite3.Connection) -> Dict[str, object]:
    """
    Apply every pending migration inside a single transaction per step.

    Returns a report describing what ran, which is logged at startup so an
    upgrade is visible in the console rather than silent.
    """
    _ensure_migration_table(connection)
    already = set(applied_versions(connection))

    applied: List[Dict[str, object]] = []
    skipped: List[int] = []

    for version, name, migrate in MIGRATIONS:
        if version in already:
            skipped.append(version)
            continue

        logger.info("Applying migration %03d: %s", version, name)
        try:
            detail = migrate(connection)
            connection.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            logger.error("Migration %03d (%s) FAILED: %s", version, name, exc)
            raise

        logger.info("Migration %03d applied: %s", version, detail)
        applied.append({"version": version, "name": name, "detail": detail})

    return {
        "applied": applied,
        "skipped_versions": skipped,
        "current_version": max([version for version, _, _ in MIGRATIONS], default=0),
    }


__all__ = [
    "CAMERA_SOURCE_WEBCAM",
    "CAMERA_SOURCE_ESP32",
    "CAMERA_SOURCE_FILE",
    "CAMERA_SOURCE_UNKNOWN",
    "VALID_CAMERA_SOURCES",
    "MIGRATIONS",
    "run_migrations",
    "applied_versions",
    "column_exists",
    "table_columns",
    "table_exists",
]
