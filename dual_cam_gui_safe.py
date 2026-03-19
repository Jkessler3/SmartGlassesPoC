import os
import time
import threading
import queue
from collections import deque
import tkinter as tk
from tkinter import ttk, messagebox

import cv2
import numpy as np
import serial
from serial.tools import list_ports

CAM_READ_FAIL_LIMIT = 100
CAM_READ_FAIL_SLEEP_S = 0.02
SERIAL_PROBE_STARTUP_S = 0.35
SERIAL_PROBE_WINDOW_S = 0.60
SERIAL_STATUS_POLL_S = 2.0
SERIAL_CONNECT_SETTLE_S = 0.35
SERIAL_PORT_TIMEOUT_S = 0.10
SERIAL_WRITE_TIMEOUT_S = 0.25
SERIAL_WRITE_TIMEOUT_LIMIT = 3


# ---------- Timing ----------
def now_ns():
    return time.perf_counter_ns()


# ---------- Camera helpers ----------
def open_cam(idx: int):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if cap is not None and cap.isOpened():
        return cap
    cap = cv2.VideoCapture(idx)
    if cap is None or not cap.isOpened():
        return None
    return cap

def try_mode(cap, w, h, fps):
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(w))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(h))
    cap.set(cv2.CAP_PROP_FPS, int(fps))

def estimate_fps(cap, frames=20):
    t0 = time.time()
    got = 0
    for _ in range(frames):
        ok, _ = cap.read()
        if ok:
            got += 1
    dt = time.time() - t0
    return (got / dt) if dt > 0 else 0.0

def is_grayscale_like(frame):
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        return True
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    return (np.mean(np.abs(b - g)) + np.mean(np.abs(g - r))) < 1.0

def scan_cameras(max_idx=10):
    cams = []
    for i in range(max_idx):
        cap = open_cam(i)
        if cap is None:
            continue
        try_mode(cap, 640, 480, 60)
        ok, frame = cap.read()
        fps = estimate_fps(cap)
        grayish = is_grayscale_like(frame) if ok else False
        cap.release()
        cams.append({"idx": i, "fps_est": round(fps, 1), "grayish": bool(grayish)})
    return cams

def auto_pick_world_eye(cams):
    if len(cams) < 2:
        return None, None
    sorted_cams = sorted(cams, key=lambda c: (c["grayish"], c["fps_est"]), reverse=True)
    eye = sorted_cams[0]["idx"]
    world = None
    for c in sorted_cams[1:]:
        if c["idx"] != eye:
            world = c["idx"]
            break
    if world is None:
        world = sorted_cams[1]["idx"]
    return world, eye


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
    ser = serial.Serial(dev, baud, timeout=SERIAL_PORT_TIMEOUT_S, write_timeout=SERIAL_WRITE_TIMEOUT_S)
    try:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass

        ser.reset_input_buffer()
        time.sleep(SERIAL_PROBE_STARTUP_S)
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
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Smart Glasses PoC (GUI + Dual Cam)")

        # Tk state
        self.world_idx = tk.IntVar(value=0)
        self.eye_idx = tk.IntVar(value=1)
        self.port_var = tk.StringVar(value="")
        self.rec_var = tk.BooleanVar(value=False)
        self.ir_var = tk.BooleanVar(value=False)
        self.brightness_var = tk.IntVar(value=255)
        self.status = tk.StringVar(value="Ready")

        # Serial
        self.ser = None
        self.ser_thread = None
        self.ser_stop = threading.Event()
        self.ser_q = queue.Queue()
        self._last_status_poll = 0.0
        self._ser_write_timeout_count = 0
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
        self.outdir = r"C:\poc_out"
        os.makedirs(self.outdir, exist_ok=True)

        # throttle brightness serial spam
        self._last_b_send = 0.0

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

        self.open_cameras()
        self.root.after(30, self.tick)

    # ---------- UI ----------
    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        cam_box = ttk.LabelFrame(frm, text="Cameras", padding=10)
        cam_box.grid(row=0, column=0, sticky="ew")

        ttk.Button(cam_box, text="Scan Cameras", command=self.on_scan_cameras).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(cam_box, text="World index").grid(row=1, column=0, sticky="w")
        ttk.Entry(cam_box, textvariable=self.world_idx, width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(cam_box, text="Eye index").grid(row=2, column=0, sticky="w")
        ttk.Entry(cam_box, textvariable=self.eye_idx, width=6).grid(row=2, column=1, sticky="w")
        ttk.Button(cam_box, text="Apply Cameras", command=self.on_apply_cameras).grid(row=3, column=0, columnspan=2, pady=5)

        ser_box = ttk.LabelFrame(frm, text="ESP32 Serial", padding=10)
        ser_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ttk.Button(ser_box, text="Find ESP32", command=self.on_find_port).grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(ser_box, text="Port").grid(row=0, column=1)
        ttk.Entry(ser_box, textvariable=self.port_var, width=10).grid(row=0, column=2)
        ttk.Button(ser_box, text="Connect", command=self.on_connect).grid(row=0, column=3, padx=5)
        ttk.Button(ser_box, text="Disconnect", command=self.on_disconnect).grid(row=0, column=4, padx=5)

        ctl_box = ttk.LabelFrame(frm, text="Controls", padding=10)
        ctl_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        self.btn_rec = ttk.Button(ctl_box, text="Record OFF", command=self.on_toggle_record)
        self.btn_rec.grid(row=0, column=0, padx=5, pady=5)

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

        ttk.Button(ctl_box, text="Quit", command=self.on_quit).grid(row=3, column=0, columnspan=2, pady=5)

        ttk.Label(frm, textvariable=self.status).grid(row=3, column=0, sticky="ew", pady=(10, 0))

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
            self.ser = serial.Serial(
                port,
                115200,
                timeout=SERIAL_PORT_TIMEOUT_S,
                write_timeout=SERIAL_WRITE_TIMEOUT_S,
            )
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(SERIAL_CONNECT_SETTLE_S)
            self.ser.reset_input_buffer()
        except Exception as e:
            messagebox.showerror(
                "ESP32",
                f"Failed to open {port}: {e}\n\nClose Arduino Serial Monitor/Plotter."
            )
            self.ser = None
            return

        self.ser_stop.clear()
        self._ser_write_timeout_count = 0
        self.ser_thread = threading.Thread(target=self.serial_reader, daemon=True)
        self.ser_thread.start()
        self._last_status_poll = time.monotonic()

        # ask for state after things settle
        self.root.after(300, lambda: self.send_ser("STATUS?"))

        self.status.set(f"Connected {port}")

    def on_disconnect(self, status_text="Disconnected"):
        self.ser_stop.set()
        ser = self.ser
        self.ser = None
        self._ser_write_timeout_count = 0
        if ser:
            try:
                ser.close()
            except Exception:
                pass

        ser_thread = self.ser_thread
        if ser_thread and ser_thread.is_alive() and ser_thread is not threading.current_thread():
            ser_thread.join(timeout=0.5)
        self.ser_thread = None
        self.status.set(status_text)

    def _disconnect_if_current(self, ser, status_text):
        if self.ser is ser:
            self.on_disconnect(status_text)

    def send_ser(self, s: str):
        ser = self.ser
        if not ser:
            return False
        try:
            ser.write((s.strip() + "\n").encode())
            self._ser_write_timeout_count = 0
            return True
        except serial.SerialTimeoutException:
            if self.ser is not ser or self.ser_stop.is_set():
                return False

            self._ser_write_timeout_count += 1
            try:
                ser.reset_output_buffer()
            except Exception:
                pass

            if self._ser_write_timeout_count >= SERIAL_WRITE_TIMEOUT_LIMIT:
                self.root.after(
                    0,
                    lambda current_ser=ser: self._disconnect_if_current(
                        current_ser,
                        "ESP32 disconnected after repeated write timeouts",
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda attempt=self._ser_write_timeout_count, cmd=s.strip(): self.status.set(
                        f"ESP32 write timeout ({attempt}/{SERIAL_WRITE_TIMEOUT_LIMIT}) on {cmd}"
                    ),
                )
            return False
        except Exception as e:
            if not self.ser_stop.is_set() and self.ser is ser:
                self.root.after(
                    0,
                    lambda current_ser=ser, msg=f"ESP32 disconnected: {e}": self._disconnect_if_current(current_ser, msg)
                )
            return False

    def serial_reader(self):
        while not self.ser_stop.is_set():
            ser = self.ser
            if not ser:
                break
            try:
                if ser.in_waiting:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        self._ser_write_timeout_count = 0
                        self.ser_q.put(("line", ser, line))
                else:
                    time.sleep(0.01)
            except Exception as e:
                if not self.ser_stop.is_set():
                    self.ser_q.put(("error", ser, str(e)))
                break

    def _clear_frame_queues(self):
        with self.world_lock:
            self.world_q.clear()
        with self.eye_lock:
            self.eye_q.clear()

    def _start_camera_worker(self, cap, q, lock):
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.cam_thread,
            args=(cap, q, lock, stop_event),
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
            cams = scan_cameras()
            w, e = auto_pick_world_eye(cams) if len(cams) >= 2 else (None, None)

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
        capW = open_cam(self.world_idx.get())
        capE = open_cam(self.eye_idx.get())
        if capW is None or capE is None:
            try:
                if capW is not None:
                    capW.release()
                if capE is not None:
                    capE.release()
            except Exception:
                pass
            self.status.set("Failed to open cameras. Scan/apply again.")
            return False

        try_mode(capW, 1280, 720, 30)
        try_mode(capE, 640, 480, 60)

        self.capW = capW
        self.capE = capE
        self._clear_frame_queues()
        self._start_camera_worker(self.capW, self.world_q, self.world_lock)
        self._start_camera_worker(self.capE, self.eye_q, self.eye_lock)
        return True

    def cam_thread(self, cap, q, lock, stop_event):
        fail_count = 0
        while self.capture_running and not stop_event.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None

            if ok:
                fail_count = 0
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
        self.set_record(not self.rec_var.get(), send_to_esp=True)

    def on_toggle_ir(self):
        self.set_ir(not self.ir_var.get(), send_to_esp=True)

    def on_brightness_change(self, _=None):
        v = int(self.brightness_var.get())
        self.lbl_b.config(text=str(v))

        if self._suppress_brightness_send:
            return

        now = time.monotonic()
        if self.ser and (now - self._last_b_send) > 0.05:
            self._last_b_send = now
            self.send_ser(f"B={v}")

    def set_brightness_from_device(self, value: int):
        value = max(0, min(255, int(value)))
        self._suppress_brightness_send = True
        try:
            self.brightness_var.set(value)
        finally:
            self._suppress_brightness_send = False
        self.lbl_b.config(text=str(value))

    def set_record(self, on: bool, send_to_esp: bool):
        self.rec_var.set(on)
        self.btn_rec.config(text="Record ON" if on else "Record OFF")
        if send_to_esp and self.ser:
            self.send_ser("REC=1" if on else "REC=0")

    def set_ir(self, on: bool, send_to_esp: bool):
        self.ir_var.set(on)
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

        now = time.monotonic()
        if self.ser and (now - self._last_status_poll) > SERIAL_STATUS_POLL_S:
            self._last_status_poll = now
            self.send_ser("STATUS?")

        # display + record
        with self.world_lock:
            world_item = self.world_q[-1] if self.world_q else None
        with self.eye_lock:
            eye_items = list(self.eye_q)

        if world_item and eye_items:
            tw, fw = world_item
            te, fe = min(eye_items, key=lambda x: abs(x[0] - tw))
            dt_ms = (tw - te) / 1e6

            fw_disp = cv2.resize(fw, (960, 540))
            fe_disp = cv2.resize(fe, (960, 540))
            combo = cv2.hconcat([fw_disp, fe_disp])

            cv2.putText(combo, f"W ts(ns)={tw}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            cv2.putText(combo, f"E ts(ns)={te}  dt={dt_ms:+.2f}ms", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            cv2.putText(combo,
                        f"REC={'ON' if self.rec_var.get() else 'OFF'} IR={'ON' if self.ir_var.get() else 'OFF'} B={int(self.brightness_var.get())}",
                        (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

            cv2.imshow("World | Eye", combo)

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

        k = cv2.waitKey(1) & 0xFF
        if k == ord('q'):
            self.on_quit()
            return
        elif k == ord('r'):
            self.set_record(not self.rec_var.get(), send_to_esp=True)

        self.root.after(30, self.tick)

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
    App().root.mainloop()
