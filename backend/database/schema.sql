-- ---------------------------------------------------------------------------
-- Plant Disease Detection - SQLite schema
--
-- Timestamp convention: every *_at column stores UTC in SQLite's canonical
-- 'YYYY-MM-DD HH:MM:SS' form. That is what lets date(created_at) and
-- datetime(created_at, 'localtime') work in the analytics queries. The API
-- layer converts these to ISO-8601 with a 'Z' suffix before sending them to
-- the browser, which then renders them in the user's local timezone.
-- ---------------------------------------------------------------------------

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- detection_history: one row per prediction the model produced.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detection_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Required by the project specification -------------------------------
    image_path          TEXT    NOT NULL,              -- path relative to backend/uploads
    plant_name          TEXT    NOT NULL,              -- e.g. 'Tomato'
    predicted_disease   TEXT    NOT NULL,              -- e.g. 'Early Blight'
    confidence          REAL    NOT NULL,              -- 0.0 - 1.0 softmax probability
    detection_status    TEXT    NOT NULL,              -- healthy | diseased | uncertain | unknown
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),

    -- Provenance ----------------------------------------------------------
    predicted_class     TEXT,                          -- raw dataset label, e.g. 'Tomato___Early_blight'
    source              TEXT    NOT NULL DEFAULT 'upload',  -- upload | esp32cam (transport)
    -- Which physical camera produced the image:
    --   laptop_webcam | esp32_cam | file_upload | unknown
    -- Kept separate from `source` because an HTTP upload can now be either a
    -- browser webcam frame or a file picked from disk. Validated in Python
    -- (models/detection.py): SQLite cannot add a CHECK via ALTER TABLE, and
    -- existing databases get this column through migration 001.
    camera_source       TEXT    NOT NULL DEFAULT 'file_upload',
    device_name         TEXT,                          -- which camera produced the image
    image_filename      TEXT,
    image_size_bytes    INTEGER,

    -- Model accountability ------------------------------------------------
    -- model_mode is 'trained' for a real model and 'test' for the explicitly
    -- untrained bootstrap model. is_validated is 0 for any row that did not
    -- come from a genuinely trained model, so analytics can exclude them.
    model_mode          TEXT    NOT NULL DEFAULT 'trained',
    is_validated        INTEGER NOT NULL DEFAULT 1,
    is_conclusive       INTEGER NOT NULL DEFAULT 1,
    confidence_threshold REAL,
    inference_ms        REAL,

    -- Universal (species-agnostic) analysis -------------------------------
    -- Lets a record describe a plant the classifier was never trained on.
    -- Added to existing databases by migration 004.
    plant_species       TEXT,                          -- identified or declared species
    species_source      TEXT,                          -- user_declared | ai_vision_api | trained_classifier | unidentified
    analysis_mode       TEXT DEFAULT 'classifier',     -- classifier | universal
    confidence_level    TEXT,                          -- confident | probable | possible | insufficient
    analysis            TEXT,                          -- JSON: the full universal report
    symptoms            TEXT,                          -- JSON: measured symptom list

    -- Full detail for the result page -------------------------------------
    probabilities       TEXT,                          -- JSON array of {class, probability}
    image_quality       TEXT,                          -- JSON object of quality metrics
    notes               TEXT,

    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CHECK (detection_status IN ('healthy', 'diseased', 'uncertain', 'unknown')),
    CHECK (source IN ('upload', 'esp32cam')),
    CHECK (model_mode IN ('trained', 'test'))
);

CREATE INDEX IF NOT EXISTS idx_detection_created_at  ON detection_history (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_detection_status      ON detection_history (detection_status);
CREATE INDEX IF NOT EXISTS idx_detection_plant       ON detection_history (plant_name);
CREATE INDEX IF NOT EXISTS idx_detection_source      ON detection_history (source);
CREATE INDEX IF NOT EXISTS idx_detection_validated   ON detection_history (is_validated);

-- The index on camera_source is created by migration 001, not here. On a
-- database that predates the column, CREATE TABLE IF NOT EXISTS above is a
-- no-op, so the column does not exist yet when this script runs and indexing
-- it would fail. The migration adds the column and its index together.


-- ---------------------------------------------------------------------------
-- device_status: one row per ESP32-CAM, updated by firmware heartbeats.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_status (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Required by the project specification -------------------------------
    device_name         TEXT    NOT NULL UNIQUE,
    ip_address          TEXT,
    connection_status   TEXT    NOT NULL DEFAULT 'offline',  -- online | offline | error
    last_seen           TEXT,

    -- Device telemetry ----------------------------------------------------
    mac_address         TEXT,
    wifi_ssid           TEXT,
    wifi_rssi           INTEGER,                       -- dBm
    firmware_version    TEXT,
    camera_model        TEXT,
    led_state           TEXT    NOT NULL DEFAULT 'off', -- on | off
    free_heap           INTEGER,
    uptime_seconds      INTEGER,
    frame_size          TEXT,                          -- e.g. 'SVGA' (800x600)
    psram_found         INTEGER,                       -- 1 when PSRAM is available

    -- Capture bookkeeping -------------------------------------------------
    last_capture_at     TEXT,
    total_captures      INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,

    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),

    CHECK (connection_status IN ('online', 'offline', 'error')),
    CHECK (led_state IN ('on', 'off'))
);

CREATE INDEX IF NOT EXISTS idx_device_name      ON device_status (device_name);
CREATE INDEX IF NOT EXISTS idx_device_last_seen ON device_status (last_seen DESC);


-- ---------------------------------------------------------------------------
-- Keep updated_at honest without application code having to remember.
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_device_status_updated_at
AFTER UPDATE ON device_status
FOR EACH ROW
BEGIN
    UPDATE device_status
       SET updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now')
     WHERE id = OLD.id;
END;


-- ---------------------------------------------------------------------------
-- app_settings: runtime configuration editable from the dashboard.
--
-- Currently holds the ESP32-CAM IP address entered on the Camera Management
-- page. Stored here rather than by rewriting .env so the file the user owns
-- stays under their control, and so the setting survives a restart.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);


-- ---------------------------------------------------------------------------
-- schema_migrations: applied migration versions (see database/migrations.py).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);
