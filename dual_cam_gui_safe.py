import os
import platform
import sys
import time
import threading
import queue
from collections import deque
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import serial
from serial.tools import list_ports

from camera_backends import load_camera_backend
from config import load_config
from glasses_discovery import discover_glasses
from pi_record import start_pi_recording, stop_pi_recording
from pi_snapshot import capture_snapshot

CAM_READ_FAIL_LIMIT = 100
CAM_READ_FAIL_SLEEP_S = 0.02
SERIAL_PROBE_STARTUP_S = 0.35
SERIAL_PROBE_WINDOW_S = 0.60
SERIAL_CONNECT_SETTLE_S = 0.75
SERIAL_PORT_TIMEOUT_S = 0.25
SERIAL_PROBE_WRITE_TIMEOUT_S = 0.25
SERIAL_SESSION_WRITE_TIMEOUT_S = None
SERIAL_BRIGHTNESS_INTERVAL_S = 0.10
SERIAL_PROBE_DTR = True
SERIAL_PROBE_RTS = False
SERIAL_SESSION_DTR = True
SERIAL_SESSION_RTS = False
WORLD_CAPTURE_WIDTH = 1280
WORLD_CAPTURE_HEIGHT = 720
WORLD_CAPTURE_FPS = 30
EYE_CAPTURE_WIDTH = 640
EYE_CAPTURE_HEIGHT = 480
EYE_CAPTURE_FPS = 60
WORLD_DISPLAY_WIDTH = 1280
WORLD_DISPLAY_HEIGHT = 720
EYE_DISPLAY_WIDTH = 640
EYE_DISPLAY_HEIGHT = 480
EYE_PAD_TOP = 120
EYE_PAD_BOTTOM = 120


# ---------- Timing ----------
def now_ns():
    return time.perf_counter_ns()


def serial_port_sort_key(port_info):
    text = " ".join(
        part for part in (
            port_info.device,
            port_info.description,
            getattr(port_info, "manufacturer", None),
            port_info.hwid,
        )
        if part
    ).lower()
    preferred = any(token in text for token in (
        "xiao", "esp32", "cp210", "ch340", "wch", "silicon labs", "usb serial"
    ))
    return (0 if preferred else 1, port_info.device or "")


def probe_esp32_port(dev, baud=115200):
    ser = serial.Serial()
    ser.port = dev
    ser.baudrate = baud
    ser.timeout = SERIAL_PORT_TIMEOUT_S
    ser.write_timeout = SERIAL_PROBE_WRITE_TIMEOUT_S
    ser.dtr = SERIAL_PROBE_DTR
    ser.rts = SERIAL_PROBE_RTS
    ser.open()
    try:
        time.sleep(SERIAL_PROBE_STARTUP_S)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(b"ID?\n")
        ser.flush()

        deadline = time.monotonic() + SERIAL_PROBE_WINDOW_S
        while time.monotonic() < deadline:
            line = ser.readline().decode(errors="ignore").strip()
            if "XIAO_REC_CTRL" in line:
                return True
        return False
    finally:
        ser.close()


def extract_prefixed_int(line: str, prefix: str):
    idx = line.find(prefix)
    if idx < 0:
        return None

    idx += len(prefix)
    digits = []
    while idx < len(line) and line[idx].isdigit():
        digits.append(line[idx])
        idx += 1

    if not digits:
        return None
    return int("".join(digits))


# ---------- Serial helpers ----------
def find_esp32_port(baud=115200):
    """
    Safe ESP32 auto-detect:
    - skips common Bluetooth/phantom COM ports
    - probes ID?
    """
    ports = list(list_ports.comports())

    filtered = []
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "bluetooth" in desc or "bthenum" in hwid:
            continue
        filtered.append(p)

    filtered.sort(key=serial_port_sort_key)

    for p in filtered:
        dev = p.device
        try:
            if probe_esp32_port(dev, baud=baud):
                return dev

        except Exception:
            continue

    return None


class App:
    def __init__(self, config):
        self.config = config
        self.camera_backend = load_camera_backend(config.camera_backend)
        if hasattr(self.camera_backend, "configure"):
            self.camera_backend.configure(config)

        self.root = tk.Tk()
        self.root.title("Smart Glasses PoC (GUI + Dual Cam)")

        # Tk state
        self.world_idx = tk.StringVar(value=str(config.scene_camera))
        self.eye_idx = tk.StringVar(value=str(config.eye_camera))
        self.port_var = tk.StringVar(value="")
        self.pi_host_var = tk.StringVar(value="")
        self.glasses_var = tk.StringVar(value="")
        self.glasses_devices = []
        self.preview_label = "Pi stream"
        self.current_stream_url = config.world_url
        self.current_status_url = ""
        self.single_stream_preview = False
        self.rec_var = tk.BooleanVar(value=False)
        self.ir_var = tk.BooleanVar(value=False)
        self.brightness_var = tk.IntVar(value=255)
        self.status = tk.StringVar(value=f"Ready ({self.camera_backend.name} camera backend)")

        # Serial
        self.ser = None
        self.ser_thread = None
        self.ser_writer_thread = None
        self.ser_stop = threading.Event()
        self.ser_q = queue.Queue()
        self.ser_write_q = queue.Queue()
        self._suppress_brightness_send = False

        # Cameras
        self.capW = None
        self.capE = None
        self.world_q = deque(maxlen=60)
        self.eye_q = deque(maxlen=180)
        self.world_lock = threading.Lock()
        self.eye_lock = threading.Lock()
        self.camera_workers = []
        self.capture_running = True

        # Recording
        self.writer = None
        self.csv_fh = None
        self.rec_path = None
        self.csv_path = None
        self.frame_idx = 0
        self.outdir = self.config.outdir
        os.makedirs(self.outdir, exist_ok=True)

        # throttle brightness serial spam
        self._last_b_send = 0.0

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

        if self.camera_backend.name != "mjpeg" or self.config.world_url:
            self.open_cameras()
        self.root.after(30, self.tick)

    # ---------- UI ----------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        cam_box_title = "Pi Stream Cameras" if self.camera_backend.name == "mjpeg" else "Cameras"
        cam_box = ttk.LabelFrame(frm, text=cam_box_title, padding=10)
        cam_box.grid(row=0, column=0, sticky="ew")

        scan_text = "Scan Sources" if self.camera_backend.name == "mjpeg" else "Scan Cameras"
        ttk.Button(cam_box, text=scan_text, command=self.on_scan_cameras).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(cam_box, text="World source").grid(row=1, column=0, sticky="w")
        ttk.Entry(cam_box, textvariable=self.world_idx, width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(cam_box, text="Eye source").grid(row=2, column=0, sticky="w")
        ttk.Entry(cam_box, textvariable=self.eye_idx, width=6).grid(row=2, column=1, sticky="w")
        ttk.Button(cam_box, text="Apply Sources", command=self.on_apply_cameras).grid(row=3, column=0, columnspan=2, pady=5)

        if self.camera_backend.name == "mjpeg":
            self._build_pi_glasses_ui(frm)
        else:
            self._build_serial_ui(frm)

        ctl_box = ttk.LabelFrame(frm, text="Controls", padding=10)
        ctl_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        self.btn_rec = ttk.Button(ctl_box, text="Record OFF", command=self.on_toggle_record)
        self.btn_rec.grid(row=0, column=0, padx=5, pady=5)

        if self.camera_backend.name != "mjpeg":
            self.btn_ir = ttk.Button(ctl_box, text="IR OFF", command=self.on_toggle_ir)
            self.btn_ir.grid(row=0, column=1, padx=5, pady=5)

            ttk.Label(ctl_box, text="Brightness").grid(row=1, column=0, sticky="w")
            self.lbl_b = ttk.Label(ctl_box, text="255")
            self.lbl_b.grid(row=1, column=1, sticky="e")
            self.sld = ttk.Scale(
                ctl_box, from_=0, to=255, orient="horizontal",
                variable=self.brightness_var, command=self.on_brightness_change
            )
            self.sld.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5)
            quit_row = 3
        else:
            self.btn_ir = None
            self.lbl_b = None
            self.sld = None
            ttk.Button(ctl_box, text="Snapshot", command=self.on_capture_snapshot).grid(row=0, column=1, padx=5, pady=5)
            quit_row = 1

        ttk.Button(ctl_box, text="Quit", command=self.on_quit).grid(row=quit_row, column=0, columnspan=2, pady=5)

        ttk.Label(frm, textvariable=self.status).grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def _build_pi_glasses_ui(self, frm):
        pi_box = ttk.LabelFrame(frm, text="Pi Glasses", padding=10)
        pi_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(pi_box, text="Find Glasses", command=self.on_find_glasses).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(pi_box, text="Device").grid(row=0, column=1, sticky="e")
        self.glasses_combo = ttk.Combobox(pi_box, textvariable=self.glasses_var, width=36, state="readonly")
        self.glasses_combo.grid(row=0, column=2, padx=5, sticky="ew")
        self.glasses_combo.bind("<<ComboboxSelected>>", self.on_glasses_selected)

        ttk.Label(pi_box, text="Host/IP").grid(row=1, column=0, sticky="w")
        ttk.Entry(pi_box, textvariable=self.pi_host_var, width=18).grid(row=1, column=1, sticky="w")
        ttk.Button(pi_box, text="Connect Stream", command=self.on_connect_glasses).grid(row=1, column=2, padx=5, sticky="w")

        if self.config.world_url:
            self.pi_host_var.set(self.config.world_url)

    def _build_serial_ui(self, frm):
        ser_box = ttk.LabelFrame(frm, text="ESP32 Serial", padding=10)
        ser_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(ser_box, text="Find ESP32", command=self.on_find_port).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(ser_box, text="Port").grid(row=0, column=1)
        ttk.Entry(ser_box, textvariable=self.port_var, width=10).grid(row=0, column=2)
        ttk.Button(ser_box, text="Connect", command=self.on_connect).grid(row=0, column=3, padx=5)
        ttk.Button(ser_box, text="Disconnect", command=self.on_disconnect).grid(row=0, column=4, padx=5)

    def _stream_url_from_host(self, host_or_url):
        value = host_or_url.strip()
        if not value:
            return ""
        if value.startswith("http://") or value.startswith("https://"):
            if value.endswith("/"):
                return value + "stream.mjpg"
            if value.endswith(".mjpg"):
                return value
            return value + "/stream.mjpg"
        if ":" not in value:
            value = f"{value}:8000"
        return f"http://{value}/stream.mjpg"

    def on_find_glasses(self):
        self.status.set("Finding Pi glasses on local network...")
        self.root.update_idletasks()

        def worker():
            devices = discover_glasses()

            def done():
                self.glasses_devices = devices
                descriptions = [device.description for device in devices]
                self.glasses_combo["values"] = descriptions
                if devices:
                    self.glasses_combo.current(0)
                    self.glasses_var.set(descriptions[0])
                    self.pi_host_var.set(devices[0].host)
                    self.status.set(f"Found {len(devices)} Pi glasses device(s)")
                else:
                    self.status.set("No Pi glasses found. Enter host/IP manually.")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def on_glasses_selected(self, _event=None):
        idx = getattr(self, "glasses_combo", None).current() if hasattr(self, "glasses_combo") else -1
        if idx is not None and 0 <= idx < len(self.glasses_devices):
            self.pi_host_var.set(self.glasses_devices[idx].host)

    def on_connect_glasses(self):
        host = self.pi_host_var.get().strip()
        stream_url = ""
        for device in self.glasses_devices:
            if host in (device.host, device.description, device.name):
                stream_url = device.stream_url
                self.current_status_url = device.status_url
                self.preview_label = device.name
                break
        if not stream_url:
            stream_url = self._stream_url_from_host(host)
            self.current_status_url = ""
            self.preview_label = host or stream_url
        if not stream_url:
            messagebox.showwarning("Pi Glasses", "Enter a Pi host/IP or click Find Glasses.")
            return

        self.close_cameras()
        self.current_stream_url = stream_url
        if hasattr(self.camera_backend, "set_urls"):
            self.camera_backend.set_urls(stream_url, "", world_label=self.preview_label)
        self.world_idx.set(0)
        self.eye_idx.set(1)
        if self.open_cameras():
            self.status.set(f"Connected Pi stream: {stream_url}")
        else:
            self.status.set(f"Could not open Pi stream: {stream_url}")

    # ---------- Serial ----------
    def on_find_port(self):
        self.status.set("Finding ESP32...")
        self.root.update_idletasks()

        def worker():
            p = find_esp32_port()

            def done():
                if not p:
                    self.status.set("ESP32 not found (enter COM manually)")
                else:
                    self.port_var.set(p)
                    self.status.set(f"Found {p}")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def on_connect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("ESP32", "Enter a COM port (e.g., COM7) or click Find.")
            return

        if self.ser:
            self.on_disconnect()

        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = 115200
            ser.timeout = SERIAL_PORT_TIMEOUT_S
            ser.write_timeout = SERIAL_SESSION_WRITE_TIMEOUT_S
            ser.dtr = SERIAL_SESSION_DTR
            ser.rts = SERIAL_SESSION_RTS
            ser.open()

            self.ser = ser
            self.ser.dtr = SERIAL_SESSION_DTR
            self.ser.rts = SERIAL_SESSION_RTS
            time.sleep(SERIAL_CONNECT_SETTLE_S)
            self.ser.reset_output_buffer()
            print(f"SER OPEN: {port} dtr={self.ser.dtr} rts={self.ser.rts}")
        except Exception as e:
            messagebox.showerror(
                "ESP32",
                f"Failed to open {port}: {e}\n\nClose Arduino Serial Monitor/Plotter."
            )
            self.ser = None
            return

        self.ser_stop.clear()
        self.ser_q = queue.Queue()
        self.ser_write_q = queue.Queue()
        self.ser_thread = threading.Thread(target=self.serial_reader, daemon=True)
        self.ser_writer_thread = threading.Thread(target=self.serial_writer, daemon=True)
        self.ser_thread.start()
        self.ser_writer_thread.start()

        self.status.set(f"Connected {port}")
        self.root.after(300, lambda: self.send_ser("STATUS?"))

    def on_disconnect(self, status_text="Disconnected"):
        self.ser_stop.set()
        self.ser_write_q.put(None)
        ser = self.ser
        self.ser = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass

        ser_thread = self.ser_thread
        if ser_thread and ser_thread.is_alive() and ser_thread is not threading.current_thread():
            ser_thread.join(timeout=0.5)
        self.ser_thread = None

        ser_writer_thread = self.ser_writer_thread
        if ser_writer_thread and ser_writer_thread.is_alive() and ser_writer_thread is not threading.current_thread():
            ser_writer_thread.join(timeout=0.5)
        self.ser_writer_thread = None
        self.status.set(status_text)

    def _disconnect_if_current(self, ser, status_text):
        if self.ser is ser:
            self.on_disconnect(status_text)

    def send_ser(self, s: str):
        if not self.ser:
            print("SER TX skipped:", s)
            return False
        print("SER TX:", s)
        self.ser_write_q.put(s.strip())
        return True

    def serial_writer(self):
        while not self.ser_stop.is_set():
            try:
                cmd = self.ser_write_q.get(timeout=0.1)
            except queue.Empty:
                continue

            if cmd is None:
                break

            ser = self.ser
            if not ser:
                continue

            try:
                ser.write((cmd + "\n").encode())
                ser.flush()
            except Exception as e:
                if not self.ser_stop.is_set() and self.ser is ser:
                    self.ser_q.put(("error", ser, f"write failed on {cmd}: {e}"))
                break

    def serial_reader(self):
        while not self.ser_stop.is_set():
            ser = self.ser
            if not ser:
                break
            try:
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print("SER RX:", line)
                    self.ser_q.put(("line", ser, line))
            except Exception as e:
                if not self.ser_stop.is_set():
                    self.ser_q.put(("error", ser, str(e)))
                break

    def _clear_frame_queues(self):
        with self.world_lock:
            self.world_q.clear()
        with self.eye_lock:
            self.eye_q.clear()

    def _start_camera_worker(self, cap, q, lock, frame_transform=None):
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.cam_thread,
            args=(cap, q, lock, stop_event, frame_transform),
            daemon=True,
        )
        self.camera_workers.append({
            "thread": thread,
            "stop_event": stop_event,
            "cap": cap,
        })
        thread.start()

    # ---------- Cameras ----------
    def on_scan_cameras(self):
        if self.rec_var.get():
            messagebox.showwarning("Cameras", "Stop recording before scanning cameras.")
            return

        self.status.set("Scanning cameras...")
        self.root.update_idletasks()
        self.close_cameras()

        def worker():
            cams = self.camera_backend.scan_cameras()
            w, e = self.camera_backend.auto_pick_world_eye(cams) if len(cams) >= 2 else (None, None)

            def done():
                if len(cams) < 2:
                    self.open_cameras()
                    self.status.set(f"Found {len(cams)} camera(s) - need 2")
                    return
                if w is not None and e is not None:
                    self.world_idx.set(w)
                    self.eye_idx.set(e)
                if self.open_cameras():
                    self.status.set(f"Found: {cams}. Picked world={self.world_idx.get()} eye={self.eye_idx.get()}")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def on_apply_cameras(self):
        if self.rec_var.get():
            messagebox.showwarning("Cameras", "Stop recording before applying new cameras.")
            return
        self.close_cameras()
        if self.open_cameras():
            self.status.set(f"Applied world={self.world_idx.get()} eye={self.eye_idx.get()}")

    def open_cameras(self):
        is_single_mjpeg = (
            self.camera_backend.name == "mjpeg"
            and hasattr(self.camera_backend, "stream_count")
            and self.camera_backend.stream_count() == 1
        )
        world_source = self.world_idx.get()
        eye_source = self.eye_idx.get()
        capW = self.camera_backend.open_cam(world_source)
        capE = None if is_single_mjpeg else self.camera_backend.open_cam(eye_source)
        if capW is None or (not is_single_mjpeg and capE is None):
            try:
                if capW is not None:
                    capW.release()
                if capE is not None:
                    capE.release()
            except Exception:
                pass
            if capW is None and (not is_single_mjpeg and capE is None):
                self.status.set(f"Failed to open scene camera {world_source} and eye camera {eye_source}.")
            elif capW is None:
                self.status.set(f"Failed to open scene camera {world_source}.")
            else:
                self.status.set(f"Failed to open eye camera {eye_source}.")
            return False

        self.camera_backend.try_mode(capW, WORLD_CAPTURE_WIDTH, WORLD_CAPTURE_HEIGHT, WORLD_CAPTURE_FPS)
        self.camera_backend.tune_world_camera(capW)
        if capE is not None:
            self.camera_backend.try_mode(capE, EYE_CAPTURE_WIDTH, EYE_CAPTURE_HEIGHT, EYE_CAPTURE_FPS)

        self.capW = capW
        self.capE = capE
        self.single_stream_preview = is_single_mjpeg
        if self.camera_backend.name == "mjpeg" and hasattr(self.camera_backend, "stream_label"):
            self.preview_label = self.camera_backend.stream_label(0)
        self._clear_frame_queues()
        self._start_camera_worker(
            self.capW,
            self.world_q,
            self.world_lock,
            frame_transform=lambda frame: cv2.rotate(frame, cv2.ROTATE_180),
        )
        if self.capE is not None:
            self._start_camera_worker(self.capE, self.eye_q, self.eye_lock)
        return True

    def cam_thread(self, cap, q, lock, stop_event, frame_transform=None):
        fail_count = 0
        while self.capture_running and not stop_event.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None

            if ok:
                fail_count = 0
                if frame_transform is not None:
                    frame = frame_transform(frame)
                with lock:
                    q.append((now_ns(), frame))
                continue

            fail_count += 1
            if fail_count >= CAM_READ_FAIL_LIMIT:
                break
            time.sleep(CAM_READ_FAIL_SLEEP_S)

    def close_cameras(self):
        for worker in self.camera_workers:
            worker["stop_event"].set()

        try:
            if self.capW is not None:
                self.capW.release()
            if self.capE is not None:
                self.capE.release()
        except Exception:
            pass

        for worker in self.camera_workers:
            thread = worker["thread"]
            if thread.is_alive():
                thread.join(timeout=0.5)

        self.camera_workers = []
        self.capW = None
        self.capE = None
        self._clear_frame_queues()
        cv2.destroyAllWindows()

    # ---------- Controls ----------
    def on_toggle_record(self):
        if self.camera_backend.name == "mjpeg":
            self.on_toggle_pi_record()
            return
        self.set_record(not self.rec_var.get(), send_to_esp=True)

    def on_toggle_pi_record(self):
        target_on = not self.rec_var.get()
        self.status.set("Starting Pi recording..." if target_on else "Stopping Pi recording...")
        self.root.update_idletasks()

        def worker():
            try:
                if target_on:
                    result = start_pi_recording(
                        status_url=self.current_status_url,
                        stream_url=self.current_stream_url,
                    )
                else:
                    result = stop_pi_recording(
                        status_url=self.current_status_url,
                        stream_url=self.current_stream_url,
                    )

                recording = bool(result.get("recording", {}).get("recording"))
                path = result.get("recording", {}).get("path")
                text = f"Pi recording {'started' if recording else 'stopped'}"
                if path:
                    text += f": {path}"

                def done():
                    self.set_record(recording, send_to_esp=False)
                    self.status.set(text)

                self.root.after(0, done)
            except Exception as exc:
                self.root.after(0, lambda: self.status.set(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def on_toggle_ir(self):
        self.set_ir(not self.ir_var.get(), send_to_esp=True)

    def on_brightness_change(self, _=None):
        v = int(self.brightness_var.get())
        if self.lbl_b is not None:
            self.lbl_b.config(text=str(v))

        if self._suppress_brightness_send:
            return

        now = time.monotonic()
        if self.ser and (now - self._last_b_send) > SERIAL_BRIGHTNESS_INTERVAL_S:
            self._last_b_send = now
            self.send_ser(f"B={v}")

    def set_brightness_from_device(self, value: int):
        value = max(0, min(255, int(value)))
        self._suppress_brightness_send = True
        try:
            self.brightness_var.set(value)
        finally:
            self._suppress_brightness_send = False
        if self.lbl_b is not None:
            self.lbl_b.config(text=str(value))

    def set_record(self, on: bool, send_to_esp: bool):
        self.rec_var.set(on)
        self.btn_rec.config(text="Record ON" if on else "Record OFF")
        if send_to_esp and self.ser:
            self.send_ser("REC=1" if on else "REC=0")

    def set_ir(self, on: bool, send_to_esp: bool):
        self.ir_var.set(on)
        if self.btn_ir is not None:
            self.btn_ir.config(text="IR ON" if on else "IR OFF")
        if send_to_esp and self.ser:
            self.send_ser("IR=1" if on else "IR=0")

    # ---------- Recording ----------
    def start_recording(self, combo):
        if self.writer is not None:
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        self.rec_path = os.path.join(self.outdir, f"poc_world_eye_{ts}.avi")
        self.csv_path = os.path.join(self.outdir, f"poc_world_eye_{ts}.csv")

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        h, w = combo.shape[:2]

        self.writer = cv2.VideoWriter(self.rec_path, fourcc, 30, (w, h))
        if not self.writer.isOpened():
            self.writer = None
            self.status.set("ERROR: Could not start recording")
            return

        self.csv_fh = open(self.csv_path, "w", encoding="utf-8", newline="\n")
        self.csv_fh.write("frame_idx,world_ts_ns,eye_ts_ns,dt_ms\n")
        self.csv_fh.flush()
        self.frame_idx = 0

        self.status.set(f"Recording -> {self.rec_path}")

    def stop_recording(self):
        if self.writer is None:
            return

        try:
            self.writer.release()
        except Exception:
            pass
        self.writer = None

        try:
            if self.csv_fh:
                self.csv_fh.flush()
                self.csv_fh.close()
        except Exception:
            pass
        self.csv_fh = None

        self.status.set(f"Saved: {self.rec_path}")

    def _record_preview_frame(self, combo, tw, te, dt_ms):
        if self.camera_backend.name == "mjpeg":
            return
        if self.rec_var.get():
            self.start_recording(combo)
            if self.writer is not None:
                self.writer.write(combo)
                if self.csv_fh is not None:
                    self.csv_fh.write(f"{self.frame_idx},{tw},{te},{dt_ms:.4f}\n")
                    self.frame_idx += 1
        else:
            if self.writer is not None:
                self.stop_recording()

    def _build_single_stream_preview(self, tw, frame):
        combo = cv2.resize(
            frame,
            (WORLD_DISPLAY_WIDTH, WORLD_DISPLAY_HEIGHT),
            interpolation=cv2.INTER_CUBIC,
        )
        cv2.putText(combo, str(self.preview_label), (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(combo, f"ts(ns)={tw}", (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        cv2.putText(combo,
                    f"REC={'ON' if self.rec_var.get() else 'OFF'}",
                    (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        return combo

    def _build_dual_preview(self, tw, fw, te, fe, dt_ms):
        fw_disp = cv2.resize(fw, (WORLD_DISPLAY_WIDTH, WORLD_DISPLAY_HEIGHT), interpolation=cv2.INTER_CUBIC)
        fe_disp = cv2.resize(fe, (EYE_DISPLAY_WIDTH, EYE_DISPLAY_HEIGHT), interpolation=cv2.INTER_CUBIC)
        fe_disp = cv2.copyMakeBorder(
            fe_disp,
            EYE_PAD_TOP,
            EYE_PAD_BOTTOM,
            0,
            0,
            cv2.BORDER_CONSTANT,
        )
        combo = cv2.hconcat([fw_disp, fe_disp])

        cv2.putText(combo, f"W ts(ns)={tw}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        cv2.putText(combo, f"E ts(ns)={te}  dt={dt_ms:+.2f}ms", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        status_text = f"REC={'ON' if self.rec_var.get() else 'OFF'}"
        if self.camera_backend.name != "mjpeg":
            status_text += f" IR={'ON' if self.ir_var.get() else 'OFF'} B={int(self.brightness_var.get())}"
        cv2.putText(combo, status_text, (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        return combo

    # ---------- Main tick ----------
    def tick(self):
        # process serial events
        while True:
            try:
                item = self.ser_q.get_nowait()
            except queue.Empty:
                break

            if isinstance(item, tuple) and len(item) == 3:
                kind, event_ser, payload = item
            else:
                kind, event_ser, payload = "line", None, item

            if kind == "error":
                if event_ser is self.ser and (self.ser or (self.ser_thread and self.ser_thread.is_alive())):
                    self.on_disconnect(f"ESP32 disconnected: {payload}")
                continue

            if event_ser is not None and event_ser is not self.ser:
                continue

            line = payload
            if "REC=1" in line:
                self.set_record(True, send_to_esp=False)
            elif "REC=0" in line:
                self.set_record(False, send_to_esp=False)

            if "IR=1" in line:
                self.set_ir(True, send_to_esp=False)
            elif "IR=0" in line:
                self.set_ir(False, send_to_esp=False)

            brightness = extract_prefixed_int(line, "B=")
            if brightness is not None:
                self.set_brightness_from_device(brightness)

        # display + record
        with self.world_lock:
            world_item = self.world_q[-1] if self.world_q else None
        with self.eye_lock:
            eye_items = list(self.eye_q)

        if self.single_stream_preview and world_item:
            tw, fw = world_item
            combo = self._build_single_stream_preview(tw, fw)

            cv2.imshow("World | Eye", combo)
            self._record_preview_frame(combo, tw, tw, 0.0)

        elif world_item and eye_items:
            tw, fw = world_item
            te, fe = min(eye_items, key=lambda x: abs(x[0] - tw))
            dt_ms = (tw - te) / 1e6

            combo = self._build_dual_preview(tw, fw, te, fe, dt_ms)

            cv2.imshow("World | Eye", combo)
            self._record_preview_frame(combo, tw, te, dt_ms)
        elif not self.rec_var.get() and self.writer is not None:
            self.stop_recording()

        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'):
            self.on_quit()
            return
        elif k == ord('r'):
            self.on_toggle_record()

        self.root.after(30, self.tick)

    def on_capture_snapshot(self):
        if self.camera_backend.name != "mjpeg":
            return
        self.status.set("Capturing Pi snapshot...")
        self.root.update_idletasks()

        def worker():
            try:
                result = capture_snapshot(
                    status_url=self.current_status_url,
                    stream_url=self.current_stream_url,
                )
                text = f"Snapshot saved: {result.get('path') or result.get('filename')}"
            except Exception as exc:
                text = str(exc)

            self.root.after(0, lambda: self.status.set(text))

        threading.Thread(target=worker, daemon=True).start()

    def on_quit(self):
        self.capture_running = False
        self.on_disconnect()
        if self.writer is not None:
            self.stop_recording()
        self.close_cameras()
        try:
            self.root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    if platform.system().lower() == "linux" and not os.environ.get("DISPLAY"):
        print("GUI mode requires DISPLAY. Use the headless stream service for systemd.", file=sys.stderr)
        raise SystemExit(2)
    App(load_config()).root.mainloop()
