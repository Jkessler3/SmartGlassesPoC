import platform

import cv2
import numpy as np


name = "opencv"


def open_cam(idx: int):
    if platform.system().lower() == "windows":
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
    t0 = cv2.getTickCount()
    got = 0
    for _ in range(frames):
        ok, _ = cap.read()
        if ok:
            got += 1
    dt = (cv2.getTickCount() - t0) / cv2.getTickFrequency()
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


def tune_world_camera(cap):
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    cap.set(cv2.CAP_PROP_FOCUS, 20)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 0.5)
    cap.set(cv2.CAP_PROP_CONTRAST, 0.5)
    cap.set(cv2.CAP_PROP_SATURATION, 0.5)
