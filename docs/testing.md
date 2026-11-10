# Testing Documentation

Six levels, each independently runnable, plus the manual procedures for the two
camera sources and the diagnosis dashboard.

| Level | What it proves | Command |
|---|---|---|
| Module self-checks | Label parsing and image quality measurement | `python ml/label_utils.py` |
| CV discrimination | Different leaves give different findings | `python scripts/test_leaf_analysis.py` |
| Model evaluation | Accuracy, precision, recall, F1, confusion matrix | `python ml/evaluate.py` |
| API suite | Every endpoint and failure path | `python scripts/smoke_test.py` |
| Device protocol | Heartbeat, command poll, image upload | `python scripts/simulate_esp32cam.py` |
| Hardware | Camera, LED, Wi-Fi on the real board | Serial monitor at 115200 baud |

---

## 1. Automated API suite

```bash
python scripts/smoke_test.py
python scripts/smoke_test.py --server http://192.168.1.10:5000
python scripts/smoke_test.py --keep      # keep the records it creates
```

Exit code 0 means every assertion passed. 90 assertions across eleven sections:

| Section | Checks |
|---|---|
| 1. Health and configuration | Backend responds, database connected, model loaded, predictions permitted |
| 2. Classes and reference data | Class list parsed, reference entries present |
| 3. Prediction pipeline | Valid image accepted, probability vector sums to 1, confidence consistent with status, quality gate rejects a flat frame, threshold override honoured, `save=false` persists nothing |
| 4. Camera sources | Both sources listed, webcam reported as browser-managed, **identical result from either source**, unknown source rejected, filtering and statistics by camera |
| 5. Universal plant analysis | Out-of-class plant analysed rather than rejected, classifier **not** forced onto it, symptoms carry their measurement, non-disease causes shortlisted, different images give different findings, chemical advice withheld while uncertain, no dosages anywhere, `/api/diagnosis` matches its alias, `/api/diseases` and `/api/treatments` complete, **PDF report valid** |
| 6. ESP32-CAM configuration | Address read, saved, probed, invalid value rejected, original restored |
| 7. Validation | Non-image bytes, missing part, empty body, tiny image, bad filters, JSON 404, unconfirmed delete, empty device upload, truncated device JPEG, wrong Content-Type |
| 8. Detection history | Pagination, required fields, single record, 404, filters |
| 9. Statistics | Totals add up, activity zero-filled, statistics agree with the history table |
| 10. Device endpoints | Status, device list, heartbeat, command poll, empty upload refused |
| 11. Cleanup | Test records removed |

Section 5 is where the honesty rules are enforced mechanically. Three of its
assertions exist to fail loudly if the system ever starts bluffing:

```
PASS  The 10-class classifier was NOT forced onto an out-of-class plant
PASS  Chemical advice is withheld while the assessment is uncertain
      confidence=possible, chemical_withheld=True
PASS  No dosages or application rates appear in the guidance
```

### The assertion that matters most

```
PASS  The same image gives the same result from either source
      both: Uncertain result at 34.04%
```

The suite submits identical bytes twice - once as `laptop_webcam`, once as
`file_upload` - and requires the same predicted class and a confidence
difference below 1e-6. If the two paths ever diverge, the pipeline is no longer
shared and this fails.

### Synthetic images

The generated shapes exercise the *pipeline*, not plant biology. They are not
photographs, so whichever class the model assigns them is meaningless; the
assertions only check structure and behaviour, never a specific disease.

---

## 2. Camera source A - laptop webcam

Automated coverage ends at the HTTP request, because the camera belongs to the
browser. The suite tests exactly the request the browser makes after
`canvas.toBlob()`. The steps below cover what only a human can.

| # | Step | Expected |
|---|---|---|
| A1 | Open `http://localhost:5173/cameras` | Camera Management loads, webcam card shown |
| A2 | Select **Laptop webcam**, press **Start camera** | Browser asks permission; after allowing, a live preview appears with the dashed framing guide and a resolution badge |
| A3 | Check the camera picker (if more than one camera) | Real device names listed, switching changes the preview |
| A4 | Press **Capture image** | Preview freezes to a still; **Retake image** and **Analyse plant** become active |
| A5 | Press **Retake image** | Returns to the live preview |
| A6 | Capture again, press **Analyse plant** | Overlay appears, then a result card with a **Laptop webcam** badge |
| A7 | Press **Stop camera** | Preview clears and the camera indicator light goes out |
| A8 | Open **Detection History** | Newest record shows a **Webcam** camera icon |
| A9 | Filter by camera source **Laptop webcam** | Only webcam records listed |
| A10 | Open the record | Detail modal shows "Camera source: Laptop webcam" |

### Negative cases

| # | Step | Expected |
|---|---|---|
| A11 | Deny the permission prompt | Clear message explaining how to reset it in site settings; no crash |
| A12 | Open the dashboard at `http://<LAN-IP>:5173` | Webcam card explains the secure-context rule and names `http://localhost:5173` |
| A13 | Hold the camera with another app (Zoom) and press Start | "The camera is in use by another application" |
| A14 | Press **Capture image** immediately after Start, before a frame arrives | "The camera has not produced a frame yet" rather than a blank upload |
| A15 | Point at a blank wall and analyse | Result is **Unusable image**, with the quality issues listed - not a disease |

---

## 3. Camera source B - ESP32-CAM

### Without hardware

```bash
# Terminal 1
cd backend && python app.py

# Terminal 2
python scripts/simulate_esp32cam.py --device esp32-cam-01 --poll-interval 1

# Terminal 3
curl -X POST http://127.0.0.1:5000/api/capture -H "Content-Type: application/json" -d "{\"led\":true}"
```

The simulator speaks the real protocol. Verified result:

```
device online=True frame_size=SIMULATED (480x480) psram=True
capture HTTP 200 transport=push job=c6af54c2199c
camera_source=esp32_cam label=ESP32-CAM
record #22 status=uncertain conf=23.47%
stored file=esp32cam_20261110-082104_e49aae.jpg
db camera_source=esp32_cam (ESP32-CAM) device=esp32-cam-01
POST /api/device/status alias -> 200 Heartbeat recorded.
esp32-filtered history: 2 records, all esp32: True
```

Backend log for the same capture, showing the pull attempt falling back to push:

```
INFO  Capture requested for device 'esp32-cam-01' (led=True).
WARN  Pull capture failed (Could not reach the ESP32-CAM at http://...);
      trying the push fallback.
INFO  Capture job c6af54c2199c queued for device 'esp32-cam-01'.
INFO  Accepted 54675 bytes from 'esp32-cam-01' (raw transport, job=c6af54c2199c).
INFO  Capture job c6af54c2199c fulfilled with 54675 bytes.
INFO  Detection complete: camera=esp32_cam status=uncertain ...
```

This proves the protocol and backend. It proves nothing about the real camera's
optics, the LED wiring, or Wi-Fi behaviour - only hardware does that.

### With hardware

| # | Step | Expected |
|---|---|---|
| B1 | Flash the sketch, open Serial Monitor at 115200 | Banner, `Camera initialised`, Wi-Fi IP, `First heartbeat accepted` |
| B2 | Watch the LED at the end of setup | Two short blinks, confirming GPIO 4 wiring |
| B3 | Open `http://<board-ip>/` | Diagnostics page with frame size, PSRAM, capture counts |
| B4 | Open `http://<board-ip>/capture?led=1` | A JPEG downloads; the LED flashes during capture |
| B5 | Open `http://<board-ip>/status` | JSON telemetry |
| B6 | Open `http://<board-ip>/led?state=on` then `off` | LED switches; JSON confirms |
| B7 | Dashboard **Camera Management** | Device online, correct IP, RSSI, frame size, PSRAM |
| B8 | Press **Check connection** | Latency in milliseconds reported |
| B9 | Press **LED on** / **LED off** | Physical LED responds |
| B10 | Press **Capture image and analyse** | Result card with an **ESP32-CAM** badge |
| B11 | Change the IP field to a wrong address, Save | Saved, with "the camera did not respond" - the failure is reported, not hidden |
| B12 | Clear the IP field, Save | Falls back to heartbeat discovery; `effective_from` becomes `heartbeat` |
| B13 | Power off the board, wait 45s | Dashboard shows offline; troubleshooting explains the heartbeat age |
| B14 | Open **Detection History** | ESP32 records show the camera icon and device name |

### Negative cases

| # | Step | Expected |
|---|---|---|
| B15 | Unplug the camera ribbon and reset | Serial reports `Camera init failed`; `/capture` returns 503; the dashboard shows the error |
| B16 | Trigger a capture with the board powered off | 503 `DEVICE_UNREACHABLE` naming **both** the direct-request and queued-command failures |
| B17 | POST an empty body to `/api/device/upload` | 400 `INVALID_IMAGE` with power/ribbon/PSRAM guidance; the device row records the error |
| B18 | POST a JPEG with a valid SOI but no EOI | 400 `INVALID_IMAGE` identifying it as truncated |
| B19 | POST `Content-Type: text/plain` | 400 `VALIDATION_ERROR` naming the accepted transports |

---

## 4. Unified dashboard

| # | Step | Expected |
|---|---|---|
| C1 | Open **Camera Management** | Both cards visible with independent statuses |
| C2 | Switch between sources | The active panel changes; the other camera's state stays visible in the comparison card |
| C3 | Read the "One model, two cameras" header | Shared endpoint, model, input size, class count, threshold and quality-gate state |
| C4 | Analyse from the webcam, then from the ESP32-CAM | Both results render in the identical layout with the same fields |
| C5 | Open **Disease Detection** | Three-way selector: file upload, webcam, ESP32-CAM |
| C6 | Change the confidence threshold under Advanced settings | The new value is applied by whichever source you then use |
| C7 | Open **Detection History** | Camera column populated for every row |
| C8 | Filter by each camera source in turn | Only matching records returned |
| C9 | Open **Dashboard** and **Analytics** | Totals and the camera breakdown match the history count |
| C10 | Stop the backend and reload | "Backend not reachable" banner with the start command, on every page |

---

## 5. Diagnosis dashboard and PDF report

### Computer-vision discrimination

```bash
python scripts/test_leaf_analysis.py
```

Ten assertions over nine synthetic leaves - healthy, leaf spots, large blight
patches, yellowing, powdery coating, edge scorch, holes, rust and a blank wall.
Each must produce distinct symptoms and a distinct shortlist. This suite needs
no backend and no model; it tests `ml/leaf_analysis.py` and
`ml/condition_rules.py` directly, which is how the morphology-order and
JPEG-ringing bugs were caught.

### Manual walkthrough

| # | Step | Expected |
|---|---|---|
| D1 | Open **Disease Detection**, upload a leaf photo, press **Analyse plant** | Two-column dashboard: image and summary on the left, sections A-E on the right |
| D2 | Read the confidence indicator | A percentage **only** when the trained classifier was used and the result is validated; otherwise the qualitative level with "Qualitative - no calibrated probability" |
| D3 | Read **Plant Identification** | Species, how it was identified (declared / classifier / vision / unidentified), and the care profile when known |
| D4 | Read **Disease Detection** and **Possible Causes** | Candidates described as possibilities; causes grouped by category; non-disease explanations included |
| D5 | Read the two treatment cards | Organic always present. Chemical present **only** at `confident`; otherwise a stated withholding notice |
| D6 | Look for product names or dosages | None anywhere - active-ingredient classes only, each marked as needing verification against the label |
| D7 | Declare a species the classifier does not cover (Mango, Neem, Rose...) | Analysed normally; the sidebar states the 10-class classifier was excluded |
| D8 | Analyse a blank wall | **Unusable image** with the quality issues listed, not a disease |
| D9 | Press **Download report** | A PDF downloads named `plantguard-diagnosis-<species>-<id>-<date>.pdf` |
| D10 | Open the PDF | Ten sections mirroring the dashboard, with the confidence level, the "not a confirmed diagnosis" statement and the limitations repeated inside |
| D11 | Check the sidebar model panel | The model's **real** state - while untrained it says so plainly on every analysis |
| D12 | Press **Analyse another leaf** | Capture controls return; the previous result is cleared |

Step D11 matters most. The dashboard reports the shipped model as untrained
test mode because it is. Nothing in the UI prints a confidence figure the
model has not earned.

---

## 6. Model evaluation

```bash
python ml/evaluate.py
```

Writes to `ml/reports/`:

| File | Contents |
|---|---|
| `metrics.json` | Accuracy, top-3, macro/weighted precision-recall-F1, per class |
| `classification_report.json` | scikit-learn report |
| `confusion_matrix.csv` | Raw counts |
| `confusion_matrix.png` | Row-normalised heat map |
| `evaluation_summary.txt` | Printable summary |

The test split is rebuilt from the same random seed used in training, so the
score is computed on images the model never saw. Macro averages are reported
alongside weighted ones because a respectable weighted F1 can hide one class
the model never gets right.

The Analytics page reads these files directly. With no report present it says
so and prints the command to generate one, rather than showing zeros.

---

## 7. What is deliberately not automated

| Area | Why | Covered by |
|---|---|---|
| Browser camera capture | No camera in a headless test run | Procedures A1-A15 |
| Real ESP32-CAM optics, LED, Wi-Fi | Needs the physical board | Procedures B1-B19 |
| Visual appearance | Judgement, not assertion | Manual review |
| Model accuracy on field images | Needs field-captured ground truth | Stated as a limitation |

The published accuracy figure is measured on PlantVillage-style images: single
leaf, plain background, even lighting. It is an upper bound for field
conditions, not field accuracy.

---

## 8. Continuous verification

```bash
cd frontend && npx tsc -b && npm run build    # types and bundle
python scripts/smoke_test.py                  # API, exits non-zero on failure
```

Both are safe to run in CI. The smoke test needs a running backend and cleans
up the records it creates unless `--keep` is passed.
