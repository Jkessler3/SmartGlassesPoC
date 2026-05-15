import argparse
import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    camera_backend: str
    outdir: str
    world_url: str
    eye_url: str
    scene_camera: str
    eye_camera: str


def load_env_file(path):
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def default_outdir():
    if platform.system().lower() == "windows":
        return r"C:\poc_out"
    return os.path.expanduser("~/poc_out")


def load_config(argv=None):
    if "DEVICE_PROFILE" in os.environ:
        env_path = Path(__file__).resolve().parent / "config" / f"{os.environ['DEVICE_PROFILE']}.env"
        load_env_file(env_path)

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
    parser.add_argument(
        "--scene-camera",
        default=os.environ.get("SCENE_CAMERA", "0"),
        help="Scene/world camera device. Use an index such as 0 or a path such as /dev/video0.",
    )
    parser.add_argument(
        "--eye-camera",
        default=os.environ.get("EYE_CAMERA", "1"),
        help="Eye camera device. Use an index such as 1 or a path such as /dev/video1.",
    )
    args = parser.parse_args(argv)
    return AppConfig(
        camera_backend=args.camera_backend,
        outdir=args.outdir,
        world_url=args.world_url,
        eye_url=args.eye_url,
        scene_camera=args.scene_camera,
        eye_camera=args.eye_camera,
    )
