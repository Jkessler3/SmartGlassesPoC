import platform


def load_camera_backend(name="auto"):
    selected = (name or "auto").lower()

    if selected == "auto":
        if platform.system().lower() == "linux":
            try:
                from . import picamera2_dual

                picamera2_dual.assert_available()
                return picamera2_dual
            except Exception:
                pass
        from . import opencv_uvc

        return opencv_uvc

    if selected == "opencv":
        from . import opencv_uvc

        return opencv_uvc

    if selected == "picamera2":
        from . import picamera2_dual

        picamera2_dual.assert_available()
        return picamera2_dual

    if selected == "mjpeg":
        from . import mjpeg_stream

        return mjpeg_stream

    raise ValueError(f"Unknown camera backend: {name}")
