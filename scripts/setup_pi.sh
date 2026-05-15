#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Jkessler3/SmartGlassesPoC.git}"
INSTALL_USER="${INSTALL_USER:-user}"
INSTALL_DIR="${INSTALL_DIR:-/home/${INSTALL_USER}/SmartGlassesPoC}"
SERVICE_NAME="${SERVICE_NAME:-smart-glasses-stream.service}"
GLASSES_NAME="${GLASSES_NAME:-glasses-left}"
STREAM_WIDTH="${STREAM_WIDTH:-640}"
STREAM_HEIGHT="${STREAM_HEIGHT:-480}"
STREAM_FPS="${STREAM_FPS:-15}"
INPUT_ORDER="${INPUT_ORDER:-bgr}"
ENABLE_GPIO="${ENABLE_GPIO:-0}"
BUTTON_PIN="${BUTTON_PIN:-${BUTTON_GPIO:-17}}"
LED_PIN="${LED_PIN:-${STATUS_LED_GPIO:-27}}"
if [[ -z "${SERVICE_EXEC_START:-}" && "${DEVICE_PROFILE:-}" == "cm5" ]]; then
  SERVICE_EXEC_START="${INSTALL_DIR}/scripts/run_cm5_stream.sh"
fi
SERVICE_EXEC_START="${SERVICE_EXEC_START:-/usr/bin/python3 ${INSTALL_DIR}/scripts/pi_wifi_stream.py --name ${GLASSES_NAME} --width ${STREAM_WIDTH} --height ${STREAM_HEIGHT} --fps ${STREAM_FPS} --input-order ${INPUT_ORDER}}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo:"
  echo "  sudo bash scripts/setup_pi.sh"
  exit 1
fi

if ! id "${INSTALL_USER}" >/dev/null 2>&1; then
  echo "User '${INSTALL_USER}' does not exist."
  exit 1
fi

echo "Installing Raspberry Pi packages..."
apt-get update
apt-get install -y \
  git \
  curl \
  v4l-utils \
  libcamera-apps \
  i2c-tools \
  gpiod \
  python3-picamera2 \
  python3-opencv \
  python3-serial \
  python3-tk \
  python3-gpiozero

if apt-cache show python3-lgpio >/dev/null 2>&1; then
  apt-get install -y python3-lgpio
fi

echo "Installing repo into ${INSTALL_DIR}..."
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  sudo -u "${INSTALL_USER}" git -C "${INSTALL_DIR}" pull
else
  install -d -o "${INSTALL_USER}" -g "${INSTALL_USER}" "$(dirname "${INSTALL_DIR}")"
  sudo -u "${INSTALL_USER}" git clone "${REPO_URL}" "${INSTALL_DIR}"
fi
chown -R "${INSTALL_USER}:${INSTALL_USER}" "${INSTALL_DIR}"

GPIO_ARGS=""
if [[ "${ENABLE_GPIO}" == "1" ]]; then
  GPIO_ARGS=" --enable-gpio --button-pin ${BUTTON_PIN} --led-pin ${LED_PIN}"
fi
if [[ "${ENABLE_GPIO}" == "1" && "${SERVICE_EXEC_START}" == *"pi_wifi_stream.py"* ]]; then
  SERVICE_EXEC_START="${SERVICE_EXEC_START}${GPIO_ARGS}"
fi

echo "Writing ${SERVICE_NAME}..."
cat >"/etc/systemd/system/${SERVICE_NAME}" <<SERVICE
[Unit]
Description=Smart Glasses Pi camera stream
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${INSTALL_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${SERVICE_EXEC_START}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo
echo "Smart Glasses stream service installed and started."
echo "Status:"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
echo
echo "Find the Pi IP with:"
echo "  hostname -I"
echo
echo "View logs with:"
echo "  journalctl -u ${SERVICE_NAME} -f"
