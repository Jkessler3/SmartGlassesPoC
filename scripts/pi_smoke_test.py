#!/usr/bin/env python3
import argparse
import time

import serial
from serial.tools import list_ports


def print_section(title):
    print()
    print(f"== {title} ==")


def check_picamera2(capture=False):
    print_section("Picamera2")
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        print("Picamera2 import failed.")
        print("Install with: sudo apt install -y python3-picamera2")
        print(f"Error: {exc}")
        return False

    try:
        infos = Picamera2.global_camera_info()
    except Exception as exc:
        print(f"Could not list cameras: {exc}")
        return False

    if not infos:
        print("No Picamera2/libcamera cameras reported.")
        print("Try: rpicam-hello --list-cameras")
        return False

    print(f"Detected {len(infos)} camera(s):")
    for idx, info in enumerate(infos):
        print(f"  camera {idx}: {info}")

    if not capture:
        return True

    ok = True
    for idx in range(len(infos)):
        print(f"Capturing one frame from camera {idx}...")
        picam = None
        try:
            picam = Picamera2(camera_num=idx)
            config = picam.create_video_configuration(
                main={"size": (640, 480), "format": "RGB888"},
                controls={"FrameRate": 30},
            )
            picam.configure(config)
            picam.start()
            time.sleep(0.5)
            frame = picam.capture_array()
            print(f"  frame shape: {getattr(frame, 'shape', None)}")
        except Exception as exc:
            ok = False
            print(f"  capture failed: {exc}")
        finally:
            if picam is not None:
                try:
                    picam.stop()
                except Exception:
                    pass
                try:
                    picam.close()
                except Exception:
                    pass

    return ok


def check_serial(probe=False, baud=115200):
    print_section("Serial")
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return False

    print("Detected serial ports:")
    for port in ports:
        print(f"  {port.device}: {port.description} [{port.hwid}]")

    if not probe:
        return True

    found = False
    for port in ports:
        desc = (port.description or "").lower()
        hwid = (port.hwid or "").lower()
        if "bluetooth" in desc or "bthenum" in hwid:
            continue

        print(f"Probing {port.device}...")
        ser = serial.Serial()
        ser.port = port.device
        ser.baudrate = baud
        ser.timeout = 0.25
        ser.write_timeout = 0.25
        ser.dtr = True
        ser.rts = False
        try:
            ser.open()
            time.sleep(0.5)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"ID?\n")
            ser.flush()

            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    print(f"  RX: {line}")
                if "XIAO_REC_CTRL" in line:
                    found = True
        except Exception as exc:
            print(f"  probe failed: {exc}")
        finally:
            try:
                ser.close()
            except Exception:
                pass

    if found:
        print("Found ESP32 controller.")
    else:
        print("ESP32 controller ID was not detected.")
    return found


def main():
    parser = argparse.ArgumentParser(description="Headless Raspberry Pi smoke test")
    parser.add_argument("--capture", action="store_true", help="Capture one frame from each camera.")
    parser.add_argument("--probe-serial", action="store_true", help="Send ID? to detected serial ports.")
    args = parser.parse_args()

    camera_ok = check_picamera2(capture=args.capture)
    serial_ok = check_serial(probe=args.probe_serial)

    print_section("Result")
    print(f"cameras: {'ok' if camera_ok else 'check needed'}")
    print(f"serial:  {'ok' if serial_ok else 'check needed'}")


if __name__ == "__main__":
    main()
