# CM5 CSI Camera Debug

This guide is for Raspberry Pi Compute Module 5 Lite with CSI Arducam modules on Raspberry Pi OS 64-bit.

The scene camera is Arducam UC-B47 / IMX708 on **CAM/DISP 0**. The second eye camera is OV9281 on **CAM/DISP 1**. CAM/DISP 0 should not require the J6 jumpers. CAM/DISP 1 requires both J6 jumpers fitted for camera/display I2C routing on the CM5 IO board.

Focus first on CAM/DISP 0, the sensor overlay, cable orientation, and `/boot/firmware/config.txt`. Do not point the app at `/dev/video19` or `/dev/video20` through `/dev/video35`; those are internal PiSP/codec devices, not the Arducam sensor.

## Stop The Service

Stop the stream service before camera testing:

```bash
sudo systemctl stop smart-glasses-stream.service
```

Leave it stopped until `rpicam-hello --list-cameras` detects at least one CSI camera.

## Run Diagnostics

From the repo root:

```bash
./scripts/debug_cm5_cameras.sh
```

Or run the individual checks:

```bash
cat /proc/device-tree/model
uname -a
grep -n "camera_auto_detect\|dtoverlay.*imx\|dtoverlay.*ov\|dtoverlay.*arducam\|vc4-kms" /boot/firmware/config.txt || true
rpicam-hello --list-cameras || true
v4l2-ctl --list-devices || true
ls -l /dev/video* || true
dmesg | grep -iE "imx|ov|arducam|unicam|csi|camera|i2c" | tail -120 || true
```

If `rpicam-hello --list-cameras` reports `No cameras available!`, the problem is below the app. Fix overlay, cabling, connector, sensor model, or I2C routing before restarting the stream service.

## Internal Video Nodes

Seeing only devices such as `/dev/video19` and `/dev/video20` through `/dev/video35` usually means only internal PiSP/codec nodes are present. They are not the scene or eye camera sensors and should not be used as `SCENE_CAMERA` or `EYE_CAMERA`.

The app should remain on the Picamera2/libcamera backend for this CM5 CSI hardware profile.

## CAM/DISP 0 Overlay Examples

Set the overlay for the exact sensor connected to CAM/DISP 0 in `/boot/firmware/config.txt`, then reboot.

For IMX219:

```ini
camera_auto_detect=0
dtoverlay=imx219,cam0
```

For OV9281:

```ini
camera_auto_detect=0
dtoverlay=ov9281,cam0
```

For IMX708:

```ini
camera_auto_detect=0
dtoverlay=imx708,cam0
```

For OV5647:

```ini
camera_auto_detect=0
dtoverlay=ov5647,cam0
```

## Current Dual Camera Config

For the current hardware, use:

```ini
camera_auto_detect=0
dtoverlay=imx708,cam0
dtoverlay=ov9281,cam1
```

CAM/DISP 1 requires both J6 jumpers fitted.

## Other Dual Camera Example

Test one camera on CAM/DISP 0 first. Add CAM/DISP 1 only after camera 0 appears in `rpicam-hello --list-cameras`.

For two IMX219 cameras:

```ini
camera_auto_detect=0
dtoverlay=imx219,cam0
dtoverlay=imx219,cam1
```

CAM/DISP 1 requires both J6 jumpers fitted.

## App Config After Detection

Only after cameras appear in `rpicam-hello --list-cameras`, keep the CM5 app config on CSI/Picamera2:

```bash
# CAMERA_BACKEND=picamera2 conceptually; this repo's env key is:
SMARTGLASSES_CAMERA_BACKEND=picamera2
SCENE_CAMERA_CONNECTOR=CAM/DISP0
SCENE_CAMERA=0
EYE_CAMERA_CONNECTOR=CAM/DISP1
ENABLE_EYE_CAMERA=1
EYE_CAMERA=1
```

Do not switch the CM5 profile to OpenCV/USB mode for CSI Arducam bring-up unless that hardware path is intentionally changed.
