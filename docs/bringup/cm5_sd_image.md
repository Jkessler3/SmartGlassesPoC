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

## Setup

```bash
sudo ./scripts/setup_cm5.sh
```

## Run

```bash
./scripts/run_cm5.sh
```

The run script loads `config/cm5.env`, creates the configured output directory, and starts the app.

## Camera Ordering

For CSI/libcamera cameras, set numeric camera IDs in `config/cm5.env`:

```bash
SCENE_CAMERA=0
EYE_CAMERA=1
```

For USB/OpenCV testing, set `SMARTGLASSES_CAMERA_BACKEND=opencv` and use either numeric indexes or stable `/dev/video*` paths.
