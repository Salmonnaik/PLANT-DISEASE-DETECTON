# Database Schema and Migrations

SQLite, two main tables plus two supporting ones. Migrations run automatically
on every backend start and are safe on a database that already holds records.

---

## 1. Why migrations exist here

`schema.sql` uses `CREATE TABLE IF NOT EXISTS`. That is correct for a fresh
install but does nothing for a database that already has detection records: a
column added to `schema.sql` never appears in an existing file, because the
`CREATE TABLE` is skipped entirely.

`backend/database/migrations.py` closes that gap. Three rules it follows:

* **Additive only.** Columns are added, never dropped or retyped, so an older
  build of the backend keeps working against a migrated database.
* **Idempotent.** Each step inspects the current state first, and applied
  versions are recorded in `schema_migrations`. Running twice is harmless.
* **Non-destructive.** No migration deletes or rewrites history. Backfills only
  populate columns that are NULL.

Order on startup: `schema.sql` first (so a fresh database gets every table),
then migrations (so an existing database reaches the same shape).

---

## 2. Applied migrations

| Version | Name | Effect |
|---|---|---|
| 001 | `add_camera_source_to_detection_history` | Adds `camera_source`, backfills it from `source`, creates its index |
| 002 | `add_app_settings_table` | Creates `app_settings` for dashboard-editable runtime settings |
| 003 | `add_device_camera_columns` | Adds `frame_size` and `psram_found` to `device_status` |

### Migration 001 in detail

Before webcam support, `source` had two values: `upload` and `esp32cam`. Adding
a laptop webcam made `upload` ambiguous - it could now mean a browser webcam
frame *or* a file picked from disk. Rather than redefine an existing column
(which would silently change the meaning of stored rows), a new `camera_source`
column records the finer distinction and `source` is left untouched.

Backfill mapping, applied only to rows where `camera_source` is NULL:

| Existing `source` | Backfilled `camera_source` | Reasoning |
|---|---|---|
| `esp32cam` | `esp32_cam` | Unambiguous |
| `upload` | `file_upload` | These rows predate webcam support, so they can only have been file uploads |
| anything else | `unknown` | Never guess |

Verified behaviour on an existing database:

```
rows before          : [1, 4, 7]
camera_source before : False
Migration 001 applied: added column camera_source;
                       backfilled 3 existing row(s);
                       index idx_detection_camera_source ensured
rows after           : [1, 4, 7]
backfilled values    : [(1, 'upload',   'file_upload'),
                        (4, 'esp32cam', 'esp32_cam'),
                        (7, 'upload',   'file_upload')]
RECORDS PRESERVED    : True
```

### A constraint worth knowing

SQLite cannot add a `CHECK` constraint with `ALTER TABLE`. `camera_source` is
therefore validated in Python (`models/detection.py::normalise_camera_source`),
not by the database. Rebuilding the table to add the constraint would mean
copying every row - a poor trade for a value written at a single insert site.

The same function normalises aliases (`webcam`, `esp32cam`, `esp32-cam`) and
maps anything unrecognised to `unknown` with a warning, so a malformed client
value cannot become an unqueryable string in the column.

---

## 3. `detection_history`

One row per prediction the model produced - including inconclusive ones.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Autoincrement |
| `image_path` | TEXT | Relative to `backend/uploads/`, e.g. `2026/11/webcam_...jpg` |
| `plant_name` | TEXT | e.g. `Tomato` |
| `predicted_disease` | TEXT | e.g. `Early Blight` |
| `confidence` | REAL | 0.0-1.0 softmax probability, `CHECK`-constrained |
| `detection_status` | TEXT | `healthy` / `diseased` / `uncertain` / `unknown` |
| **`camera_source`** | TEXT | `laptop_webcam` / `esp32_cam` / `file_upload` / `unknown` |
| `created_at` | TEXT | UTC, `YYYY-MM-DD HH:MM:SS` |
| `predicted_class` | TEXT | Raw dataset label, e.g. `Tomato___Early_blight` |
| `source` | TEXT | Transport: `upload` / `esp32cam` |
| `device_name` | TEXT | Which camera reported it |
| `image_filename` | TEXT | |
| `image_size_bytes` | INTEGER | |
| `model_mode` | TEXT | `trained` / `test` |
| `is_validated` | INTEGER | 0 for any result from an untrained model |
| `is_conclusive` | INTEGER | 0 for uncertain/unknown |
| `confidence_threshold` | REAL | Threshold in force for this prediction |
| `inference_ms` | REAL | |
| `probabilities` | TEXT | JSON array of the top classes |
| `image_quality` | TEXT | JSON of the quality metrics |
| `notes` | TEXT | Reason, when inconclusive |

Indexes: `created_at DESC`, `detection_status`, `plant_name`, `source`,
`is_validated`, `camera_source`.

### Why inconclusive rows are stored

"The system could not decide" is information the operator needs. Dropping those
rows would make the dashboard look more confident than the system actually is,
and would hide a camera that is persistently producing unusable frames.

---

## 4. `device_status`

One row per ESP32-CAM, updated by firmware heartbeats.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `device_name` | TEXT UNIQUE | Matches `DEVICE_NAME` in the sketch |
| `ip_address` | TEXT | Last reported address |
| `connection_status` | TEXT | `online` / `offline` / `error` |
| `last_seen` | TEXT | Last heartbeat, UTC |
| `mac_address` | TEXT | |
| `wifi_ssid` | TEXT | |
| `wifi_rssi` | INTEGER | dBm |
| `firmware_version` | TEXT | |
| `camera_model` | TEXT | |
| `led_state` | TEXT | `on` / `off` |
| `free_heap` | INTEGER | Bytes |
| `uptime_seconds` | INTEGER | |
| **`frame_size`** | TEXT | e.g. `SVGA (800x600)` |
| **`psram_found`** | INTEGER | 1 when PSRAM is available |
| `last_capture_at` | TEXT | |
| `total_captures` | INTEGER | |
| `last_error` | TEXT | |
| `created_at` / `updated_at` | TEXT | `updated_at` maintained by a trigger |

### Online state is derived, not trusted

A board that loses power cannot report its own death, so a stored "online" flag
would stay wrong indefinitely. `to_api_dict()` computes liveness from the age of
`last_seen` against `ESP32_OFFLINE_AFTER_SECONDS` (45s default). The stored
column is still updated so that a plain `SELECT` in a DB browser matches what
the dashboard shows.

`frame_size` and `psram_found` are recorded because they explain a
low-resolution capture: a board without PSRAM is forced to a smaller frame, and
without that telemetry the cause is invisible from the dashboard.

---

## 5. `app_settings`

Key/value store for configuration the dashboard can change at runtime.

| Column | Type |
|---|---|
| `key` | TEXT PK |
| `value` | TEXT |
| `updated_at` | TEXT |

Current keys:

| Key | Purpose |
|---|---|
| `esp32_cam_ip` | Camera address entered on the Camera Management page |

Stored in the database rather than by rewriting `.env` for two reasons: the
configuration file the user owns stays under their control, and the value takes
effect immediately without a restart. The resolution order is documented in
[`camera_sources.md`](camera_sources.md#configuring-the-address).

---

## 6. `schema_migrations`

| Column | Type |
|---|---|
| `version` | INTEGER PK |
| `name` | TEXT |
| `applied_at` | TEXT |

---

## 7. Operations

```bash
# Create or verify the schema (also happens on every backend start)
python backend/database/init_db.py

# Inspect tables, columns and row counts
python backend/database/init_db.py --show

# DESTRUCTIVE: drop every table and recreate. Prompts for confirmation.
python backend/database/init_db.py --reset
```

### Timestamps

All `*_at` columns store UTC in SQLite's canonical `YYYY-MM-DD HH:MM:SS` form.
That is what makes `date(created_at)` and `datetime(created_at, 'localtime')`
work in the analytics queries. The API converts them to ISO-8601 with a `Z`
suffix, and the browser renders local time.

### Backups

The database is a single file. To back it up while the backend is running, use
SQLite's own backup rather than copying the file, because WAL journalling means
a plain copy can miss committed data:

```bash
sqlite3 backend/database/plant_disease.db ".backup 'backup.db'"
```

Stored images live separately under `backend/uploads/` and are referenced by
`image_path`. Back both up together, or the history will show missing
thumbnails.

### Adding a migration

1. Write the function in `migrations.py`, checking current state first.
2. Append it to the `MIGRATIONS` tuple with the next version number.
3. Mirror the change in `schema.sql` so fresh installs get it directly.
4. Do not add an index in `schema.sql` on a column that only a migration
   creates - `schema.sql` runs first, and indexing a missing column fails. Let
   the migration create the column and its index together.
