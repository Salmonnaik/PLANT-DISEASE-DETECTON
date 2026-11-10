# Circuit and Wiring Diagram

Hardware for the ESP32-CAM imaging node. The laptop webcam source needs no
wiring at all.

---

## 1. Bill of materials

| # | Component | Specification | Purpose |
|---|---|---|---|
| 1 | ESP32-CAM | AI Thinker, with OV2640 | Capture and Wi-Fi transmission |
| 2 | White LED | 5 mm, ~3.0-3.4 V forward voltage | Illumination for repeatable exposure |
| 3 | Resistor | 220 Ω, 1/4 W | Limits LED current to a safe ~15 mA |
| 4 | USB-to-TTL adapter | CP2102, FT232 or CH340 | Programming (the ESP32-CAM has no USB port) |
| 5 | Power supply | 5 V, **1 A or more** | The module browns out below ~500 mA |
| 6 | Jumper wires | Female-to-female | Connections |
| 7 | Breadboard | Optional | Mounting the LED and resistor |

> **The single most common failure is power.** A laptop USB port shared with
> other devices frequently cannot supply the peak current the ESP32-CAM draws
> when the Wi-Fi radio transmits while the camera is active. The symptom is
> `Camera init failed` or random reboots - not an obvious power error. Use a
> dedicated 5 V 1 A supply or a powered hub.

---

## 2. White LED circuit

```
            ESP32-CAM
          +-----------+
          |           |
          |   GPIO 4  o-----------[ 220 Ω ]-----------+
          |           |                              |
          |           |                            __|__
          |           |                            \   /   White LED
          |           |                             \ /    (5 mm)
          |           |                              V
          |           |                              |
          |     GND   o------------------------------+
          |           |
          +-----------+
```

Current limiting, for the record:

```
  I = (V_supply - V_forward) / R
    = (3.3 V - 3.0 V) / 220 Ω        [GPIO drives 3.3 V]
    ~ 1.4 mA   with a 3.0 V white LED
```

A white LED's forward voltage sits close to the 3.3 V GPIO rail, so the
achievable current is modest and the LED will be dim but adequate at close
range. For brighter illumination, drive the LED from the 5 V rail through a
transistor switched by GPIO 4, with a 100 Ω resistor:

```
                            +5V
                             |
                          [ 100 Ω ]
                             |
                           __|__
                           \   /  White LED
                            \ /
                             V
                             |
                             +------------------+
                             |                  |
                    Collector |              (BC547 / 2N2222)
   GPIO 4 ---[ 1 kΩ ]--- Base |
                             |
                     Emitter |
                             |
                            GND
```

> **GPIO 4 also drives the on-board flash LED.** The module therefore works
> with no external LED at all - the built-in one is bright but harsh and
> unevenly distributed. An external LED positioned to the side gives flatter,
> more repeatable illumination, which matters more for consistent predictions
> than raw brightness.

---

## 3. Programming connections

Wire the USB-to-TTL adapter only while flashing.

```
   USB-to-TTL                       ESP32-CAM
  +-----------+                   +-----------+
  |       5V  o-------------------o 5V        |
  |      GND  o-------------------o GND       |
  |       TX  o-------------------o U0R (RX)  |
  |       RX  o-------------------o U0T (TX)  |
  +-----------+                   |           |
                                  | GPIO 0  o-+
                                  |           | |  connect to GND
                                  |   GND   o-+ |  ONLY while flashing
                                  +-----------+
```

| USB-TTL pin | ESP32-CAM pin | Note |
|---|---|---|
| 5V | 5V | Do **not** also connect 3.3V |
| GND | GND | Common ground |
| TX | U0R (RX) | Crossed over |
| RX | U0T (TX) | Crossed over |
| - | GPIO 0 ↔ GND | Bootloader mode, **remove after flashing** |

Set the adapter to **3.3 V logic** if it has a voltage selector jumper. 5 V
logic on the ESP32's UART pins can damage the module.

### Flashing procedure

1. Connect GPIO 0 to GND.
2. Press the on-board **RESET** button.
3. In the Arduino IDE, select **AI Thinker ESP32-CAM**, then **Upload**.
4. Wait for `Hard resetting via RTS pin...`.
5. **Disconnect GPIO 0 from GND.**
6. Press **RESET** again.

Skipping step 5 leaves the board in bootloader mode, where it appears
completely dead - no serial output, no Wi-Fi.

---

## 4. Pin reference

### Used by this project

| Signal | Pin | Direction | Note |
|---|---|---|---|
| White LED | GPIO 4 | Output | Shared with the on-board flash LED |
| Programming RX | U0R / GPIO 3 | Input | USB-TTL TX |
| Programming TX | U0T / GPIO 1 | Output | USB-TTL RX |
| Bootloader select | GPIO 0 | Input | GND while flashing only |
| Power | 5V | - | Regulated 5 V, 1 A+ |
| Ground | GND | - | |

### Consumed by the camera (do not reuse)

The OV2640 occupies most of the usable GPIO. These are set in the sketch and
must not be changed for an AI Thinker board:

| Function | Pin | Function | Pin |
|---|---|---|---|
| PWDN | GPIO 32 | Y4 (D2) | GPIO 19 |
| RESET | not connected | Y3 (D1) | GPIO 18 |
| XCLK | GPIO 0 | Y2 (D0) | GPIO 5 |
| SIOD (SDA) | GPIO 26 | VSYNC | GPIO 25 |
| SIOC (SCL) | GPIO 27 | HREF | GPIO 23 |
| Y9 (D7) | GPIO 35 | PCLK | GPIO 22 |
| Y8 (D6) | GPIO 34 | | |
| Y7 (D5) | GPIO 39 | | |
| Y6 (D4) | GPIO 36 | | |
| Y5 (D3) | GPIO 21 | | |

Note that **XCLK shares GPIO 0** with the bootloader select pin. This is normal
for the AI Thinker design and is why GPIO 0 must be free during normal
operation.

---

## 5. Physical arrangement for imaging

```
            [ White LED ]                 <- offset ~30-45 deg from the lens axis
                  \                          to light the leaf without glare
                   \
                    \
                     v
   [ ESP32-CAM ] --------> [  LEAF  ]     <- 10-15 cm, leaf filling the frame
         |                      |
         |                 plain, non-reflective
         |                 background (matte card)
      Wi-Fi
         |
         v
    Flask backend
```

Guidelines that affect accuracy more than any software setting:

* **Distance 10-15 cm.** The OV2640 has a fixed focus optimised for roughly
  this range; closer than ~8 cm is soft.
* **One leaf, filling most of the frame.** The model was trained on single-leaf
  images. A whole plant breaks that assumption.
* **Plain matte background.** A glossy surface reflects the LED into the lens.
* **LED offset, not head-on.** Direct frontal light produces a specular hotspot
  that the quality gate may reject as over-exposed.
* **Fixed mounting.** A stand or clamp makes repeat scans comparable, which is
  the whole reason for using a fixed camera rather than a phone.

---

## 6. Verification checklist

After wiring and flashing, open the serial monitor at **115200 baud** and press
RESET. A healthy board prints:

```
==========================================================
  PlantGuard AI - ESP32-CAM imaging node
  Firmware 1.0.0 | Device esp32-cam-01
==========================================================
[CAM ] PSRAM found: using the configured frame size.
[CAM ] Camera initialised.
[WIFI] Connecting to "YourNetwork"....
[WIFI] Connected.
[WIFI] IP address  : 192.168.1.50
[WIFI] Signal      : -58 dBm
[HTTP] Web server listening on port 80.
[BEAT] First heartbeat accepted - the dashboard now shows this device.
```

Then verify, in order:

1. The two LED blinks at the end of setup - confirms GPIO 4 wiring.
2. `http://<board-ip>/` in a browser - the diagnostics page loads.
3. `http://<board-ip>/capture?led=1` - returns a JPEG, LED flashes.
4. The dashboard's **Camera Management** page shows the device online.
5. **Capture image and analyse** returns a prediction.

If step 2 fails but the serial log shows an IP, the server and board are on
different subnets or client isolation is enabled on the access point - the push
fallback will still work.
