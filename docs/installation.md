# Installation and Setup

Complete setup for the AI-Based Smart Plant Disease Detection system: machine
learning, backend, dashboard, and both camera sources.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 - 3.12 | TensorFlow does not publish wheels for 3.13 yet |
| Node.js | 18 or newer | 20 LTS recommended |
| npm | 9 or newer | Ships with Node |
| Arduino IDE | 2.x | Only for the ESP32-CAM |
| Disk space | ~3 GB | TensorFlow is most of it |
| RAM | 8 GB | 4 GB works for inference only |

Check what you have:

```bash
python --version
node --version
npm --version
```

A laptop webcam needs no extra software. The ESP32-CAM needs the hardware in
[`circuit_diagram.md`](circuit_diagram.md).

---

## 2. Python environment

From the project root (`plant-disease-detection/`):

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

If activation is blocked by execution policy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

This installs Flask, TensorFlow, OpenCV, scikit-learn, Pillow and the reporting
libraries - about 600 MB of downloads, so allow a few minutes.

Verify:

```bash
python -c "import tensorflow as tf; print('TensorFlow', tf.__version__)"
python ml/label_utils.py        # prints parsed class names
python ml/preprocessing.py      # prints a dataset report
```

---

## 3. Configuration

```powershell
copy .env.example .env          # Windows
cp .env.example .env            # Linux / macOS
```

Every value has a working default, so the system runs with no `.env` at all.
The ones worth reviewing:

| Variable | Default | When to change it |
|---|---|---|
| `FLASK_PORT` | `5000` | Port already in use |
| `CONFIDENCE_THRESHOLD` | `0.70` | After training, `train.py` prints a suggested value |
| `ESP32_CAM_IP` | empty | Leave empty - the board self-registers |
| `ESP32_CAM_NAME` | `esp32-cam-01` | Must match `DEVICE_NAME` in the sketch |
| `ALLOW_TEST_MODE_MODEL` | `true` | Set `false` once a real model is trained |
| `CORS_ORIGINS` | localhost:5173, :4173 | Add your LAN address to view from a phone |
| `DEVICE_API_KEY` | empty | Set in both `.env` and the sketch to require a shared secret |

See [`camera_sources.md`](camera_sources.md) for the camera-specific settings.

---

## 4. Machine learning model

The backend needs a loadable model. There are two routes.

### Option A - train on PlantVillage (produces real predictions)

1. Download the PlantVillage dataset (Kaggle: *PlantVillage Dataset*, or the
   original spMohanty/PlantVillage-Dataset repository).

2. Extract the class folders into `ml/dataset/` so the layout is one directory
   per class:

   ```
   ml/dataset/
     Pepper,_bell___Bacterial_spot/   image (1).JPG ...
     Pepper,_bell___healthy/
     Potato___Early_blight/
     Potato___Late_blight/
     Potato___healthy/
     Tomato___Early_blight/
     Tomato___Late_blight/
     Tomato___Leaf_Mold/
     Tomato___Septoria_leaf_spot/
     Tomato___healthy/
   ```

   The folder names become the class labels, so keep the `Plant___Condition`
   convention. You may include more classes; the dashboard reads the list from
   the trained model.

3. Validate before committing to a long run:

   ```bash
   python ml/train.py --validate-only
   ```

4. Train:

   ```bash
   cd ml
   python train.py                              # full run
   python train.py --max-images-per-class 300   # quick trial
   python train.py --epochs 20 --fine-tune-epochs 10 --batch-size 32
   ```

   Two stages run: the frozen-base head, then fine-tuning of the top 40 layers.
   On a CPU expect 1-3 hours for the full dataset; `--max-images-per-class 300`
   finishes in roughly 15-25 minutes.

   Outputs:

   | Path | Contents |
   |---|---|
   | `ml/saved_model/plant_disease_model.keras` | The trained model |
   | `ml/saved_model/metadata.json` | Provenance, settings, metrics |
   | `ml/class_labels.json` | Class order and parsed names |
   | `ml/reports/metrics.json` | Accuracy, precision, recall, F1 |
   | `ml/reports/confusion_matrix.png` | Normalised heat map |
   | `ml/reports/training_curves.png` | Accuracy and loss per epoch |

5. Re-score an existing model at any time:

   ```bash
   python ml/evaluate.py
   ```

### Option B - untrained test model (pipeline testing only)

When the dataset is not available yet and you want to wire up and test the
hardware, dashboard and API:

```bash
python ml/create_test_model.py
```

This builds a MobileNetV2 with a **randomly initialised** classification head.
It is labelled as such at every layer:

* `metadata.json` carries `trained: false`, `test_mode: true`
* `/api/health` returns `model.is_test_mode = true`
* every prediction has `is_validated_prediction: false` and a warning
* stored rows get `is_validated = 0`
* the dashboard shows a permanent amber **TEST MODE** banner

Its outputs are **not diagnoses**. Replace it by running `train.py`, then
either restart the backend or call `POST /api/model/reload`.

---

## 5. Database

Created automatically on first start, and migrated on every start:

```bash
python backend/database/init_db.py            # explicit creation
python backend/database/init_db.py --show     # tables, columns, row counts
python backend/database/init_db.py --reset    # DESTRUCTIVE: drops everything
```

Migrations are additive and idempotent, so upgrading preserves existing
records. See [`database_migration.md`](database_migration.md).

---

## 6. Start the backend

```bash
cd backend
python app.py
```

```
========================================================================
  AI Plant Disease Detection - Flask backend
========================================================================
  API                            : http://192.168.1.10:5000/api
  Local API                      : http://127.0.0.1:5000/api
  Dashboard                      : http://localhost:5173
  Model                          : trained, test accuracy 97.84%
  Classes                        : 10
  Confidence gate                : 70%
  Camera IP                      : not set (device will self-register)
  FLASK_SERVER_IP for the sketch : 192.168.1.10
========================================================================
```

**Note the last line** - that is the value to put in the ESP32-CAM sketch.

Verify:

```bash
curl http://127.0.0.1:5000/api/health
curl http://127.0.0.1:5000/api/cameras
```

---

## 7. Start the dashboard

In a second terminal:

```bash
cd frontend
npm install        # first time only
npm run dev
```

Open **http://localhost:5173**.

> Use `localhost`, not your LAN IP, if you want the laptop webcam to work -
> browsers only grant camera access on a secure origin. See
> [`camera_sources.md`](camera_sources.md#the-secure-context-rule).

The dev server proxies `/api` and `/uploads` to the backend, so no CORS setup
is needed during development.

Production build:

```bash
npm run build      # outputs to frontend/dist
npm run preview    # serve the build on :4173
```

---

## 8. Camera source A - laptop webcam

Nothing to install.

1. Open **Camera Management** in the dashboard.
2. Select **Laptop webcam**.
3. Press **Start camera** and allow the permission prompt.
4. Frame one leaf in the dashed guide, press **Capture image**.
5. Press **Analyse plant**.

---

## 9. Camera source B - ESP32-CAM

### 9.1 Arduino IDE setup

1. **File -> Preferences -> Additional Board Manager URLs**, add:

   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```

2. **Tools -> Board -> Boards Manager**, search `esp32`, install
   **esp32 by Espressif Systems**.

3. Select **Tools -> Board -> ESP32 Arduino -> AI Thinker ESP32-CAM**.

4. Set these, which matter:

   | Setting | Value | Why |
   |---|---|---|
   | Partition Scheme | Huge APP (3MB No OTA/1MB SPIFFS) | The default is too small |
   | PSRAM | Enabled | Without it the camera cannot allocate large frames |
   | Upload Speed | 115200 | Higher speeds fail on many USB-TTL adapters |
   | Flash Frequency | 80 MHz | |

### 9.2 Configure the sketch

Open `esp32cam/plant_disease_camera.ino` and edit three values:

```cpp
#define WIFI_SSID         "YourNetwork"        // 2.4 GHz only
#define WIFI_PASSWORD     "YourPassword"
#define FLASK_SERVER_IP   "192.168.1.10"       // from the backend banner
```

`127.0.0.1` and `localhost` refer to the ESP32 itself and will never work here.

### 9.3 Wire and flash

Follow [`circuit_diagram.md`](circuit_diagram.md), then:

1. Connect GPIO 0 to GND.
2. Press RESET on the board.
3. Click **Upload**.
4. **Disconnect GPIO 0 from GND.**
5. Press RESET.

### 9.4 Verify

Open **Tools -> Serial Monitor** at **115200 baud**. You should see the camera
initialise, Wi-Fi connect, an IP address, and `First heartbeat accepted`.

Then in the dashboard: **Camera Management -> ESP32-CAM** shows the device
online. Press **Capture image and analyse**.

### 9.5 No hardware yet?

A simulator speaks the same HTTP protocol (heartbeat, command poll, upload) so
the full capture path can be tested without a board:

```bash
python scripts/simulate_esp32cam.py --device esp32-cam-01
```

It is explicitly labelled: the device name defaults to `esp32-cam-sim`, the
firmware version is `simulator-1.0.0`, and generated frames carry a visible
"SIMULATED FRAME" banner. It verifies the protocol and backend, not the optics,
LED or Wi-Fi behaviour of real hardware.

---

## 10. Verify the whole system

```bash
python scripts/smoke_test.py
```

63 assertions across health, classes, prediction, both camera sources, device
configuration, input validation, history, statistics and device endpoints.
Exit code 0 means everything passed.

---

## 11. Commands reference

| Task | Command |
|---|---|
| Train the model | `cd ml && python train.py` |
| Evaluate a model | `python ml/evaluate.py` |
| Predict from the CLI | `python ml/predict.py path/to/leaf.jpg` |
| Create a test model | `python ml/create_test_model.py` |
| Initialise the database | `python backend/database/init_db.py` |
| Inspect the database | `python backend/database/init_db.py --show` |
| Start the backend | `cd backend && python app.py` |
| Start the dashboard | `cd frontend && npm run dev` |
| Build the dashboard | `cd frontend && npm run build` |
| Run the API tests | `python scripts/smoke_test.py` |
| Simulate the camera | `python scripts/simulate_esp32cam.py` |
| Reload the model without restarting | `curl -X POST http://127.0.0.1:5000/api/model/reload` |

---

## 12. Troubleshooting

### Installation

| Problem | Fix |
|---|---|
| `No matching distribution found for tensorflow` | Python 3.13 has no TensorFlow wheels. Use 3.10-3.12. |
| `Microsoft Visual C++ 14.0 required` | Install the Visual Studio Build Tools, or use a prebuilt wheel. |
| npm install fails behind a proxy | `npm config set proxy http://...` |

### Backend

| Problem | Fix |
|---|---|
| `Address already in use` | Change `FLASK_PORT`, or stop the process on 5000. |
| `Model file not found` | Run `train.py` or `create_test_model.py`. |
| `Model/label mismatch` | `class_labels.json` and the model disagree. Retrain so both are written together. |
| Slow first prediction | Expected: the model loads lazily unless `EAGER_MODEL_LOAD=true`. |

### Dashboard

| Problem | Fix |
|---|---|
| "Backend not reachable" | Start `python app.py`; check the port. |
| Blank page after build | Serve `dist/` from a web server, not the filesystem. |
| CORS error | Add the origin to `CORS_ORIGINS`, or set `CORS_ALLOW_ALL=true` on a trusted network. |

Camera problems are covered in [`camera_sources.md`](camera_sources.md), and
hardware problems in [`circuit_diagram.md`](circuit_diagram.md).
