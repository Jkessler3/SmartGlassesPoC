# Smart Glasses PoC - Dual Camera + ESP32 Record/IR Control

This repository contains a Windows-first proof of concept for:
- Capturing and displaying two synchronized video feeds on a PC
- A simple GUI with Record, IR, Brightness, camera scan/apply, and ESP32 connect/disconnect
- An ESP32-S3 controller with a physical record button, IR illumination control, and a red REC indicator LED

This is an engineering prototype focused on data capture and control flow, not industrial design.

## Hardware

PC-side:
- World camera: UVC webcam
- Eye camera: OV9281 mono global shutter UVC camera or similar

ESP32 controller:
- Seeed XIAO ESP32-S3
- IR LEDs with current limiting resistors
- N-MOSFET low-side switch for IR LEDs
- Red LED for REC indicator on `REC_LED_PIN`
- Momentary pushbutton for record toggle

## Folder Layout

SmartGlassesPoC/
- `dual_cam_gui_safe.py`
- `requirements.txt`
- `INSTALL.bat`
- `RUN.bat`
- `firmware/esp32_rec_ir_control/esp32_rec_ir_control.ino`
- `out/`

## Installation

Windows:
1. Install Python 3.12 or 3.13.
2. Run `INSTALL.bat`.
3. Run `RUN.bat`.

Dependencies:
- `opencv-python`
- `numpy`
- `pyserial`

## Running

1. Plug in both UVC cameras.
2. Plug in the ESP32 over USB.
3. Close Arduino Serial Monitor and Serial Plotter if they are open.
4. Run `RUN.bat`.

Windows/OpenCV can also be launched directly:
- `python dual_cam_gui_safe.py --camera-backend opencv`

Raspberry Pi OS Bookworm/Picamera2 launch:
- `python3 dual_cam_gui_safe.py --camera-backend picamera2 --outdir ~/poc_out`

SSH/WiFi camera preview from the Pi:
- `python3 scripts/pi_wifi_stream.py --width 640 --height 480 --fps 15`
- Open `http://<pi-ip-address>:8000` on the Windows PC.

See `TARGETS.md` for the Pi Zero 2 W and CM5 target plan.

In the GUI:
- `Scan Cameras` pauses capture, scans available cameras, auto-picks world and eye, then reopens capture.
- `Apply Cameras` closes and reopens capture with the selected indices.
- `Find ESP32` probes likely serial devices and looks for `XIAO_REC_CTRL`.
- `Connect` opens the selected COM port and listens for the ESP32 boot/status output.
- `Record` toggles recording in the GUI and sends `REC=1` or `REC=0` to the ESP32.
- `IR ON/OFF` sends `IR=1` or `IR=0`.
- `Brightness` sends `B=0..255`.
- `Quit` disconnects serial, stops recording, stops camera workers, and closes the UI.

The live preview appears in an OpenCV window named `World | Eye`.

## Output Files

The current app writes recordings to:
- `C:\poc_out\poc_world_eye_YYYYMMDD_HHMMSS.avi`
- `C:\poc_out\poc_world_eye_YYYYMMDD_HHMMSS.csv`

The CSV contains:
- `frame_idx`
- `world_ts_ns`
- `eye_ts_ns`
- `dt_ms`

## ESP32 Firmware

Firmware sketch:
- `firmware/esp32_rec_ir_control/esp32_rec_ir_control.ino`

Serial commands accepted by the firmware:
- `ID?`
- `STATUS?`
- `REC=1` or `REC=0`
- `IR=1` or `IR=0`
- `B=0..255`

Serial output from the firmware includes:
- `ID=XIAO_REC_CTRL ...`
- `REC=1` or `REC=0`
- `IR=1` or `IR=0`
- `B=###`

Notes:
- The GUI parses inbound `REC=`, `IR=`, and `B=` updates and keeps its controls in sync.
- The app does not poll `STATUS?` automatically; it relies on the ESP32 boot/status lines plus normal control traffic.
- `REC=1` in firmware also forces `IR=1`.
- The firmware now blinks the REC LED twice on boot as a quick wiring check.
- If the REC LED logic is inverted for your wiring, flip `REC_LED_ACTIVE_HIGH` in `esp32_rec_ir_control.ino`.

## Verification Checklist

Recommended next manual checks:
1. Connect the ESP32 and click `Record` in the GUI. Confirm the red REC LED follows the GUI state.
2. Press the hardware record button. Confirm the GUI record state updates and recording starts or stops.
3. Click `Apply Cameras` twice in a row. Confirm preview recovers cleanly both times without freezing or spiking CPU.
4. Run `Scan Cameras`, then `Apply Cameras`, and confirm world/eye preview still updates normally.
5. Adjust brightness and confirm the device and GUI stay in sync.

## Troubleshooting

COM port problems:
- Close Arduino Serial Monitor and Plotter.
- Unplug and reconnect the ESP32.
- Use `Find ESP32`, or enter the COM port manually and click `Connect`.

Camera problems:
- Try different USB ports.
- Avoid low-power hubs.
- Stop recording before scanning or applying cameras.
- Re-run `Scan Cameras` if indices changed.
