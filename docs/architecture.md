# System Architecture

---

## 1. Overview

Four layers, each independently runnable and testable: train the model without
the hardware, run the API without the dashboard, develop the dashboard against
the API.

```
 ACQUISITION                TRANSPORT            PROCESSING             PRESENTATION
 ===========                =========            ==========             ============

 +-------------------+
 |  Laptop webcam    |
 |  MediaDevices API |---- multipart HTTP ---+
 |  + HTML canvas    |                       |
 +-------------------+                       |
                                             |    +------------------+
 +-------------------+                       +--->|  Flask REST API  |
 |  ESP32-CAM        |                       |    |                  |
 |  OV2640 + LED     |---- raw JPEG HTTP ----+    |  validation      |
 |  (GPIO 4)         |      over Wi-Fi            |  orchestration   |
 +-------------------+                            |  error handling  |
                                                  +---+----------+---+
 +-------------------+                                |          |
 |  Image file       |---- multipart HTTP ------------+          |
 +-------------------+                                           |
                                      +--------------------------+------+
                                      |                                 |
                              +-------v---------+              +--------v--------+
                              |  MobileNetV2    |              |  SQLite         |
                              |  224x224 input  |              |  detection_     |
                              |  softmax over   |              |  history,       |
                              |  trained classes|              |  device_status, |
                              +-------+---------+              |  app_settings   |
                                      |                        +--------+--------+
                                      |                                 |
                                      +----------------+----------------+
                                                       |
                                              +--------v---------+
                                              |  React dashboard |
                                              |  7 pages, Recharts|
                                              +------------------+
```

---

## 2. The unified prediction pipeline

Every camera source converges on one function,
`services/detection_service.py::analyze_and_store`. This is the design decision
the whole feature rests on: there is no per-camera code path, so the two
cameras cannot drift apart.

```
 bytes (from any source)
        |
        v
 1. validate_image_bytes()           utils/image_utils.py
        |  - non-empty
        |  - within MAX_UPLOAD_MB
        |  - magic bytes identify a supported format
        |  - JPEG: size floor + End-Of-Image marker present
        |  - decodes to a real raster  (Pillow, via ml_bridge)
        |  - at least 16x16 pixels
        v
 2. assess_image_quality()           ml/preprocessing.py
        |  - resolution, sharpness (variance of Laplacian)
        |  - brightness, contrast, leaf-like pixel ratio
        |  - FAIL -> status "unknown", model never runs
        v
 3. preprocess_for_model()           ml/preprocessing.py
        |  - EXIF orientation applied, converted to RGB
        |  - resized to 224x224 bilinear
        |  - normalisation happens INSIDE the saved model
        v
 4. model.predict()                  ml/predict.py
        |  - MobileNetV2 softmax over the trained classes
        v
 5. confidence gate
        |  - below CONFIDENCE_THRESHOLD -> "uncertain", no disease named
        v
 6. save image + insert row          services/detection_service.py
        |  - image written only AFTER inference succeeds
        |  - camera_source recorded
        v
 identical JSON response
```

Two ordering decisions worth noting:

* **Quality gate before the model.** A blurred or leaf-free frame is reported as
  unusable rather than classified. Running the model first and then deciding
  would mean having a disease name on hand for an image that should never have
  produced one.
* **Image saved after inference succeeds.** If no model is available the request
  fails without leaving an orphan file on disk. An *inconclusive* result is
  still saved, because "the system could not decide" is information the operator
  needs.

---

## 3. Acquisition layer

### Laptop webcam (browser-owned)

```
navigator.mediaDevices.getUserMedia({ video: {...} })
        |
   MediaStream -> <video> preview (live)
        |
   canvas.drawImage(video)            on "Capture image"
        |
   canvas.toBlob('image/jpeg', 0.92)
        |
   new File([blob], 'webcam-<ts>.jpg')
        |
   POST /api/predict  (multipart, camera_source=laptop_webcam)
```

The Flask process has no access to this camera and does not pretend otherwise:
`/api/cameras` reports the webcam's availability as `null` with
`managed_by: "browser"`.

Capture and analysis are two steps by design. A live frame is easy to get wrong,
and reviewing the still costs less than an inference pass on a bad image.

### ESP32-CAM (backend-owned)

Two transports, because a classroom or lab network rarely allows both
directions.

**Pull (preferred)**

```
Dashboard --POST /api/capture--> Backend --GET /capture--> ESP32-CAM
                                         <---- JPEG -----
```

**Push fallback** - used when the backend cannot open a connection to the board
(client isolation, different subnet, unknown IP):

```
Dashboard --POST /api/capture--> Backend
                                   |  queues a CaptureJob, blocks on an Event
                                   |
ESP32-CAM --GET /api/device/command--> Backend
          <-- {action:"capture", job_id} --
          |
          | captures, validates JPEG markers locally
          |
ESP32-CAM --POST /api/device/upload?job_id=...--> Backend
                                                    | fulfils the job, wakes
                                                    | the waiting request
Dashboard <------------ prediction ------------------+
```

The backend tries pull first and falls back automatically. If neither delivers
an image, the 503 names **both** failures - "camera unreachable AND no device
polled for the job" is the diagnosis the user actually needs.

Jobs live in memory only (`CaptureJobRegistry`), keyed by a random id, pruned
after 120 seconds. Persisting them would serve no purpose: a job whose waiting
HTTP request has gone is worthless.

---

## 4. Backend structure

```
backend/
  app.py                    application factory, LAN-IP banner, /uploads route
  config.py                 typed env configuration, per-environment classes
  routes/
    system_routes.py        /api, /health, /classes, /disease-info, /model/reload
    detection_routes.py     /predict, /analyze, /capture
    camera_routes.py        /cameras
    history_routes.py       /history (+ filters, delete)
    stats_routes.py         /stats, /analytics
    device_routes.py        /device/* (dashboard- and firmware-facing)
  services/
    ml_service.py           owns the single loaded model; test-mode policy
    detection_service.py    THE shared pipeline
    esp32_service.py        HTTP client + capture-job registry
    stats_service.py        aggregation queries
    settings_service.py     app_settings access, host validation
  models/
    detection.py            detection_history DAO + camera_source normalisation
    device.py               device_status DAO, derived liveness
  database/
    schema.sql              fresh-install schema
    migrations.py           additive, idempotent upgrades
    db.py                   connection-per-request, WAL, query helpers
    init_db.py              CLI
  utils/
    image_utils.py          validation, JPEG integrity, safe storage
    ml_bridge.py            the one place that puts ml/ on sys.path
    responses.py            one JSON envelope
    errors.py               ApiError hierarchy + handlers
    logging_config.py       console logging; sets TF_CPP_MIN_LOG_LEVEL early
```

### Startup order (matters)

1. `configure_logging()` - also sets `TF_CPP_MIN_LOG_LEVEL`, which TensorFlow
   only reads at import time.
2. Create directories, open SQLite, apply `schema.sql`, run migrations.
3. Build `MLService` and load the model eagerly, so the first real prediction is
   not delayed by a 5-10 second load.
4. Build `Esp32CamService`; ensure the configured device has a row so the Device
   page has something to show before the first heartbeat.
5. Register blueprints, JSON error handlers and `/uploads`.

### Why `ml/` is a sibling, not a sub-package

The training scripts must stay runnable on their own (`cd ml && python
train.py`) and must not depend on Flask. `utils/ml_bridge.py` is the single
place that inserts `ml/` onto `sys.path` and re-exports what the backend needs,
so no other backend file performs path surgery. TensorFlow is imported lazily
inside `predict.py`, so importing the bridge is cheap.

---

## 5. Frontend structure

```
frontend/src/
  App.tsx                   routing; dashboard pages are code-split
  layouts/
    DashboardLayout.tsx     sidebar + top bar + global banners
    SystemStatusProvider.tsx  one shared /api/health poll
  pages/
    LandingPage.tsx         objectives, pipeline, stack, abstract
    DashboardPage.tsx       totals, device state, charts, recent detections
    DetectionPage.tsx       three-way source selector + capture/upload
    CameraPage.tsx          Camera Management
    HistoryPage.tsx         grid/table, filters incl. camera source
    AnalyticsPage.tsx       trends + model evaluation metrics
    DevicePage.tsx          ESP32-CAM diagnostics, LED, wiring reference
    AboutPage.tsx           abstract, architecture, methodology, limitations
  components/
    camera/                 WebcamCapture, Esp32CameraCard, source selector/badge
    detection/              dropzone, result card, probability list, history item
    charts/                 Recharts wrappers + confusion matrix
    layout/ banners/ ui/    shell, honesty banners, design-system primitives
  hooks/
    useApiResource.ts       loading/error/polling/stale-response guard
    useBackendData.ts       one typed hook per endpoint
    useWebcam.ts            MediaDevices lifecycle, capture, error mapping
  services/
    api.ts                  Axios client, envelope unwrapping, ApiClientError
    types.ts                hand-maintained mirrors of the API payloads
  utils/
    format.ts status.ts     dates/bytes/percent, status and severity maps
```

`SystemStatusProvider` exists because four places need `/api/health` at once -
the sidebar badge, the top-bar indicator, the test-mode banner and the Detect
page's capability check. Without a shared provider each would poll
independently and hit the single-threaded Flask dev server four times every
twenty seconds.

---

## 6. Data model

See [`database_migration.md`](database_migration.md) for the full column list.

```
 detection_history                      device_status
 -----------------                      -------------
 id                                     id
 image_path        -> backend/uploads/  device_name  (unique, = DEVICE_NAME)
 plant_name                             ip_address
 predicted_disease                      connection_status  (derived on read)
 confidence                             last_seen
 detection_status                       wifi_rssi, free_heap, frame_size, ...
 camera_source  <-- laptop_webcam |     led_state
                    esp32_cam |         last_capture_at, total_captures
                    file_upload         last_error
 created_at
 model_mode, is_validated               app_settings
 probabilities (JSON)                   ------------
 image_quality (JSON)                   key  -> 'esp32_cam_ip'
                                        value
```

`source` (transport) and `camera_source` (physical camera) are kept separate
because an HTTP upload can now be either a browser webcam frame or a file from
disk - one column cannot carry both meanings without redefining stored rows.

---

## 7. Accountability design

The system is built so that no screen can mislead a user into acting on a result
the model cannot support.

| Mechanism | Where |
|---|---|
| Quality gate rejects unusable frames before inference | `ml/preprocessing.py` |
| Confidence threshold; below it, no disease is named | `ml/predict.py` |
| `is_validated_prediction` false for any untrained model | `ml/predict.py` |
| `is_validated = 0` stored on such rows | `models/detection.py` |
| `/api/health` exposes `model.is_test_mode` | `routes/system_routes.py` |
| Permanent amber TEST MODE banner on every page | `components/banners/SystemBanners.tsx` |
| Per-result "Not a real diagnosis" notice | `components/detection/PredictionResult.tsx` |
| Analytics warns when history contains test-mode rows | `pages/AnalyticsPage.tsx` |
| `ALLOW_TEST_MODE_MODEL=false` refuses such predictions outright | `config.py` |
| Empty/truncated device uploads refused, never stored | `routes/device_routes.py` |
| Class list read from the trained model, never hardcoded | `/api/classes` |

---

## 8. Request flow examples

### Webcam capture

```
Browser: canvas.toBlob -> File
  POST /api/predict  (multipart, camera_source=laptop_webcam)
    -> _extract_image_bytes()      finds the multipart part
    -> _resolve_camera_source()    validates against CAMERA_SOURCES
    -> analyze_and_store()         THE shared pipeline
         validate -> quality -> preprocess -> predict -> threshold
         save image (prefix "webcam") -> insert row
    <- 200 {prediction, detection, image, camera_source}
```

### ESP32-CAM capture, push fallback

```
POST /api/capture
  -> Esp32CamService.capture()
       capture_pull()   -> DeviceUnreachableError (logged, not fatal)
       capture_push()   -> jobs.create() -> Event.wait(30s)
                                 ^
       (firmware) GET /api/device/command  -> {action:"capture", job_id}
       (firmware) captures, checks SOI/EOI locally, retries up to 3x
       (firmware) POST /api/device/upload?job_id=...
                      -> integrity check -> jobs.fulfil() -> Event.set()
                                 |
       capture_push() returns bytes
  -> analyze_and_store(camera_source=esp32_cam)
  <- 200 {prediction, capture:{transport:"push", job_id}, ...}
```

### Health degradation

```
GET /api/health
  -> database probe (a real COUNT, not just a file check)
  -> MLService.status()
  -> mark stale devices offline, read the primary device
  <- 200 {status:"healthy"}   when both are fine
  <- 503 {status:"degraded", problems:["model"]}   backend up, model missing
```

The 503-with-a-body distinction lets the dashboard tell "backend is down" apart
from "backend is up but has no trained model", which need completely different
guidance.
