/* =========================================================================
 * plant_disease_camera.ino
 * -------------------------------------------------------------------------
 * Firmware for the AI-Based Smart Plant Disease Detection system.
 *
 * Board : AI Thinker ESP32-CAM (OV2640)
 * LED   : White illumination LED on GPIO 4 (also the on-board flash LED)
 *
 * WHAT THIS FIRMWARE DOES
 * -----------------------
 * 1. Joins the configured Wi-Fi network and prints its IP over serial.
 * 2. Initialises the OV2640 camera.
 * 3. Serves three HTTP endpoints so the backend can pull from the board:
 *       GET /            - human-readable info page
 *       GET /status      - JSON telemetry
 *       GET /capture     - captures a frame and returns it as image/jpeg
 *       GET /led?state=on|off  - switches the white LED
 * 4. Sends a periodic heartbeat to the Flask backend
 *    (POST /api/device/register) so the dashboard knows the board is alive
 *    and learns its current DHCP address.
 * 5. Polls the backend (GET /api/device/command) for dashboard-triggered
 *    captures and pushes the resulting JPEG to POST /api/device/upload.
 *
 * WHY BOTH DIRECTIONS
 * -------------------
 * Pulling (step 3) is the fast path, but many networks block one device from
 * opening a connection to another (client isolation / guest Wi-Fi), and a
 * DHCP lease can change the board's address. The heartbeat plus command poll
 * (steps 4-5) only require the board to reach the server, which almost
 * always works. The backend tries the pull first and falls back to the queued
 * command automatically.
 *
 * REQUIRED ARDUINO IDE SETUP
 * --------------------------
 *   Boards Manager URL : https://espressif.github.io/arduino-esp32/package_esp32_index.json
 *   Board              : "AI Thinker ESP32-CAM"
 *   Partition Scheme   : "Huge APP (3MB No OTA/1MB SPIFFS)"
 *   PSRAM              : Enabled
 *   Upload Speed       : 115200
 *   Flash Frequency    : 80 MHz
 *
 * FLASHING
 * --------
 *   1. Wire the USB-to-TTL adapter: 5V->5V, GND->GND, TX->U0R, RX->U0T.
 *   2. Connect GPIO 0 to GND to enter bootloader mode.
 *   3. Press the on-board RESET button, then click Upload.
 *   4. When it finishes, DISCONNECT GPIO 0 from GND and press RESET again.
 *      Leaving GPIO 0 grounded keeps the board in bootloader mode and it will
 *      appear completely dead.
 *
 * Only these three settings normally need changing: WIFI_SSID, WIFI_PASSWORD
 * and FLASK_SERVER_IP (printed in the backend's startup banner).
 * ========================================================================= */

#include <WiFi.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "esp_timer.h"

/* =========================================================================
 * 1. USER CONFIGURATION
 * ========================================================================= */

/* ---- Wi-Fi ------------------------------------------------------------- */
#define WIFI_SSID            "YOUR_WIFI_SSID"
#define WIFI_PASSWORD        "YOUR_WIFI_PASSWORD"

/* ---- Flask backend ----------------------------------------------------- */
/* Use the "FLASK_SERVER_IP for the sketch" value printed by `python app.py`.
 * It must be the server's LAN address - 127.0.0.1 and "localhost" refer to
 * the ESP32 itself and will never work here.                              */
#define FLASK_SERVER_IP      "192.168.1.100"
#define FLASK_SERVER_PORT    5000

/* Logical name for this camera. Use a distinct value per board if you run
 * more than one; it is the key the backend stores in device_status.        */
#define DEVICE_NAME          "esp32-cam-01"

/* Optional shared secret. Leave empty unless DEVICE_API_KEY is set in the
 * backend's .env, in which case the two values must match exactly.         */
#define DEVICE_API_KEY       ""

/* ---- Camera ------------------------------------------------------------ */
/* Frame size. Larger means more detail but slower transfer and more RAM:
 *   FRAMESIZE_VGA  (640x480)  - most reliable on weak Wi-Fi
 *   FRAMESIZE_SVGA (800x600)  - good default with PSRAM
 *   FRAMESIZE_XGA  (1024x768) - needs PSRAM and a solid signal
 * The backend resizes to 224x224 for the model, so anything above SVGA
 * mainly costs transfer time rather than adding accuracy.                  */
#define CAMERA_FRAME_SIZE    FRAMESIZE_SVGA

/* JPEG quality: 10 (best) to 63 (worst). 10-12 is a good range for leaves. */
#define CAMERA_JPEG_QUALITY  12

/* ---- White LED --------------------------------------------------------- */
#define LED_PIN              4      /* GPIO 4 = on-board flash LED */
#define LED_ACTIVE_HIGH      true   /* true: HIGH switches the LED on */

/* Milliseconds to wait after switching the LED on before grabbing a frame,
 * so the sensor's auto-exposure and white balance settle. Too short and the
 * image comes out dark; this is the single most common cause of rejected
 * low-brightness captures.                                                 */
#define LED_SETTLE_MS        450

/* Frames discarded before the one that is kept. The OV2640 returns stale
 * buffers immediately after a lighting change.                             */
#define WARMUP_FRAMES        2

/* Retries for a failed frame grab. The first grab after power-up, or after a
 * brief brown-out, frequently returns NULL while the sensor re-initialises;
 * retrying costs a few hundred milliseconds and avoids reporting a capture
 * failure for a camera that is actually fine.                              */
#define CAPTURE_MAX_ATTEMPTS 3
#define CAPTURE_RETRY_DELAY_MS 180

/* A real SVGA leaf photograph is tens of kilobytes. Anything below this is a
 * partially-failed grab, so the firmware refuses to upload it rather than
 * letting the backend reject it after a pointless Wi-Fi transfer.          */
#define MIN_VALID_JPEG_BYTES 1024

/* ---- Timing ------------------------------------------------------------ */
#define HEARTBEAT_INTERVAL_MS   10000UL  /* must be < backend's offline threshold */
#define COMMAND_POLL_INTERVAL_MS 2000UL  /* dashboard capture responsiveness */
#define WIFI_RETRY_INTERVAL_MS  15000UL
#define HTTP_TIMEOUT_MS         15000

#define FIRMWARE_VERSION     "1.0.0"
#define SERIAL_BAUD          115200

/* =========================================================================
 * 2. AI THINKER ESP32-CAM PIN MAP  (do not change for this board)
 * ========================================================================= */

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

/* =========================================================================
 * 3. GLOBAL STATE
 * ========================================================================= */

WebServer server(80);

bool          cameraReady        = false;
bool          ledState           = false;
unsigned long bootMillis         = 0;
unsigned long lastHeartbeatMs    = 0;
unsigned long lastCommandPollMs  = 0;
unsigned long lastWifiAttemptMs  = 0;
unsigned long totalCaptures      = 0;
unsigned long failedCaptures     = 0;
String        lastError          = "";

/* Forward declarations.
 *
 * The Arduino IDE normally generates these automatically, but declaring them
 * explicitly keeps the sketch compilable as a plain .cpp file too (for
 * example under PlatformIO) and documents the call graph. */
bool initCamera();
String frameSizeName();
bool frameLooksValid(camera_fb_t *frame, String &reason);
camera_fb_t *captureFrame(bool useLed);
void connectWiFi();
void ensureWiFi();
void startWebServer();
String buildStatusJson();
bool sendHeartbeat();
bool uploadFrame(camera_fb_t *frame, const String &jobId);
bool captureAndUpload(const String &jobId, bool useLed);
void pollCommand();

/* =========================================================================
 * 4. SMALL HELPERS
 * ========================================================================= */

String backendUrl(const String &path) {
  return String("http://") + FLASK_SERVER_IP + ":" + String(FLASK_SERVER_PORT) + path;
}

/* Human-readable name of the frame size actually in use, reported in the
 * heartbeat so the dashboard can explain a low-resolution capture (a board
 * without PSRAM is forced down to a smaller frame). */
String frameSizeName() {
  sensor_t *sensor = esp_camera_sensor_get();
  framesize_t size = (sensor != NULL) ? sensor->status.framesize : CAMERA_FRAME_SIZE;

  switch (size) {
    case FRAMESIZE_QQVGA: return "QQVGA (160x120)";
    case FRAMESIZE_QVGA:  return "QVGA (320x240)";
    case FRAMESIZE_CIF:   return "CIF (400x296)";
    case FRAMESIZE_VGA:   return "VGA (640x480)";
    case FRAMESIZE_SVGA:  return "SVGA (800x600)";
    case FRAMESIZE_XGA:   return "XGA (1024x768)";
    case FRAMESIZE_SXGA:  return "SXGA (1280x1024)";
    case FRAMESIZE_UXGA:  return "UXGA (1600x1200)";
    default:              return "unknown";
  }
}

void applyDeviceHeaders(HTTPClient &http) {
  http.addHeader("X-Device-Name", DEVICE_NAME);
  if (strlen(DEVICE_API_KEY) > 0) {
    http.addHeader("X-Device-Key", DEVICE_API_KEY);
  }
}

void setLed(bool on) {
  ledState = on;
  digitalWrite(LED_PIN, (on == LED_ACTIVE_HIGH) ? HIGH : LOW);
}

/* Minimal JSON string-value extractor.
 *
 * The backend's replies are small and fixed in shape, so pulling one value
 * out by string search avoids adding an ArduinoJson dependency to the build.
 * It is not a general JSON parser and is only used on our own responses. */
String jsonFindString(const String &payload, const String &key) {
  String needle = "\"" + key + "\"";
  int keyIndex = payload.indexOf(needle);
  if (keyIndex < 0) return "";

  int colon = payload.indexOf(':', keyIndex + needle.length());
  if (colon < 0) return "";

  int firstQuote = payload.indexOf('"', colon);
  if (firstQuote < 0) return "";

  int secondQuote = payload.indexOf('"', firstQuote + 1);
  if (secondQuote < 0) return "";

  return payload.substring(firstQuote + 1, secondQuote);
}

bool jsonFindBool(const String &payload, const String &key, bool fallback) {
  String needle = "\"" + key + "\"";
  int keyIndex = payload.indexOf(needle);
  if (keyIndex < 0) return fallback;

  int colon = payload.indexOf(':', keyIndex + needle.length());
  if (colon < 0) return fallback;

  String tail = payload.substring(colon + 1, min((int)payload.length(), colon + 8));
  tail.trim();
  if (tail.startsWith("true"))  return true;
  if (tail.startsWith("false")) return false;
  return fallback;
}

/* =========================================================================
 * 5. CAMERA
 * ========================================================================= */

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  /* With PSRAM the frame buffer lives in external RAM, which allows larger
   * frames and double buffering. Without it, fall back to a smaller frame
   * that fits in internal RAM - otherwise init fails with ESP_ERR_NO_MEM. */
  if (psramFound()) {
    config.frame_size   = CAMERA_FRAME_SIZE;
    config.jpeg_quality = CAMERA_JPEG_QUALITY;
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    Serial.println("[CAM ] PSRAM found: using the configured frame size.");
  } else {
    config.frame_size   = FRAMESIZE_SVGA;
    config.jpeg_quality = 14;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
    Serial.println("[CAM ] No PSRAM: falling back to SVGA, single buffer.");
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM ] Camera init FAILED (0x%x).\n", err);
    Serial.println("[CAM ] Usual causes: insufficient power (needs 5V at ~500mA),");
    Serial.println("[CAM ] a loose camera ribbon, or PSRAM disabled in Tools.");
    lastError = "Camera init failed: 0x" + String(err, HEX);
    return false;
  }

  /* Sensor tuning for close-up leaf photography under the white LED. */
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor != NULL) {
    sensor->set_brightness(sensor, 0);
    sensor->set_contrast(sensor, 1);        /* slight boost helps lesion edges */
    sensor->set_saturation(sensor, 1);      /* colour matters for this task   */
    sensor->set_whitebal(sensor, 1);
    sensor->set_awb_gain(sensor, 1);
    sensor->set_exposure_ctrl(sensor, 1);
    sensor->set_aec2(sensor, 1);
    sensor->set_gain_ctrl(sensor, 1);
    sensor->set_lenc(sensor, 1);            /* lens shading correction        */
    sensor->set_vflip(sensor, 0);
    sensor->set_hmirror(sensor, 0);
  }

  Serial.println("[CAM ] Camera initialised.");
  return true;
}

/* Validate a grabbed frame before it is trusted.
 *
 * Three things can go wrong even when esp_camera_fb_get() returns non-NULL:
 * the buffer can be empty, it can be far too small to be a photograph, or it
 * can be missing the JPEG markers (which happens if the sensor handed back a
 * partially written buffer). Each is caught here so the firmware never puts a
 * broken image on the wire. */
bool frameLooksValid(camera_fb_t *frame, String &reason) {
  if (frame == NULL) {
    reason = "frame buffer pointer was NULL";
    return false;
  }
  if (frame->len == 0 || frame->buf == NULL) {
    reason = "frame buffer was empty (0 bytes)";
    return false;
  }
  if (frame->format != PIXFORMAT_JPEG) {
    reason = "sensor returned a non-JPEG pixel format";
    return false;
  }
  if (frame->len < MIN_VALID_JPEG_BYTES) {
    reason = "frame was only " + String((unsigned)frame->len) +
             " bytes, below the " + String(MIN_VALID_JPEG_BYTES) + " byte minimum";
    return false;
  }
  /* JPEG must start with SOI (FFD8) and end with EOI (FFD9). */
  if (!(frame->buf[0] == 0xFF && frame->buf[1] == 0xD8)) {
    reason = "missing JPEG start-of-image marker";
    return false;
  }
  if (!(frame->buf[frame->len - 2] == 0xFF && frame->buf[frame->len - 1] == 0xD9)) {
    reason = "missing JPEG end-of-image marker (frame truncated)";
    return false;
  }
  return true;
}

/* Capture a frame with the LED on, discarding warm-up frames first.
 *
 * Retries a failed or invalid grab up to CAPTURE_MAX_ATTEMPTS times. Returns
 * NULL only when every attempt failed, in which case nothing is uploaded and
 * the reason is recorded in lastError for the dashboard to display.
 *
 * The caller MUST return the buffer with esp_camera_fb_return(). */
camera_fb_t *captureFrame(bool useLed) {
  if (!cameraReady) {
    lastError = "Capture requested but the camera is not initialised.";
    Serial.println("[CAM ] Cannot capture: camera init failed at boot.");
    return NULL;
  }

  if (useLed) {
    setLed(true);
    delay(LED_SETTLE_MS);
  }

  camera_fb_t *frame = NULL;
  String reason = "";

  for (int attempt = 1; attempt <= CAPTURE_MAX_ATTEMPTS; attempt++) {
    /* Flush stale buffers so the kept frame reflects the current lighting.
     * The OV2640 keeps returning the pre-LED frame for a frame or two. */
    for (int i = 0; i < WARMUP_FRAMES; i++) {
      camera_fb_t *stale = esp_camera_fb_get();
      if (stale) esp_camera_fb_return(stale);
    }

    frame = esp_camera_fb_get();

    if (frameLooksValid(frame, reason)) {
      break;
    }

    Serial.printf("[CAM ] Attempt %d/%d rejected: %s\n",
                  attempt, CAPTURE_MAX_ATTEMPTS, reason.c_str());

    if (frame) {
      esp_camera_fb_return(frame);
      frame = NULL;
    }

    if (attempt < CAPTURE_MAX_ATTEMPTS) {
      delay(CAPTURE_RETRY_DELAY_MS);
    }
  }

  if (useLed) {
    setLed(false);
  }

  if (!frame) {
    failedCaptures++;
    lastError = "Frame grab failed after " + String(CAPTURE_MAX_ATTEMPTS) +
                " attempts: " + reason;
    Serial.println("[CAM ] CAPTURE FAILED - nothing will be uploaded.");
    Serial.println("[CAM ] Check: 5V supply able to deliver 500mA, camera ribbon");
    Serial.println("[CAM ] fully seated, and PSRAM enabled in Tools.");
    return NULL;
  }

  totalCaptures++;
  lastError = "";
  Serial.printf("[CAM ] Captured %u bytes (%ux%u), JPEG markers verified.\n",
                (unsigned)frame->len, frame->width, frame->height);
  return frame;
}

/* =========================================================================
 * 6. WI-FI
 * ========================================================================= */

void connectWiFi() {
  Serial.printf("[WIFI] Connecting to \"%s\"", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);              /* sleep adds latency to every request */
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 20000UL) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WIFI] Connected.");
    Serial.print  ("[WIFI] IP address  : ");
    Serial.println(WiFi.localIP());
    Serial.print  ("[WIFI] MAC address : ");
    Serial.println(WiFi.macAddress());
    Serial.printf ("[WIFI] Signal      : %d dBm\n", WiFi.RSSI());
    Serial.printf ("[WIFI] Camera page : http://%s/\n", WiFi.localIP().toString().c_str());
    lastError = "";
  } else {
    Serial.println("[WIFI] Connection FAILED.");
    Serial.println("[WIFI] Check the SSID/password, and that the network is 2.4 GHz -");
    Serial.println("[WIFI] the ESP32 cannot join a 5 GHz-only network.");
    lastError = "Wi-Fi connection failed.";
  }
}

void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiAttemptMs < WIFI_RETRY_INTERVAL_MS) return;

  lastWifiAttemptMs = millis();
  Serial.println("[WIFI] Connection lost, reconnecting...");
  WiFi.disconnect();
  connectWiFi();
}

/* =========================================================================
 * 7. LOCAL WEB SERVER (backend -> board, "pull" transport)
 * ========================================================================= */

String buildStatusJson() {
  String json = "{";
  json += "\"device_name\":\""      + String(DEVICE_NAME) + "\",";
  json += "\"firmware_version\":\"" + String(FIRMWARE_VERSION) + "\",";
  json += "\"camera_model\":\"AI-Thinker ESP32-CAM (OV2640)\",";
  json += "\"camera_ready\":"       + String(cameraReady ? "true" : "false") + ",";
  json += "\"ip_address\":\""       + WiFi.localIP().toString() + "\",";
  json += "\"mac_address\":\""      + WiFi.macAddress() + "\",";
  json += "\"wifi_ssid\":\""        + String(WIFI_SSID) + "\",";
  json += "\"wifi_rssi\":"          + String(WiFi.RSSI()) + ",";
  json += "\"led_state\":\""        + String(ledState ? "on" : "off") + "\",";
  json += "\"free_heap\":"          + String((unsigned long)ESP.getFreeHeap()) + ",";
  json += "\"frame_size\":\""       + frameSizeName() + "\",";
  json += "\"psram_found\":"        + String(psramFound() ? "true" : "false") + ",";
  json += "\"uptime_seconds\":"     + String((millis() - bootMillis) / 1000UL) + ",";
  json += "\"total_captures\":"     + String(totalCaptures) + ",";
  json += "\"failed_captures\":"    + String(failedCaptures) + ",";
  json += "\"last_error\":\""       + lastError + "\"";
  json += "}";
  return json;
}

void handleStatus() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", buildStatusJson());
}

void handleRoot() {
  String page = "<!doctype html><html><head><meta charset='utf-8'>";
  page += "<meta name='viewport' content='width=device-width,initial-scale=1'>";
  page += "<title>ESP32-CAM - PlantGuard AI</title><style>";
  page += "body{font-family:system-ui,sans-serif;background:#f6f7f6;color:#26332a;margin:0;padding:24px}";
  page += ".card{max-width:620px;margin:0 auto;background:#fff;border:1px solid #e3e8e4;border-radius:16px;padding:24px}";
  page += "h1{margin:0 0 4px;font-size:20px}code{background:#e3e8e4;padding:2px 6px;border-radius:4px}";
  page += "a.btn{display:inline-block;background:#16a34a;color:#fff;text-decoration:none;padding:10px 16px;border-radius:10px;margin:4px 6px 4px 0}";
  page += "table{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}";
  page += "td{padding:6px 0;border-bottom:1px solid #f0f0f0}td:first-child{color:#587055}";
  page += "</style></head><body><div class='card'>";
  page += "<h1>ESP32-CAM &middot; PlantGuard AI</h1>";
  page += "<p style='color:#587055;margin-top:0'>Plant disease detection imaging node</p>";
  page += "<a class='btn' href='/capture?led=1'>Capture (LED on)</a>";
  page += "<a class='btn' href='/capture?led=0'>Capture (no LED)</a>";
  page += "<a class='btn' href='/led?state=on'>LED on</a>";
  page += "<a class='btn' href='/led?state=off'>LED off</a>";
  page += "<a class='btn' href='/status'>JSON status</a>";
  page += "<table>";
  page += "<tr><td>Device</td><td>" + String(DEVICE_NAME) + "</td></tr>";
  page += "<tr><td>Firmware</td><td>" + String(FIRMWARE_VERSION) + "</td></tr>";
  page += "<tr><td>Camera</td><td>" + String(cameraReady ? "ready" : "NOT READY") + "</td></tr>";
  page += "<tr><td>IP address</td><td>" + WiFi.localIP().toString() + "</td></tr>";
  page += "<tr><td>Signal</td><td>" + String(WiFi.RSSI()) + " dBm</td></tr>";
  page += "<tr><td>Free heap</td><td>" + String((unsigned long)ESP.getFreeHeap()) + " bytes</td></tr>";
  page += "<tr><td>Frame size</td><td>" + frameSizeName() + "</td></tr>";
  page += "<tr><td>PSRAM</td><td>" + String(psramFound() ? "found" : "not found") + "</td></tr>";
  page += "<tr><td>Uptime</td><td>" + String((millis() - bootMillis) / 1000UL) + " s</td></tr>";
  page += "<tr><td>Captures</td><td>" + String(totalCaptures) + " ok / " + String(failedCaptures) + " failed</td></tr>";
  page += "<tr><td>Backend</td><td><code>" + backendUrl("") + "</code></td></tr>";
  page += "</table>";
  page += "<p style='font-size:13px;color:#75876f'>This page is for diagnostics. ";
  page += "Run detections from the dashboard so the result is classified and stored.</p>";
  page += "</div></body></html>";

  server.send(200, "text/html", page);
}

void handleLed() {
  String state = server.hasArg("state") ? server.arg("state") : "";
  state.toLowerCase();

  if (state != "on" && state != "off") {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(400, "application/json",
                "{\"error\":\"Use /led?state=on or /led?state=off\"}");
    return;
  }

  setLed(state == "on");
  Serial.printf("[LED ] Switched %s by HTTP request.\n", state.c_str());

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json",
              "{\"led_state\":\"" + state + "\",\"device_name\":\"" + DEVICE_NAME + "\"}");
}

void handleCapture() {
  bool useLed = true;
  if (server.hasArg("led")) {
    String value = server.arg("led");
    useLed = !(value == "0" || value == "false" || value == "off");
  }

  Serial.printf("[HTTP] /capture requested (led=%s).\n", useLed ? "on" : "off");

  camera_fb_t *frame = captureFrame(useLed);
  if (!frame) {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(503, "application/json",
                "{\"error\":\"Frame capture failed\",\"detail\":\"" + lastError + "\"}");
    return;
  }

  /* Stream the JPEG straight out of the frame buffer: copying it into a
   * String would need a second allocation the size of the image. */
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Content-Disposition", "inline; filename=leaf.jpg");
  server.sendHeader("X-Device-Name", DEVICE_NAME);
  server.setContentLength(frame->len);
  server.send(200, "image/jpeg", "");

  WiFiClient client = server.client();
  client.write(frame->buf, frame->len);

  esp_camera_fb_return(frame);
  Serial.println("[HTTP] Frame sent to the requester.");
}

void handleNotFound() {
  server.send(404, "application/json",
              "{\"error\":\"Unknown endpoint\",\"available\":[\"/\",\"/status\",\"/capture\",\"/led\"]}");
}

void startWebServer() {
  server.on("/",        HTTP_GET, handleRoot);
  server.on("/status",  HTTP_GET, handleStatus);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/led",     HTTP_GET, handleLed);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println("[HTTP] Web server listening on port 80.");
}

/* =========================================================================
 * 8. BACKEND COMMUNICATION (board -> backend, "push" transport)
 * ========================================================================= */

/* POST /api/device/register - heartbeat with telemetry.
 * The response may carry a queued capture command, which saves a round-trip
 * compared with waiting for the next poll. */
bool sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(client, backendUrl("/api/device/register"))) {
    Serial.println("[BEAT] Could not open a connection to the backend.");
    return false;
  }

  http.addHeader("Content-Type", "application/json");
  applyDeviceHeaders(http);

  int status = http.POST(buildStatusJson());

  if (status <= 0) {
    Serial.printf("[BEAT] Heartbeat failed: %s\n", http.errorToString(status).c_str());
    Serial.printf("[BEAT] Is the backend running at %s?\n", backendUrl("").c_str());
    http.end();
    return false;
  }

  String body = http.getString();
  http.end();

  if (status >= 400) {
    Serial.printf("[BEAT] Backend returned HTTP %d: %s\n", status, body.substring(0, 160).c_str());
    return false;
  }

  /* A capture command piggybacked on the heartbeat response. */
  if (body.indexOf("\"action\":\"capture\"") >= 0) {
    String jobId = jsonFindString(body, "job_id");
    bool useLed  = jsonFindBool(body, "led", true);
    Serial.printf("[BEAT] Capture command received with the heartbeat (job %s).\n", jobId.c_str());
    captureAndUpload(jobId, useLed);
  }
  return true;
}

/* POST /api/device/upload - push one JPEG to the backend.
 * `jobId` links the image to a dashboard capture request that is waiting for
 * it; pass an empty string for an unsolicited push. */
bool uploadFrame(camera_fb_t *frame, const String &jobId) {
  if (WiFi.status() != WL_CONNECTED) {
    lastError = "Cannot upload: Wi-Fi is not connected.";
    Serial.println("[UPLD] Skipped: Wi-Fi is down.");
    return false;
  }

  /* Re-check immediately before transmitting. captureFrame() already
   * validated the buffer, but this is the last point at which a bad frame can
   * be stopped, and uploading an empty body would make the backend report a
   * device fault for something the firmware could see locally. */
  String reason = "";
  if (!frameLooksValid(frame, reason)) {
    lastError = "Refused to upload an invalid frame: " + reason;
    Serial.printf("[UPLD] REFUSED to upload: %s\n", reason.c_str());
    return false;
  }

  String url = backendUrl("/api/device/upload") + "?device=" + String(DEVICE_NAME);
  if (jobId.length() > 0) {
    url += "&job_id=" + jobId;
  }

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(client, url)) {
    Serial.println("[UPLD] Could not open a connection to the backend.");
    return false;
  }

  /* Raw JPEG body. HTTPClient sets Content-Length from the buffer length, so
   * the backend reads exactly frame->len bytes and can detect a short read. */
  http.addHeader("Content-Type", "image/jpeg");
  applyDeviceHeaders(http);

  Serial.printf("[UPLD] Uploading %u bytes to %s\n", (unsigned)frame->len, url.c_str());
  unsigned long startedAt = millis();

  int status = http.POST(frame->buf, frame->len);
  String body = (status > 0) ? http.getString() : String("");
  http.end();

  if (status <= 0) {
    Serial.printf("[UPLD] Upload FAILED: %s\n", http.errorToString(status).c_str());
    lastError = "Upload failed: " + http.errorToString(status);
    return false;
  }

  Serial.printf("[UPLD] HTTP %d in %lu ms.\n", status, millis() - startedAt);

  if (status >= 400) {
    Serial.printf("[UPLD] Backend rejected the image: %s\n", body.substring(0, 220).c_str());
    lastError = "Backend rejected the upload (HTTP " + String(status) + ")";
    return false;
  }

  /* The backend echoes the prediction for an unsolicited push, which makes the
   * serial log a complete record of what the board did. */
  String label = jsonFindString(body, "display_label");
  if (label.length() > 0) {
    Serial.printf("[UPLD] Result: %s\n", label.c_str());
  }
  lastError = "";
  return true;
}

/* Capture a frame and push it, always returning the frame buffer. */
bool captureAndUpload(const String &jobId, bool useLed) {
  camera_fb_t *frame = captureFrame(useLed);
  if (!frame) {
    Serial.println("[CMD ] Capture failed; nothing was uploaded.");
    return false;
  }

  bool ok = uploadFrame(frame, jobId);
  esp_camera_fb_return(frame);
  return ok;
}

/* GET /api/device/command - ask whether the dashboard wants an image. */
void pollCommand() {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(5000);

  String url = backendUrl("/api/device/command") + "?device=" + String(DEVICE_NAME);
  if (!http.begin(client, url)) return;

  applyDeviceHeaders(http);
  int status = http.GET();

  if (status != 200) {
    http.end();
    return;   /* stay quiet: this runs every couple of seconds */
  }

  String body = http.getString();
  http.end();

  if (body.indexOf("\"action\":\"capture\"") < 0) return;

  String jobId = jsonFindString(body, "job_id");
  bool useLed  = jsonFindBool(body, "led", true);

  Serial.printf("[CMD ] Dashboard requested a capture (job %s, led=%s).\n",
                jobId.c_str(), useLed ? "on" : "off");
  captureAndUpload(jobId, useLed);
}

/* =========================================================================
 * 9. SETUP / LOOP
 * ========================================================================= */

void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setDebugOutput(false);
  delay(400);
  bootMillis = millis();

  Serial.println();
  Serial.println("==========================================================");
  Serial.println("  PlantGuard AI - ESP32-CAM imaging node");
  Serial.printf ("  Firmware %s | Device %s\n", FIRMWARE_VERSION, DEVICE_NAME);
  Serial.println("==========================================================");

  pinMode(LED_PIN, OUTPUT);
  setLed(false);

  cameraReady = initCamera();

  connectWiFi();

  if (WiFi.status() == WL_CONNECTED) {
    startWebServer();

    Serial.println("----------------------------------------------------------");
    Serial.printf ("  Camera page : http://%s/\n", WiFi.localIP().toString().c_str());
    Serial.printf ("  Capture URL : http://%s/capture\n", WiFi.localIP().toString().c_str());
    Serial.printf ("  Backend     : %s\n", backendUrl("").c_str());
    Serial.println("----------------------------------------------------------");

    if (sendHeartbeat()) {
      Serial.println("[BEAT] First heartbeat accepted - the dashboard now shows this device.");
    } else {
      Serial.println("[BEAT] First heartbeat failed. Check FLASK_SERVER_IP and that the");
      Serial.println("[BEAT] backend is running and reachable from this network.");
    }
    lastHeartbeatMs = millis();
  }

  /* Two short blinks: setup finished. Visible even with no serial attached. */
  for (int i = 0; i < 2; i++) {
    setLed(true);  delay(120);
    setLed(false); delay(120);
  }

  if (!cameraReady) {
    Serial.println("[WARN] Running WITHOUT a working camera. /capture will return 503.");
  }
}

void loop() {
  server.handleClient();
  ensureWiFi();

  unsigned long now = millis();

  if (now - lastCommandPollMs >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPollMs = now;
    pollCommand();
  }

  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    sendHeartbeat();
  }

  delay(10);   /* yield to the Wi-Fi and TCP/IP tasks */
}
