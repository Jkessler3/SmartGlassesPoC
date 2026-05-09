import time

import cv2


name = "picamera2"


def _picamera2():
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError(
            "Picamera2 is not installed. On Raspberry Pi OS Bookworm, install it "
            "with: sudo apt install -y python3-picamera2"
        ) from exc
    return Picamera2


def assert_available():
    _picamera2()


class PiCameraSource:
    def __init__(self, idx: int):
        Picamera2 = _picamera2()
        self.idx = int(idx)
        self.picam = Picamera2(camera_num=self.idx)
        self.width = 640
        self.height = 480
        self.fps = 30
        self.started = False

    def set(self, prop, value):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            self.width = int(value)
        elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
            self.height = int(value)
        elif prop == cv2.CAP_PROP_FPS:
            self.fps = int(value)
        return True

    def _start_if_needed(self):
        if self.started:
            return
        config = self.picam.create_video_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"},
            controls={"FrameRate": self.fps},
        )
        self.picam.configure(config)
        self.picam.start()
        time.sleep(0.2)
        self.started = True

    def read(self):
        try:
            self._start_if_needed()
            frame = self.picam.capture_array()
            if frame is None:
                return False, None
            return True, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        except Exception:
            return False, None

    def release(self):
        try:
            self.picam.stop()
        except Exception:
            pass
        try:
            self.picam.close()
        except Exception:
            pass
        self.started = False


def open_cam(idx: int):
    try:
        return PiCameraSource(idx)
    except Exception:
        return None


def try_mode(cap, w, h, fps):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(w))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(h))
    cap.set(cv2.CAP_PROP_FPS, int(fps))


def scan_cameras(max_idx=10):
    Picamera2 = _picamera2()
    try:
        infos = Picamera2.global_camera_info()
    except Exception:
        infos = []

    cams = []
    for i, info in enumerate(infos[:max_idx]):
        model = str(info.get("Model", info.get("model", ""))).lower()
        grayish = any(token in model for token in ("mono", "imx296", "ov9281"))
        cams.append({"idx": i, "fps_est": 0.0, "grayish": grayish, "model": model})
    return cams


def auto_pick_world_eye(cams):
    if len(cams) < 2:
        return None, None

    gray = [c for c in cams if c.get("grayish")]
    eye = gray[0]["idx"] if gray else cams[1]["idx"]
    world = next((c["idx"] for c in cams if c["idx"] != eye), cams[0]["idx"])
    return world, eye


def tune_world_camera(cap):
    return None
