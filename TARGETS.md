# Target Plan

This project currently supports a Windows/OpenCV proof of concept and has an
early Raspberry Pi camera backend for Pi OS Bookworm/Picamera2.

## Target Roles

### Windows PC

Use this as the known-good development and capture-control baseline.

```powershell
python dual_cam_gui_safe.py --camera-backend opencv
```

The OpenCV backend is also selected automatically on Windows.

### Raspberry Pi Zero 2 W

Use this as the lean Raspberry Pi target. It is useful for validating:

- Raspberry Pi OS Bookworm setup
- Picamera2 camera capture
- ESP32 serial control
- reduced-resolution recording

The Pi Zero 2 W is not the preferred final dual-camera recorder. Keep tests
small at first: one camera, then two cameras only if the attached hardware and
throughput are stable.

Install the camera stack from Raspberry Pi OS packages:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-serial
```

For a fresh Pi, the one-command setup path is:

```bash
curl -fsSL https://raw.githubusercontent.com/Jkessler3/SmartGlassesPoC/main/scripts/setup_pi.sh | sudo bash
```

Useful setup overrides:

```bash
curl -fsSL https://raw.githubusercontent.com/Jkessler3/SmartGlassesPoC/main/scripts/setup_pi.sh | sudo GLASSES_NAME=glasses-right STREAM_FPS=10 bash
```

GPIO-enabled install:

```bash
curl -fsSL https://raw.githubusercontent.com/Jkessler3/SmartGlassesPoC/main/scripts/setup_pi.sh | sudo ENABLE_GPIO=1 BUTTON_PIN=17 LED_PIN=27 bash
```

Verify the camera stack before running the GUI:

```bash
rpicam-hello --list-cameras
```

For SSH/headless validation, run the repo smoke test first:

```bash
python3 scripts/pi_smoke_test.py --capture --probe-serial
```

To view the camera over WiFi from the Windows PC without VNC, start the MJPEG
preview server on the Pi:

```bash
python3 scripts/pi_wifi_stream.py --name glasses-left --width 640 --height 480 --fps 15
```

The stream server also supports Pi-side snapshots:

```bash
curl -X POST http://localhost:8000/capture
```

Snapshots are saved under `~/poc_out/snapshots` unless `--snapshot-dir` is
provided.

Pi-side recording endpoints:

```bash
curl -X POST http://localhost:8000/record/start
curl http://localhost:8000/record/status
curl -X POST http://localhost:8000/record/stop
```

Recordings are saved under `~/poc_out/recordings` unless `--record-dir` is
provided. GPIO is disabled by default. To enable a physical record button and
LED, start the streamer with:

```bash
python3 scripts/pi_wifi_stream.py --name glasses-left --width 640 --height 480 --fps 15 --input-order bgr --enable-gpio --button-pin 17 --led-pin 27
```

Autostart template:

```bash
sudo cp systemd/smart-glasses-stream.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smart-glasses-stream.service
sudo systemctl start smart-glasses-stream.service
```

The included template assumes the Pi username is `user` and the repo is at
`/home/user/SmartGlassesPoC`. Edit it first if your glasses name, pins, or
stream settings differ.

If red and blue look swapped in the browser, restart the stream with:

```bash
python3 scripts/pi_wifi_stream.py --width 640 --height 480 --fps 15 --input-order bgr
```

Find the Pi address:

```bash
hostname -I
```

Then open this from Windows:

```text
http://<pi-ip-address>:8000
```

The Windows GUI can also consume the same stream directly:

```powershell
python dual_cam_gui_safe.py --camera-backend mjpeg
```

Click `Find Glasses`, choose the right named Pi device, and click
`Connect Stream`.

Click `Snapshot` in MJPEG mode to save the latest frame on the Pi and display
the returned filename/path in the status line.

Click `Record` in MJPEG mode to call the Pi `/record/start` and `/record/stop`
endpoints. OpenCV/local USB mode still records locally in the GUI.

Manual connection still works:

```powershell
python dual_cam_gui_safe.py --camera-backend mjpeg --world-url http://<pi-ip-address>:8000/stream.mjpg
```

With one Pi camera, the GUI maps that stream to both panes. Later, with a
second camera/stream, provide it manually as:

```powershell
python dual_cam_gui_safe.py --camera-backend mjpeg --world-url http://<world-pi-ip>:8000/stream.mjpg --eye-url http://<eye-pi-ip>:8000/stream.mjpg
```

Run with:

```bash
python3 dual_cam_gui_safe.py --camera-backend picamera2 --outdir ~/poc_out
```

Plain SSH usually does not provide a display for Tkinter/OpenCV windows. Use
VNC, a directly attached desktop, or X forwarding for the GUI. The smoke test
above is the preferred first step over SSH.

### Raspberry Pi Compute Module 5 Lite

Use CM5 Lite, 2GB RAM, as the higher-performance embedded prototype target.
CM5 Lite has no eMMC, so this target boots from microSD. Raspberry Pi OS
64-bit is acceptable for bring-up, and the modern boot config path is
`/boot/firmware/config.txt`.

Use the target-specific setup and run path:

```bash
sudo ./scripts/setup_cm5.sh
./scripts/run_cm5.sh
```

The CM5 IO path should validate:

- two CSI cameras
- RGB/world camera plus mono/global-shutter eye camera
- reliable timestamp CSV output
- sustained recording without frame starvation
- ESP32 record/IR control over USB serial or UART

## Backend Selection

The app accepts:

```bash
--camera-backend auto
--camera-backend opencv
--camera-backend picamera2
```

Environment variables are also supported:

```bash
SMARTGLASSES_CAMERA_BACKEND=picamera2
SMARTGLASSES_OUTDIR=~/poc_out
SCENE_CAMERA=0
EYE_CAMERA=1
```

## Next Engineering Steps

1. Validate the OpenCV backend still behaves the same on Windows.
2. Boot the Pi Zero 2 W on Raspberry Pi OS Bookworm and verify
   `rpicam-hello --list-cameras`.
3. Run one Picamera2 camera through the GUI.
4. Reduce capture sizes if Pi Zero 2 W cannot sustain the current defaults.
5. Move the same backend to CM5 and validate dual CSI.
6. Consider moving recording from MJPG AVI to H.264 plus CSV metadata on Pi.
