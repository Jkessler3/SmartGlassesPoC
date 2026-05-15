# Raspberry Pi CM5 Lite SD Image Bring-up

This guide is for Raspberry Pi Compute Module 5 Lite, 2GB RAM, booting from microSD with Raspberry Pi OS 64-bit.

## Hardware Notes

- CM5 Lite has no eMMC.
- This target boots from microSD.
- Raspberry Pi OS 64-bit is acceptable for bring-up.
- Modern Raspberry Pi OS stores boot configuration at `/boot/firmware/config.txt`.

## Validate Hardware

```bash
cat /proc/device-tree/model
uname -a
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,MODEL
v4l2-ctl --list-devices
rpicam-hello --list-cameras || libcamera-hello --list-cameras || true
```

For this build, the scene camera is connected to **CAM/DISP 0**. In Picamera2/libcamera that should appear as camera `0`, and `config/cm5.env` sets:

```bash
SCENE_CAMERA_CONNECTOR=CAM/DISP0
SCENE_CAMERA=0
EYE_CAMERA_CONNECTOR=CAM/DISP1
ENABLE_EYE_CAMERA=1
EYE_CAMERA=1
```

The current boot camera overlays are:

```ini
camera_auto_detect=0
dtoverlay=imx708,cam0
dtoverlay=ov9281,cam1
```

If `rpicam-hello --list-cameras` reports `No cameras available!`, the problem is below the app. Stop the stream service and debug the CSI camera path first:

```bash
sudo systemctl stop smart-glasses-stream.service
./scripts/debug_cm5_cameras.sh
```

Internal nodes such as `/dev/video19` and `/dev/video20` through `/dev/video35` are PiSP/codec devices, not the Arducam camera sensors. Do not configure the app to use those nodes.

## Setup

```bash
sudo ./scripts/setup_cm5.sh
```

## Run

```bash
./scripts/run_cm5.sh
```

The GUI app is for desktop/manual testing only. It creates a Tkinter window and requires `DISPLAY`.

The systemd service uses headless stream mode and does not require `DISPLAY`:

```bash
./scripts/run_cm5_stream.sh
```

The headless run script loads `config/cm5.env`, creates `/home/user/poc_out`, opens scene camera `0` and eye camera `1`, and exposes the stream/status endpoints.
At startup it logs the Picamera2 camera inventory and confirms that CAM/DISP 0 is being used as scene camera `0`.
Keep the stream service stopped until `rpicam-hello --list-cameras` detects at least one camera.

View service logs with:

```bash
journalctl -u smart-glasses-stream.service -f
```

For GUI/client connection testing over LAN/Wi-Fi, see `docs/bringup/cm5_stream_gui_connection.md`.

## Camera Ordering

For CSI/libcamera cameras, set numeric camera IDs in `config/cm5.env`:

```bash
# CAMERA_BACKEND=picamera2 conceptually; this repo's env key is:
SMARTGLASSES_CAMERA_BACKEND=picamera2
SCENE_CAMERA_CONNECTOR=CAM/DISP0
SCENE_CAMERA=0
EYE_CAMERA_CONNECTOR=CAM/DISP1
ENABLE_EYE_CAMERA=1
EYE_CAMERA=1
```

Use those settings only after the CSI cameras appear in `rpicam-hello --list-cameras` or Picamera2. Do not switch this CM5 Arducam profile to OpenCV/USB mode unless explicitly testing different USB camera hardware.

See `docs/bringup/cm5_csi_camera_debug.md` for overlay examples for IMX219, OV9281, IMX708, OV5647, and dual-camera CAM/DISP0 plus CAM/DISP1 bring-up.
