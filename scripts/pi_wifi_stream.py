#!/usr/bin/env python3
import argparse
import json
import os
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


class FrameStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._jpeg = None
        self._ts = 0.0

    def update(self, jpeg):
        with self._lock:
            self._jpeg = jpeg
            self._ts = time.time()

    def latest(self):
        with self._lock:
            return self._jpeg, self._ts


class RecordingState:
    def __init__(self, record_dir, device_name, width, height, fps, led_setter=None):
        self.record_dir = record_dir
        self.device_name = device_name
        self.width = width
        self.height = height
        self.fps = fps
        self.led_setter = led_setter or (lambda _on: None)
        self._lock = threading.RLock()
        self._writer = None
        self._path = None
        self._frame_count = 0
        self.led_setter(False)

    def status(self):
        with self._lock:
            return {
                "recording": self._writer is not None,
                "path": self._path,
                "frame_count": self._frame_count,
            }

    def start(self):
        with self._lock:
            if self._writer is not None:
                return self.status()

            os.makedirs(self.record_dir, exist_ok=True)
            safe_name = safe_filename_part(self.device_name)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self._path = os.path.abspath(os.path.join(self.record_dir, f"{safe_name}_{stamp}.avi"))
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(self._path, fourcc, self.fps, (self.width, self.height))
            if not writer.isOpened():
                self._path = None
                raise RuntimeError("Could not open Pi recording writer")

            self._writer = writer
            self._frame_count = 0
            self.led_setter(True)
            return self.status()

    def stop(self):
        with self._lock:
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            self.led_setter(False)
            return self.status()

    def toggle(self):
        with self._lock:
            recording = self._writer is not None
        if recording:
            return self.stop()
        return self.start()

    def write(self, frame):
        with self._lock:
            if self._writer is None:
                return
            self._writer.write(frame)
            self._frame_count += 1


def safe_filename_part(value):
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


class GpioControls:
    def __init__(self, enabled, button_pin, led_pin, toggle_callback):
        self.enabled = enabled
        self.button = None
        self.led = None
        if not enabled:
            return

        from gpiozero import Button, LED

        self.led = LED(led_pin)
        self.led.off()
        self.button = Button(button_pin, pull_up=True, bounce_time=0.08)
        self.button.when_pressed = toggle_callback

    def set_led(self, on):
        if self.led is None:
            return
        if on:
            self.led.on()
        else:
            self.led.off()

    def close(self):
        if self.led is not None:
            self.led.off()
            self.led.close()
        if self.button is not None:
            self.button.close()


def camera_worker(store, recorder, camera_num, width, height, fps, quality, input_order, stop_event):
    from picamera2 import Picamera2

    picam = Picamera2(camera_num=camera_num)
    config = picam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"},
        controls={"FrameRate": fps},
    )
    picam.configure(config)
    picam.start()
    time.sleep(0.5)

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    frame_interval = 1.0 / max(1, fps)

    try:
        while not stop_event.is_set():
            t0 = time.monotonic()
            frame = picam.capture_array()
            if input_order == "rgb":
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, jpeg = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                store.update(jpeg.tobytes())
            recorder.write(frame)

            sleep_s = frame_interval - (time.monotonic() - t0)
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        try:
            picam.stop()
        except Exception:
            pass
        try:
            picam.close()
        except Exception:
            pass


def make_handler(store, recorder, device_name, camera_num, width, height, fps, snapshot_dir, gpio_enabled):
    class StreamHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("%s - %s" % (self.address_string(), fmt % args))

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smart Glasses Pi Preview</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: Arial, sans-serif; }
    header { padding: 10px 14px; background: #202020; }
    img { display: block; width: 100vw; height: calc(100vh - 42px); object-fit: contain; background: #000; }
  </style>
</head>
<body>
  <header>Smart Glasses Pi Preview</header>
  <img src="/stream.mjpg" alt="camera stream">
</body>
</html>"""
                )
                return

            if self.path == "/status.json":
                jpeg, ts = store.latest()
                payload = {
                    "service": "smart-glasses-pi-stream",
                    "name": device_name,
                    "hostname": socket.gethostname(),
                    "camera": camera_num,
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "has_frame": jpeg is not None,
                    "last_frame_age_s": round(time.time() - ts, 3) if ts else None,
                    "stream_path": "/stream.mjpg",
                    "snapshot_path": "/snapshot.jpg",
                    "capture_path": "/capture",
                    "record_start_path": "/record/start",
                    "record_stop_path": "/record/stop",
                    "record_status_path": "/record/status",
                    "recording": recorder.status(),
                    "gpio_enabled": gpio_enabled,
                }
                body = json.dumps(payload, indent=2).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/snapshot.jpg":
                jpeg, _ = store.latest()
                if jpeg is None:
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "No frame yet")
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
                return

            if self.path == "/record/status":
                self._send_json({"ok": True, "recording": recorder.status()})
                return

            if self.path == "/stream.mjpg":
                self.send_response(HTTPStatus.OK)
                self.send_header("Age", "0")
                self.send_header("Cache-Control", "no-cache, private")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()

                last_ts = 0.0
                while True:
                    jpeg, ts = store.latest()
                    if jpeg is None or ts == last_ts:
                        time.sleep(0.02)
                        continue
                    last_ts = ts
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    except BrokenPipeError:
                        break
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path == "/record/start":
                try:
                    self._send_json({"ok": True, "recording": recorder.start()})
                except Exception as exc:
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

            if self.path == "/record/stop":
                self._send_json({"ok": True, "recording": recorder.stop()})
                return

            if self.path != "/capture":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            jpeg, ts = store.latest()
            if jpeg is None:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "No frame yet")
                return

            os.makedirs(snapshot_dir, exist_ok=True)
            safe_name = safe_filename_part(device_name)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_name}_{stamp}.jpg"
            path = os.path.abspath(os.path.join(snapshot_dir, filename))
            with open(path, "wb") as fh:
                fh.write(jpeg)

            payload = {
                "ok": True,
                "name": device_name,
                "filename": filename,
                "path": path,
                "frame_ts": ts,
            }
            self._send_json(payload)

        def _send_json(self, payload):
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return StreamHandler


def main():
    parser = argparse.ArgumentParser(description="Stream Raspberry Pi camera preview over WiFi")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--name", default=socket.gethostname(), help="Friendly glasses/device name.")
    parser.add_argument(
        "--snapshot-dir",
        default=os.path.expanduser("~/poc_out/snapshots"),
        help="Directory where POST /capture saves JPEG snapshots.",
    )
    parser.add_argument(
        "--record-dir",
        default=os.path.expanduser("~/poc_out/recordings"),
        help="Directory where Pi-side recordings are saved.",
    )
    parser.add_argument("--enable-gpio", action="store_true", help="Enable GPIO button and LED controls.")
    parser.add_argument("--button-pin", type=int, default=17, help="BCM GPIO pin for the record toggle button.")
    parser.add_argument("--led-pin", type=int, default=27, help="BCM GPIO pin for the recording LED.")
    parser.add_argument(
        "--input-order",
        choices=("rgb", "bgr"),
        default="rgb",
        help="Color channel order returned by Picamera2 before JPEG encoding.",
    )
    args = parser.parse_args()

    store = FrameStore()
    stop_event = threading.Event()
    gpio = None
    recorder = None

    def toggle_from_button():
        if recorder is None:
            return
        try:
            status = recorder.toggle()
            print(f"GPIO record toggle: {status}")
        except Exception as exc:
            print(f"GPIO record toggle failed: {exc}")

    gpio = GpioControls(args.enable_gpio, args.button_pin, args.led_pin, toggle_from_button)
    recorder = RecordingState(
        args.record_dir,
        args.name,
        args.width,
        args.height,
        args.fps,
        led_setter=gpio.set_led,
    )
    thread = threading.Thread(
        target=camera_worker,
        args=(
            store,
            recorder,
            args.camera,
            args.width,
            args.height,
            args.fps,
            args.quality,
            args.input_order,
            stop_event,
        ),
        daemon=True,
    )
    thread.start()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(
            store,
            recorder,
            args.name,
            args.camera,
            args.width,
            args.height,
            args.fps,
            args.snapshot_dir,
            args.enable_gpio,
        ),
    )
    print(f"Streaming {args.name} camera {args.camera} at http://{args.host}:{args.port}")
    print("From Windows, open http://<pi-ip-address>:%d" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping stream...")
    finally:
        stop_event.set()
        recorder.stop()
        server.server_close()
        thread.join(timeout=2.0)
        gpio.close()


if __name__ == "__main__":
    main()
