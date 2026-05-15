# Raspberry Pi Zero 2 W Bring-up

This is the original wearable prototype target.

## Validate Hardware

```bash
cat /proc/device-tree/model
uname -a
v4l2-ctl --list-devices
rpicam-hello --list-cameras || libcamera-hello --list-cameras || true
```

## Setup

```bash
sudo ./scripts/setup_pi_zero_2w.sh
```

## Run

```bash
./scripts/run_pi_zero_2w.sh
```

The run script loads `config/pi_zero_2w.env`, creates the configured output directory, and starts the app.

## Camera Ordering

For the Picamera2/libcamera backend, use numeric camera IDs:

```bash
SCENE_CAMERA=0
EYE_CAMERA=1
```

For USB/OpenCV testing, set `SMARTGLASSES_CAMERA_BACKEND=opencv` and use either numeric indexes or stable `/dev/video*` paths. If the scene and eye cameras swap, update `config/pi_zero_2w.env`.

## GPIO

The ESP32 serial controller remains supported. Direct Pi GPIO is optional. The Pi stream service uses `gpiozero` when started with GPIO enabled.
