import argparse
import os
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    camera_backend: str
    outdir: str
    world_url: str
    eye_url: str


def default_outdir():
    if platform.system().lower() == "windows":
        return r"C:\poc_out"
    return os.path.expanduser("~/poc_out")


def load_config(argv=None):
    parser = argparse.ArgumentParser(description="Smart Glasses PoC")
    parser.add_argument(
        "--camera-backend",
        choices=("auto", "opencv", "picamera2", "mjpeg"),
        default=os.environ.get("SMARTGLASSES_CAMERA_BACKEND", "auto"),
        help="Camera backend to use. Defaults to auto.",
    )
    parser.add_argument(
        "--outdir",
        default=os.environ.get("SMARTGLASSES_OUTDIR", default_outdir()),
        help="Directory for AVI/CSV recordings.",
    )
    parser.add_argument(
        "--world-url",
        default=os.environ.get("SMARTGLASSES_WORLD_URL", ""),
        help="MJPEG/HTTP stream URL for the world camera backend.",
    )
    parser.add_argument(
        "--eye-url",
        default=os.environ.get("SMARTGLASSES_EYE_URL", ""),
        help="Optional MJPEG/HTTP stream URL for the eye camera backend.",
    )
    args = parser.parse_args(argv)
    return AppConfig(
        camera_backend=args.camera_backend,
        outdir=args.outdir,
        world_url=args.world_url,
        eye_url=args.eye_url,
    )
