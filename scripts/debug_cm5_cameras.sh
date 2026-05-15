#!/usr/bin/env bash
set -u

print_section() {
  echo
  echo "== $1 =="
}

print_section "Model"
cat /proc/device-tree/model 2>/dev/null || true

print_section "Kernel"
uname -a || true

print_section "Camera config lines"
grep -n "camera_auto_detect\|dtoverlay.*imx\|dtoverlay.*ov\|dtoverlay.*arducam\|vc4-kms" /boot/firmware/config.txt || true

print_section "rpicam cameras"
rpicam-hello --list-cameras || true

print_section "v4l2 devices"
v4l2-ctl --list-devices || true

print_section "Video nodes"
ls -l /dev/video* || true

print_section "Camera-related dmesg"
dmesg | grep -iE "imx|ov|arducam|unicam|csi|camera|i2c" | tail -120 || true
