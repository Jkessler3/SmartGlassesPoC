# CM5 Stream GUI Connection

This guide connects the Windows GUI/client to the CM5 headless stream service over LAN/Wi-Fi.

The CM5 target is Raspberry Pi Compute Module 5 Lite with a CSI Arducam UC-B47 / IMX708 on CAM/DISP0. Keep the boot camera config as:

```ini
camera_auto_detect=0
dtoverlay=imx708,cam0
```

## Service Basics

The service entrypoint is:

```bash
/home/user/SmartGlassesPoC/scripts/run_cm5_stream.sh
```

It loads `config/cm5.env`, uses Picamera2, binds to `0.0.0.0`, and exposes:

```text
http://<pi-ip>:8000/stream.mjpg
http://<pi-ip>:8000/status
http://<pi-ip>:8000/status.json
```

## Find The Pi IP

On the CM5:

```bash
hostname -I
```

Use the first LAN/Wi-Fi address from that output.

## Check Logs

```bash
journalctl -u smart-glasses-stream.service -f
```

The service logs the exact stream and status URLs at startup.

## Check Listening Port

```bash
sudo ss -ltnp
```

Expected result: Python listening on `0.0.0.0:8000`. If it shows only `127.0.0.1:8000`, set this in `config/cm5.env` and restart:

```bash
STREAM_HOST=0.0.0.0
STREAM_PORT=8000
```

```bash
sudo systemctl restart smart-glasses-stream.service
```

## Browser Tests

From the CM5:

```bash
curl http://127.0.0.1:8000/status
```

From another machine on the same network:

```text
http://<pi-ip>:8000/status
http://<pi-ip>:8000/stream.mjpg
```

You can also run:

```bash
./scripts/check_stream.sh
```

## Scene-Only Testing

For one-camera IMX708 testing on CAM/DISP0, set:

```bash
ENABLE_EYE_CAMERA=0
SCENE_CAMERA=0
EYE_CAMERA=
```

With `ENABLE_EYE_CAMERA=0`, the service should start and stream the scene camera only.

## GUI/Client Configuration

The GUI/client can connect without discovery using environment variables:

```powershell
$env:PI_HOST="<pi-ip>"
$env:PI_PORT="8000"
$env:SMARTGLASSES_CAMERA_BACKEND="mjpeg"
.\RUN.bat
```

Or provide explicit URLs:

```powershell
$env:STREAM_URL="http://<pi-ip>:8000/stream.mjpg"
$env:STATUS_URL="http://<pi-ip>:8000/status"
$env:SMARTGLASSES_CAMERA_BACKEND="mjpeg"
.\RUN.bat
```

The equivalent command-line form is:

```powershell
python dual_cam_gui_safe.py --camera-backend mjpeg --world-url http://<pi-ip>:8000/stream.mjpg --status-url http://<pi-ip>:8000/status
```
