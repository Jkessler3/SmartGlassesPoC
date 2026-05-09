import argparse
import os
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    camera_backend: str
    outdir: str


def default_outdir():
    if platform.system().lower() == "windows":
        return r"C:\poc_out"
    return os.path.expanduser("~/poc_out")


def load_config(argv=None):
    parser = argparse.ArgumentParser(description="Smart Glasses PoC")
    parser.add_argument(
        "--camera-backend",
        choices=("auto", "opencv", "picamera2"),
        default=os.environ.get("SMARTGLASSES_CAMERA_BACKEND", "auto"),
        help="Camera backend to use. Defaults to auto.",
    )
    parser.add_argument(
        "--outdir",
        default=os.environ.get("SMARTGLASSES_OUTDIR", default_outdir()),
        help="Directory for AVI/CSV recordings.",
    )
    args = parser.parse_args(argv)
    return AppConfig(camera_backend=args.camera_backend, outdir=args.outdir)
