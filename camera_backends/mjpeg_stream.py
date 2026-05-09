import cv2


name = "mjpeg"
_world_url = ""
_eye_url = ""


def configure(config):
    global _world_url, _eye_url
    _world_url = config.world_url
    _eye_url = config.eye_url or config.world_url


def _url_for_idx(idx):
    if int(idx) == 0:
        return _world_url
    return _eye_url


def open_cam(idx: int):
    url = _url_for_idx(idx)
    if not url:
        return None

    cap = cv2.VideoCapture(url)
    if cap is None or not cap.isOpened():
        return None
    return cap


def try_mode(cap, w, h, fps):
    return None


def scan_cameras(max_idx=10):
    cams = []
    if _world_url:
        cams.append({"idx": 0, "fps_est": 0.0, "grayish": False, "source": _world_url})
    if _eye_url and _eye_url != _world_url:
        cams.append({"idx": 1, "fps_est": 0.0, "grayish": True, "source": _eye_url})
    elif _world_url:
        cams.append({"idx": 1, "fps_est": 0.0, "grayish": True, "source": _world_url})
    return cams


def auto_pick_world_eye(cams):
    if len(cams) < 2:
        return None, None
    return cams[0]["idx"], cams[1]["idx"]


def tune_world_camera(cap):
    return None
