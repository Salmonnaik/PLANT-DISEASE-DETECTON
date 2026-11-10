# AI-Based Smart Plant Disease Detection and Classification

Leaf-disease detection from **two camera sources** - a laptop webcam and an
ESP32-CAM - through **one** MobileNetV2 prediction pipeline, a Flask REST API,
SQLite persistence and a React dashboard.

```
  Laptop webcam  ─┐
                  ├─► Flask API ─► MobileNetV2 ─► SQLite ─► React dashboard
  ESP32-CAM      ─┤
  Image file     ─┘
```

---

## What this is

Plant disease costs a large share of global crop yield every year, and most of
that loss is avoidable: early symptoms are visible on the leaf long before the
crop is lost. The barrier is access to diagnosis, not the existence of a cure.

This project puts a diagnostic loop on a desk. A camera acquires the image, a
convolutional network small enough to run on a laptop CPU classifies it, and a
dashboard turns a probability vector into something a grower can act on.

The engineering emphasis is on **not overclaiming**:

* Images that are blurred, dark, over-exposed or contain no leaf are **rejected**
  rather than classified.
* Predictions below a configurable confidence threshold are reported as
  **uncertain**, naming no disease.
* If the loaded model has never been trained, **every** response and every
  screen says so.

A diagnostic tool that is occasionally silent is more useful than one that is
confidently wrong.

---

## Features

### Universal analysis - any plant, not just ten classes

The trained classifier knows ten PlantVillage classes across three crops. A
softmax layer always produces an answer, so feeding it a mango leaf returns a
*tomato* disease with a confidence number attached - meaningless, and dressed up
to look trustworthy.

A second, species-agnostic layer solves that. It measures what is actually on
the leaf with OpenCV - colour composition, lesion blobs and their geometry,
margin versus interior necrosis, powdery coating, holes, mottling, shape
distortion - and maps those measurements to a shortlist of possible conditions,
each with the evidence for and against it.

| | Trained classifier | Universal analysis |
|---|---|---|
| Covers | 10 classes, 3 crops | Any plant |
| Output | A class with a softmax probability | Measured symptoms + consistent conditions |
| Used when | The plant is one it was trained on *and* it is confident | Always |

The classifier is consulted **only** for the crops it was trained on. For
anything else the response says so rather than force-fitting a label.

15 species have care profiles (mango, neem, rose, hibiscus, banana, papaya,
guava, apple, grapevine, tomato, potato, pepper, corn, lemon, orange); any other
plant is still analysed and gets general care guidance.

Species identification is handled honestly: the user selects the plant (most
reliable), or an **optional** AI vision API identifies it, or it is reported as
unidentified. It is never guessed. See
[`docs/universal_analysis.md`](docs/universal_analysis.md).

### Two camera sources, one model

| Source | Acquired by | Recorded as |
|---|---|---|
| Laptop / USB webcam | The browser - MediaDevices API + HTML canvas | `laptop_webcam` |
| ESP32-CAM (OV2640) | The backend over Wi-Fi, or pushed by the board | `esp32_cam` |
| Existing image file | The browser file picker | `file_upload` |

All three converge on a single function. Same validation, same preprocessing,
same 224x224 input, same normalisation, same weights, same class labels, same
confidence threshold. The camera is recorded with each detection but never
changes the result - and the test suite asserts exactly that by submitting
identical bytes as two different sources and requiring identical output.

### Machine learning

* MobileNetV2 transfer learning on PlantVillage, two-stage (frozen head, then
  fine-tuning of the top 40 layers with BatchNorm kept frozen).
* Augmentation, inverse-frequency class weights, early stopping with checkpoint
  restoration.
* Evaluation on a held-out split rebuilt from the same seed: accuracy, top-3,
  macro and weighted precision/recall/F1, per-class scores, confusion matrix,
  plus a separate healthy-vs-diseased accuracy.
* Normalisation lives **inside** the saved model, which structurally eliminates
  train/serve skew.

### Backend

* Flask REST API with one JSON envelope and stable machine-readable error codes.
* Layered image validation: magic bytes, size floor, JPEG End-Of-Image marker,
  then an actual decode.
* Pull and push capture transports with a combined, actionable failure message.
* SQLite with additive, idempotent migrations that preserve existing records.

### Dashboard

Seven pages - Landing, Dashboard, Disease Detection, Camera Management,
Detection History, Analytics, Device Management, About - with live backend data,
explicit loading/empty/error states, and camera-source filtering throughout.

---

## Quick start

Requires Python 3.10-3.12 and Node 18+.

```bash
# 1. Python environment
python -m venv .venv
.venv\Scripts\activate                 # Windows
# source .venv/bin/activate            # Linux / macOS
pip install -r backend/requirements.txt

# 2. Configuration (optional - every value has a default)
copy .env.example .env                 # Windows
# cp .env.example .env                 # Linux / macOS

# 3. A model. Either train one...
cd ml && python train.py --dataset-dir dataset && cd ..
#    ...or create an explicitly untrained one for pipeline testing:
python ml/create_test_model.py

# 4. Backend
cd backend && python app.py

# 5. Dashboard (second terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**.

> Use `localhost`, not a LAN IP, if you want the laptop webcam: browsers only
> grant camera access on a secure origin.

### Add the ESP32-CAM

1. Wire it per [`docs/circuit_diagram.md`](docs/circuit_diagram.md).
2. Open `esp32cam/plant_disease_camera.ino`, set `WIFI_SSID`, `WIFI_PASSWORD`
   and `FLASK_SERVER_IP` (the backend prints the value to use).
3. Flash with the Arduino IDE: board **AI Thinker ESP32-CAM**, partition
   **Huge APP**, **PSRAM enabled**.
4. The board self-registers; the dashboard shows it on **Camera Management**.

No hardware yet? `python scripts/simulate_esp32cam.py` speaks the same protocol.

---

## Project structure

```
plant-disease-detection/
├── frontend/              React 18 + TypeScript + Vite + Tailwind + Recharts
│   └── src/
│       ├── components/    camera/ detection/ charts/ layout/ banners/ ui/
│       ├── pages/         7 pages
│       ├── layouts/       dashboard shell + shared health provider
│       ├── services/      typed Axios client and API types
│       ├── hooks/         data fetching, webcam lifecycle
│       └── utils/         formatting, status maps
├── backend/               Flask REST API
│   ├── app.py             application factory and entry point
│   ├── config.py          environment-driven configuration
│   ├── routes/            system, detection, camera, history, stats, device
│   ├── services/          ml, detection pipeline, esp32, stats, settings
│   ├── models/            detection_history and device_status DAOs
│   ├── database/          schema, migrations, init script
│   ├── utils/             validation, responses, errors, ml bridge
│   └── uploads/           stored images, YYYY/MM/
├── ml/                    training and inference
│   ├── train.py           two-stage transfer learning
│   ├── evaluate.py        metrics and confusion matrix
│   ├── predict.py         the inference engine
│   ├── preprocessing.py   datasets, augmentation, quality gate
│   ├── model_builder.py   MobileNetV2 architecture
│   ├── create_test_model.py  explicitly untrained model
│   ├── saved_model/       plant_disease_model.keras + metadata.json
│   └── reports/           evaluation artefacts
├── esp32cam/
│   └── plant_disease_camera.ino
├── scripts/
│   ├── smoke_test.py      63-assertion API suite
│   └── simulate_esp32cam.py  firmware protocol simulator
├── docs/
│   ├── architecture.md    layers, pipeline, request flows
│   ├── camera_sources.md  both cameras, configuration, troubleshooting
│   ├── circuit_diagram.md wiring, pin map, verification
│   ├── installation.md    full setup
│   ├── database_migration.md  schema and migration details
│   └── testing.md         automated and manual test procedures
├── .env.example
└── README.md
```

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Backend, database, model and device status |
| `GET` | `/api/classes` | Plants and conditions the model can predict |
| `GET` | `/api/cameras` | Camera sources, their state, shared pipeline settings |
| `POST` | `/api/diagnosis` | **Full diagnosis - any plant species** (alias: `/api/analyze-plant`) |
| `GET` | `/api/plants` | Species with care profiles, classifier and vision-API coverage |
| `GET` | `/api/diseases` | The 14 conditions: symptoms, causes, severity scale |
| `GET` | `/api/treatments` | Organic and chemical guidance; `?condition=<id>` to filter |
| `POST` | `/api/predict` | Classify an image against the 10 trained classes |
| `POST` | `/api/analyze` | Classify without saving |
| `POST` | `/api/capture` | Capture from the ESP32-CAM, then classify |
| `GET` | `/api/history` | Paginated history; filters incl. `camera_source` |
| `GET` | `/api/history/filters` | Distinct values for the filter controls |
| `GET` | `/api/history/<id>/report` | Download that diagnosis as a PDF |
| `DELETE` | `/api/history/<id>` | Delete one record and its image |
| `GET` | `/api/stats` | Dashboard totals, distributions, activity |
| `GET` | `/api/analytics` | The above plus model evaluation metrics |
| `GET` | `/api/device/status` | ESP32-CAM status and troubleshooting |
| `POST` | `/api/device/status` | Alias of `/api/device/register` (device → server) |
| `GET`/`POST` | `/api/device/config` | Read or set the camera IP from the dashboard |
| `POST` | `/api/device/register` | Firmware heartbeat |
| `GET` | `/api/device/command` | Firmware poll for a queued capture |
| `POST` | `/api/device/upload` | Firmware image push |
| `POST` | `/api/device/led` | Switch the white LED |
| `POST` | `/api/model/reload` | Reload the model after training |

Every response uses one envelope:

```json
{ "success": true, "data": { }, "message": "...", "timestamp": "..." }
{ "success": false, "error": { "code": "DEVICE_UNREACHABLE", "message": "...", "details": { } } }
```

---

## Supported classes

Read from the trained model at runtime, never hardcoded. The default class list:

| Plant | Conditions |
|---|---|
| Tomato | Healthy, Early Blight, Late Blight, Leaf Mould, Septoria Leaf Spot |
| Potato | Healthy, Early Blight, Late Blight |
| Bell Pepper | Healthy, Bacterial Spot |

Add classes by adding their folders to `ml/dataset/` and retraining; the
dashboard picks up the new list automatically.

---

## Testing

```bash
python scripts/smoke_test.py                  # 90 API assertions
python scripts/test_leaf_analysis.py          # 10 CV discrimination assertions
cd frontend && npx tsc -b && npm run build    # types and bundle
python ml/evaluate.py                         # model metrics
```

Manual procedures for the webcam and the real ESP32-CAM are in
[`docs/testing.md`](docs/testing.md).

---

## Test mode

When no trained model exists, `ml/create_test_model.py` produces a MobileNetV2
with a **randomly initialised** head so the hardware, API and dashboard can be
integration-tested. It is impossible to mistake for a trained model:

* `metadata.json` records `trained: false`
* `/api/health` returns `model.is_test_mode: true`
* every prediction carries `is_validated_prediction: false` and a warning
* stored rows get `is_validated = 0`
* the dashboard shows a permanent amber **TEST MODE** banner
* `ALLOW_TEST_MODE_MODEL=false` refuses such predictions outright

Because the head is untrained, its outputs hover near 1/N and therefore fall
below the confidence threshold - they are reported as *uncertain*, not as
diseases.

---

## Limitations

* PlantVillage images are captured on plain backgrounds under controlled
  lighting. Accuracy on cluttered field photographs is materially lower, and the
  reported figure should be read as an upper bound, not as field accuracy.
* The model can only output a class it was trained on. An unseen crop maps to
  the nearest known class - which is why the confidence threshold exists.
* Classification is per leaf, not per plant.
* Inference runs on the server; the camera alone cannot diagnose anything.
* The ESP32-CAM browns out below roughly 5 V at 500 mA, which shows up as
  repeated camera-init failures rather than an obvious power fault.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/universal_analysis.md`](docs/universal_analysis.md) | Any-plant analysis: what is measured, species handling, treatment rules, limits |
| [`docs/installation.md`](docs/installation.md) | Full setup, both cameras, command reference, troubleshooting |
| [`docs/architecture.md`](docs/architecture.md) | Layers, the shared pipeline, request flows, accountability design |
| [`docs/camera_sources.md`](docs/camera_sources.md) | Both cameras in depth, configuration, per-source troubleshooting |
| [`docs/circuit_diagram.md`](docs/circuit_diagram.md) | Bill of materials, wiring, pin map, verification checklist |
| [`docs/database_migration.md`](docs/database_migration.md) | Schema, migrations, backups |
| [`docs/testing.md`](docs/testing.md) | Automated suites and manual procedures |

The **About Project** page in the dashboard also carries the abstract, problem
statement, literature review outline, ML methodology, testing approach, results
discussion, limitations and future scope.

---

## Technology

**Frontend** React 18, TypeScript, Vite 5, Tailwind CSS 3, Recharts, Axios,
React Router, lucide-react
**Backend** Python 3, Flask 3, Flask-CORS, SQLite, Pillow, requests
**ML** TensorFlow 2 / Keras 3, MobileNetV2, OpenCV, NumPy, scikit-learn,
matplotlib
**Hardware** ESP32-CAM (AI Thinker), OV2640, white LED on GPIO 4, Arduino IDE
