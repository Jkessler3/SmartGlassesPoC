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
python3 scripts/pi_wifi_stream.py --width 640 --height 480 --fps 15
```

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
python dual_cam_gui_safe.py --camera-backend mjpeg --world-url http://<pi-ip-address>:8000/stream.mjpg
```

With one Pi camera, the GUI maps that stream to both panes. Later, with a
second camera/stream, provide it as:

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

### Compute Module 5

Use CM5 as the final embedded target. The CM5 IO path should validate:

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
```

## Next Engineering Steps

1. Validate the OpenCV backend still behaves the same on Windows.
2. Boot the Pi Zero 2 W on Raspberry Pi OS Bookworm and verify
   `rpicam-hello --list-cameras`.
3. Run one Picamera2 camera through the GUI.
4. Reduce capture sizes if Pi Zero 2 W cannot sustain the current defaults.
5. Move the same backend to CM5 and validate dual CSI.
6. Consider moving recording from MJPG AVI to H.264 plus CSV metadata on Pi.
