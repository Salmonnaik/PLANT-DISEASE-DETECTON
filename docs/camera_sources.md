# Camera Sources

The system supports three ways to get a leaf image into the model. All three
end at the same endpoint and are processed identically; only the recorded
`camera_source` differs.

| Source | `camera_source` | Acquired by | Endpoint |
|---|---|---|---|
| Laptop / USB webcam | `laptop_webcam` | The browser (MediaDevices + canvas) | `POST /api/predict` |
| ESP32-CAM (OV2640) | `esp32_cam` | The backend over Wi-Fi, or pushed by the board | `POST /api/capture`, `POST /api/device/upload` |
| Existing image file | `file_upload` | The browser file picker | `POST /api/predict` |

---

## 1. One pipeline, three entry points

```
   Laptop webcam                    ESP32-CAM
   -------------                    ---------
   navigator.mediaDevices           OV2640 sensor
        |                                |
   <video> preview                  white LED on, exposure settles
        |                                |
   <canvas>.drawImage()             esp_camera_fb_get()
        |                                |
   canvas.toBlob('image/jpeg')      JPEG in PSRAM frame buffer
        |                                |
   multipart POST                    raw JPEG body over Wi-Fi
        |                                |
        +----------------+---------------+
                         |
                  Flask backend
                         |
          +--------------v--------------+
          |  SHARED PIPELINE            |
          |  1. validate_image_bytes()  |  magic bytes, size, JPEG markers, decode
          |  2. assess_image_quality()  |  sharpness, exposure, contrast, leaf pixels
          |  3. preprocess_for_model()  |  resize 224x224, in-model rescaling
          |  4. model.predict()         |  MobileNetV2 softmax
          |  5. confidence threshold    |  below it -> "uncertain", no disease named
          |  6. SQLite insert           |  + camera_source
          +--------------+--------------+
                         |
                 identical JSON response
```

The smoke test asserts this directly: the same image bytes submitted as
`laptop_webcam` and as `file_upload` must return the same predicted class and
the same confidence to within 1e-6. If the two paths ever diverge, that check
fails.

What the `camera_source` value does **not** affect: preprocessing, image size,
normalisation, class labels, model weights, or the confidence threshold.
What it does affect: the filename prefix of the stored image, the badge shown
in the UI, and the history/analytics filters.

---

## 2. Laptop webcam

### Requirements

* A browser with MediaDevices support (Chrome, Edge, Firefox, Safari).
* Camera permission granted to the page.
* **A secure context.** This is the one that catches people out.

### The secure-context rule

Browsers only expose `navigator.mediaDevices` on a secure origin. The practical
consequences:

| URL used to open the dashboard | Webcam works? |
|---|---|
| `http://localhost:5173` | Yes - localhost is treated as secure |
| `http://127.0.0.1:5173` | Yes |
| `http://192.168.1.42:5173` | **No** - plain HTTP on a remote host |
| `https://...` | Yes |

If you open the dashboard from another device on the network over plain HTTP,
the Camera Management page shows a clear explanation rather than a silent
failure. Either use the ESP32-CAM from that machine, or put the dashboard
behind HTTPS.

### Using it

1. Open **Camera Management** (or **Disease Detection**) in the dashboard.
2. Select **Laptop webcam**.
3. Press **Start camera**. The browser asks for permission the first time.
4. Frame one leaf inside the dashed guide and press **Capture image**.
5. Review the still. Press **Retake image** if the leaf is cut off or blurred.
6. Press **Analyse plant**.

Capture and analysis are deliberately two steps: a live frame is easy to get
wrong, and reviewing the still costs less than an inference pass on a bad image.

### Capture settings

Set in `frontend/src/hooks/useWebcam.ts`:

| Constant | Value | Why |
|---|---|---|
| `VIDEO_CONSTRAINTS` | 1280x720 `ideal` | The model resizes to 224x224, so a larger frame only costs encode and upload time. `ideal` (not `exact`) lets the browser fall back rather than fail. |
| `CAPTURE_QUALITY` | 0.92 | Keeps leaf texture without bloating the upload. |

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Webcam capture is not available here" | Insecure context. Use `http://localhost:5173`. |
| "Camera permission was denied" | Reset the permission in the browser's site settings, reload, start again. |
| "The camera is in use by another application" | Close Zoom, Teams, OBS, or any other app holding the device. |
| "No camera was found" | Connect a webcam, then press the refresh button next to the camera picker. |
| Preview is black but no error | Some laptops have a physical privacy shutter or a function-key camera disable. |
| "The camera has not produced a frame yet" | The stream opened but no frame arrived. Wait a second and capture again. |

---

## 3. ESP32-CAM

### Configuring the address

The backend resolves the camera's address in this order, and the Camera
Management page shows which one won:

1. **Dashboard setting** - typed into the IP field, stored in the `app_settings`
   table. Survives a restart and outranks everything else, because an operator
   who just corrected the address expects it to take effect immediately.
2. **`ESP32_CAM_IP` in `.env`** - the deployment default.
3. **Heartbeat discovery** - the address the board last reported. This is what
   makes the system work on a DHCP network where the IP changes between
   sessions, and why `ESP32_CAM_IP` can be left empty.

To set it from the dashboard: **Camera Management -> ESP32-CAM -> Camera IP
address**, enter the address from the board's serial monitor, press **Save**.
The backend probes it immediately and reports whether it answered. Clear the
field and save to fall back to `.env` or discovery.

### Two capture transports

The backend tries them in order, and a failure reports both reasons:

**Pull (preferred).** `GET http://<cam-ip>/capture` returns the JPEG in the
response body. Lowest latency, fully synchronous, but it needs the camera to be
directly reachable from the server.

**Push fallback.** If the pull fails, the backend queues a capture job. The
firmware polls `GET /api/device/command` every two seconds, sees the job,
captures, and POSTs the JPEG to `/api/device/upload?job_id=...`. The waiting
request is released by a `threading.Event` as soon as the bytes arrive. This
works on client-isolated or guest Wi-Fi where the server cannot open a
connection to the board.

Disable the fallback with `ENABLE_PUSH_CAPTURE_FALLBACK=false` if you want pull
failures to surface immediately.

### Firmware settings

In `esp32cam/plant_disease_camera.ino`:

| Setting | Default | Notes |
|---|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | - | Must be a 2.4 GHz network; the ESP32 cannot join 5 GHz. |
| `FLASK_SERVER_IP` | `192.168.1.100` | Use the value the backend prints as "FLASK_SERVER_IP for the sketch". Never `127.0.0.1`. |
| `FLASK_SERVER_PORT` | `5000` | |
| `DEVICE_NAME` | `esp32-cam-01` | Must match `ESP32_CAM_NAME` in `.env`. |
| `DEVICE_API_KEY` | empty | Set it in both places to require `X-Device-Key` on firmware endpoints. |
| `CAMERA_FRAME_SIZE` | `FRAMESIZE_SVGA` | Drop to `FRAMESIZE_VGA` on a weak signal. |
| `CAMERA_JPEG_QUALITY` | `12` | 10 = best, 63 = worst. |
| `LED_SETTLE_MS` | `450` | Delay after the LED switches on, before the frame is grabbed. |
| `HEARTBEAT_INTERVAL_MS` | `10000` | Must stay well below `ESP32_OFFLINE_AFTER_SECONDS` (45s). |

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Serial shows `Camera init failed (0x...)` | Power first: the module needs 5V at ~500 mA and browns out on a weak USB port. Then reseat the ribbon cable, and confirm PSRAM is enabled in Tools. |
| Board appears completely dead after flashing | GPIO 0 is still grounded. Disconnect it and press RESET. |
| Wi-Fi never connects | 5 GHz network, or a typo in the credentials. Check the serial log. |
| `Heartbeat failed` in serial | `FLASK_SERVER_IP` is wrong, the backend is not running, or a firewall is blocking port 5000. |
| Dashboard shows offline but serial looks fine | The heartbeat is reaching a *different* backend, or `DEVICE_NAME` does not match `ESP32_CAM_NAME`. |
| `400 INVALID_IMAGE - empty body` | The frame grab failed. The firmware retries three times before giving up; persistent failure is almost always power. |
| `400 INVALID_IMAGE - truncated JPEG` | The transfer was cut short. Reduce `CAMERA_FRAME_SIZE` and check the supply. |
| Images are dark | Increase `LED_SETTLE_MS`, or move the LED closer. |
| Images are washed out | The LED is too close. Move it back or add series resistance. |

---

## 4. File upload

Always available, needs no hardware, and is the quickest way to sanity-check a
newly trained model against known images. Recorded as `file_upload` rather than
as a camera capture, so the history stays an accurate record of provenance -
even when the webcam panel happens to be open.

---

## 5. Backend configuration

In `.env`:

```ini
ENABLE_WEBCAM_SOURCE=true      # show the webcam option in the dashboard
ENABLE_ESP32_SOURCE=true       # show the ESP32-CAM option
DEFAULT_CAMERA_SOURCE=file_upload
```

Disabling a source hides it from the selector. It does not block the API: a
`camera_source` value is validated against `CAMERA_SOURCES` in `config.py`,
which lists all three regardless, so existing records stay queryable.

---

## 6. Relevant API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/cameras` | Describe every source, its state, and the shared pipeline settings. `?ping=true` also probes the ESP32-CAM. |
| `POST` | `/api/predict` | Classify an image. Send `camera_source` to label it. |
| `POST` | `/api/capture` | Ask the backend to capture from the ESP32-CAM, then classify. |
| `GET` | `/api/device/config` | The effective camera address and where it came from. |
| `POST` | `/api/device/config` | Save or clear the dashboard-configured address. |
| `GET` | `/api/history?camera_source=...` | Filter history by camera. |
| `GET` | `/api/stats` | Includes a `camera_sources` breakdown. |
