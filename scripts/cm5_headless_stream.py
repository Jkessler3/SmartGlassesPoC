#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from camera_backends import load_camera_backend
from config import load_config


class FrameStore:
    def __init__(self):
        self._lock = threading.RLock()
        self.scene = None
        self.eye = None

    def update_scene(self, ts_ns, frame):
        with self._lock:
            self.scene = (ts_ns, frame)

    def update_eye(self, ts_ns, frame):
        with self._lock:
            self.eye = (ts_ns, frame)

    def latest(self):
        with self._lock:
            return self.scene, self.eye


class RecordingState:
    def __init__(self, record_dir, fps):
        self.record_dir = record_dir
        self.fps = fps
        self._lock = threading.RLock()
        self._writer = None
        self._path = None
        self._frame_count = 0

    def status(self):
        with self._lock:
            return {
                "recording": self._writer is not None,
                "path": self._path,
                "frame_count": self._frame_count,
            }

    def start(self, frame_shape):
        with self._lock:
            if self._writer is not None:
                return self.status()

            os.makedirs(self.record_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self._path = os.path.abspath(os.path.join(self.record_dir, f"cm5_dual_{stamp}.avi"))
            h, w = frame_shape[:2]
            writer = cv2.VideoWriter(self._path, cv2.VideoWriter_fourcc(*"MJPG"), self.fps, (w, h))
            if not writer.isOpened():
                self._path = None
                raise RuntimeError("Could not open CM5 recording writer")

            self._writer = writer
            self._frame_count = 0
            return self.status()

    def stop(self):
        with self._lock:
            if self._writer is not None:
                self._writer.release()
                self._writer = None
            return self.status()

    def write(self, frame):
        with self._lock:
            if self._writer is None:
                return
            self._writer.write(frame)
            self._frame_count += 1


def now_ns():
    return time.perf_counter_ns()


def read_worker(label, cap, update_fn, stop_event):
    failures = 0
    print(f"{label}: capture worker started", flush=True)
    while not stop_event.is_set():
        try:
            ok, frame = cap.read()
        except Exception as exc:
            print(f"{label}: camera read error: {exc}", file=sys.stderr, flush=True)
            ok, frame = False, None

        if ok and frame is not None:
            failures = 0
            update_fn(now_ns(), frame)
            continue

        failures += 1
        if failures == 1 or failures % 50 == 0:
            print(f"{label}: waiting for frames, failures={failures}", file=sys.stderr, flush=True)
        time.sleep(0.02)


def build_combo(scene_item, eye_item, width, height):
    scene_ts, scene = scene_item
    scene_disp = cv2.resize(scene, (width, height), interpolation=cv2.INTER_CUBIC)
    if eye_item is None:
        cv2.putText(
            scene_disp,
            f"scene={scene_ts}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
        )
        return scene_disp

    eye_ts, eye = eye_item
    eye_disp = cv2.resize(eye, (width, height), interpolation=cv2.INTER_CUBIC)
    combo = cv2.hconcat([scene_disp, eye_disp])
    dt_ms = (scene_ts - eye_ts) / 1e6
    cv2.putText(
        combo,
        f"scene={scene_ts} eye={eye_ts} dt={dt_ms:+.2f}ms",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
    )
    return combo


def encode_jpeg(frame, quality):
    ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return jpeg.tobytes()


def local_lan_ips():
    ips = []
    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, timeout=2)
        ips.extend(output.split())
    except Exception:
        pass

    try:
        ips.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass

    seen = set()
    result = []
    for ip in ips:
        if ip.startswith("127.") or ip in seen:
            continue
        seen.add(ip)
        result.append(ip)
    return result


def log_picamera2_inventory(expected_scene_camera, expected_connector):
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        print(f"Picamera2 inventory unavailable: {exc}", file=sys.stderr, flush=True)
        return None

    try:
        infos = Picamera2.global_camera_info()
    except Exception as exc:
        print(f"Picamera2 inventory failed: {exc}", file=sys.stderr, flush=True)
        return None

    print(f"Picamera2 detected {len(infos)} camera(s)", flush=True)
    for idx, info in enumerate(infos):
        print(f"  camera {idx}: {info}", flush=True)

    try:
        scene_idx = int(expected_scene_camera)
    except (TypeError, ValueError):
        print(
            f"Scene camera is configured as {expected_scene_camera!r}; CAM/DISP connector validation only applies to numeric Picamera2 camera IDs.",
            flush=True,
        )
        return infos

    if scene_idx >= len(infos):
        print(
            f"ERROR: expected {expected_connector} to appear as Picamera2 camera {scene_idx}, but only {len(infos)} camera(s) were detected.",
            file=sys.stderr,
            flush=True,
        )
        return infos

    print(f"Using {expected_connector} as scene camera {scene_idx}", flush=True)
    return infos


def make_handler(store, recorder, args, camera_count):
    class StreamHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *values):
            print("%s - %s" % (self.address_string(), fmt % values), flush=True)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send_html()
                return

            if self.path in ("/status", "/status.json"):
                scene, eye = store.latest()
                payload = {
                    "running": True,
                    "service": "smart-glasses-cm5-stream",
                    "profile": os.environ.get("DEVICE_PROFILE", "cm5"),
                    "name": args.name,
                    "hostname": socket.gethostname(),
                    "backend": args.camera_backend,
                    "detected_camera_count": camera_count,
                    "width": args.width,
                    "height": args.height,
                    "fps": args.fps,
                    "host": args.host,
                    "port": args.port,
                    "scene_camera": args.scene_camera,
                    "scene_camera_index": args.scene_camera,
                    "scene_camera_connector": args.scene_camera_connector,
                    "eye_camera_enabled": args.enable_eye_camera,
                    "eye_camera": args.eye_camera if args.enable_eye_camera else "",
                    "eye_camera_connector": args.eye_camera_connector if args.enable_eye_camera else "",
                    "has_scene_frame": scene is not None,
                    "has_eye_frame": eye is not None,
                    "paths": {
                        "stream": "/stream.mjpg",
                        "status": "/status",
                        "status_json": "/status.json",
                        "snapshot": "/snapshot.jpg",
                        "capture": "/capture",
                        "record_start": "/record/start",
                        "record_stop": "/record/stop",
                        "record_status": "/record/status",
                    },
                    "stream_path": "/stream.mjpg",
                    "status_path": "/status",
                    "snapshot_path": "/snapshot.jpg",
                    "capture_path": "/capture",
                    "record_start_path": "/record/start",
                    "record_stop_path": "/record/stop",
                    "record_status_path": "/record/status",
                    "recording": recorder.status(),
                }
                self._send_json(payload)
                return

            if self.path == "/snapshot.jpg":
                self._send_snapshot(save=False)
                return

            if self.path == "/record/status":
                self._send_json({"ok": True, "recording": recorder.status()})
                return

            if self.path == "/stream.mjpg":
                self._send_stream()
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path == "/capture":
                self._send_snapshot(save=True)
                return

            if self.path == "/record/start":
                scene, eye = store.latest()
                if scene is None or (args.enable_eye_camera and eye is None):
                    self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Required camera frames are not ready")
                    return
                combo = build_combo(scene, eye, args.width, args.height)
                try:
                    self._send_json({"ok": True, "recording": recorder.start(combo.shape)})
                except Exception as exc:
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

            if self.path == "/record/stop":
                self._send_json({"ok": True, "recording": recorder.stop()})
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def _send_html(self):
            body = b"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smart Glasses CM5 Preview</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: Arial, sans-serif; }
    header { padding: 10px 14px; background: #202020; }
    img { display: block; width: 100vw; height: calc(100vh - 42px); object-fit: contain; background: #000; }
  </style>
</head>
<body>
  <header>Smart Glasses CM5 Preview</header>
  <img src="/stream.mjpg" alt="dual camera stream">
</body>
</html>"""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_snapshot(self, save):
            scene, eye = store.latest()
            if scene is None or (args.enable_eye_camera and eye is None):
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "No required camera frame yet")
                return

            combo = build_combo(scene, eye, args.width, args.height)
            jpeg = encode_jpeg(combo, args.quality)

            if save:
                os.makedirs(args.snapshot_dir, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                path = os.path.abspath(os.path.join(args.snapshot_dir, f"cm5_dual_{stamp}.jpg"))
                with open(path, "wb") as fh:
                    fh.write(jpeg)
                self._send_json({"ok": True, "path": path})
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)

        def _send_stream(self):
            self.send_response(HTTPStatus.OK)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            last_scene_ts = None
            while True:
                scene, eye = store.latest()
                if scene is None or (args.enable_eye_camera and eye is None) or scene[0] == last_scene_ts:
                    time.sleep(0.02)
                    continue
                last_scene_ts = scene[0]
                try:
                    combo = build_combo(scene, eye, args.width, args.height)
                    recorder.write(combo)
                    jpeg = encode_jpeg(combo, args.quality)
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    break
                except Exception as exc:
                    print(f"stream error: {exc}", file=sys.stderr, flush=True)
                    time.sleep(0.1)

        def _send_json(self, payload):
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return StreamHandler


def parse_args():
    config = load_config([])
    parser = argparse.ArgumentParser(description="Headless CM5 dual-camera stream service")
    parser.add_argument("--host", default=os.environ.get("STREAM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STREAM_PORT", "8000")))
    parser.add_argument("--name", default=os.environ.get("GLASSES_NAME", "glasses-cm5"))
    parser.add_argument("--camera-backend", default=config.camera_backend)
    parser.add_argument("--scene-camera", default=config.scene_camera)
    parser.add_argument("--eye-camera", default=config.eye_camera)
    parser.add_argument(
        "--enable-eye-camera",
        default=os.environ.get("ENABLE_EYE_CAMERA", "1").strip().lower() in ("1", "true", "yes"),
        action=argparse.BooleanOptionalAction,
    )
    parser.add_argument("--scene-camera-connector", default=os.environ.get("SCENE_CAMERA_CONNECTOR", "CAM/DISP0"))
    parser.add_argument("--eye-camera-connector", default=os.environ.get("EYE_CAMERA_CONNECTOR", "CAM/DISP1"))
    parser.add_argument("--width", type=int, default=int(os.environ.get("STREAM_WIDTH", "640")))
    parser.add_argument("--height", type=int, default=int(os.environ.get("STREAM_HEIGHT", "480")))
    parser.add_argument("--fps", type=int, default=int(os.environ.get("STREAM_FPS", "15")))
    parser.add_argument("--quality", type=int, default=int(os.environ.get("STREAM_QUALITY", "75")))
    parser.add_argument(
        "--snapshot-dir",
        default=os.environ.get("SNAPSHOT_DIR", os.path.join(config.outdir, "snapshots")),
    )
    parser.add_argument(
        "--record-dir",
        default=os.environ.get("RECORD_DIR", os.path.join(config.outdir, "recordings")),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("Starting Smart Glasses CM5 headless stream service", flush=True)
    print(f"profile={os.environ.get('DEVICE_PROFILE', 'cm5')}", flush=True)
    print(
        f"backend={args.camera_backend} scene_camera={args.scene_camera} eye_camera={'enabled:' + str(args.eye_camera) if args.enable_eye_camera else 'disabled'}",
        flush=True,
    )
    print(f"scene_camera_connector={args.scene_camera_connector}", flush=True)
    if args.enable_eye_camera:
        print(f"eye_camera_connector={args.eye_camera_connector}", flush=True)
    print(f"snapshots={args.snapshot_dir} recordings={args.record_dir}", flush=True)

    backend = load_camera_backend(args.camera_backend)
    camera_count = None
    if args.camera_backend == "picamera2":
        camera_infos = log_picamera2_inventory(args.scene_camera, args.scene_camera_connector)
        if camera_infos is not None:
            camera_count = len(camera_infos)
        if camera_infos == []:
            print(
                "No Picamera2/libcamera cameras detected. Run scripts/debug_cm5_cameras.sh and verify CSI overlay/cable.",
                file=sys.stderr,
                flush=True,
            )
            return 2

    scene_cap = backend.open_cam(args.scene_camera)
    if scene_cap is None:
        print(f"ERROR: failed to open scene camera {args.scene_camera}", file=sys.stderr, flush=True)
        return 2

    eye_cap = None
    if args.enable_eye_camera:
        eye_cap = backend.open_cam(args.eye_camera)
        if eye_cap is None:
            print(f"ERROR: failed to open eye camera {args.eye_camera}", file=sys.stderr, flush=True)
            scene_cap.release()
            return 2

    backend.try_mode(scene_cap, args.width, args.height, args.fps)
    if eye_cap is not None:
        backend.try_mode(eye_cap, args.width, args.height, args.fps)

    store = FrameStore()
    recorder = RecordingState(args.record_dir, args.fps)
    stop_event = threading.Event()
    workers = [
        threading.Thread(target=read_worker, args=("scene", scene_cap, store.update_scene, stop_event), daemon=True),
    ]
    if eye_cap is not None:
        workers.append(threading.Thread(target=read_worker, args=("eye", eye_cap, store.update_eye, stop_event), daemon=True))
    for worker in workers:
        worker.start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, recorder, args, camera_count))
    lan_ips = local_lan_ips()
    bind_host = args.host
    print(f"Listening on {bind_host}:{args.port}", flush=True)
    if bind_host in ("0.0.0.0", "") and lan_ips:
        for ip in lan_ips:
            print(f"Stream URL: http://{ip}:{args.port}/stream.mjpg", flush=True)
            print(f"Status URL: http://{ip}:{args.port}/status", flush=True)
    else:
        print(f"Stream URL: http://{bind_host}:{args.port}/stream.mjpg", flush=True)
        print(f"Status URL: http://{bind_host}:{args.port}/status", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping CM5 stream service", flush=True)
    finally:
        stop_event.set()
        recorder.stop()
        server.server_close()
        for cap in (scene_cap, eye_cap):
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
        for worker in workers:
            worker.join(timeout=2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
