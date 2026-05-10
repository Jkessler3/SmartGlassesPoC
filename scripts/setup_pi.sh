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
BUTTON_PIN="${BUTTON_PIN:-17}"
LED_PIN="${LED_PIN:-27}"

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
  python3-picamera2 \
  python3-opencv \
  python3-serial \
  python3-tk \
  python3-gpiozero

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
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/scripts/pi_wifi_stream.py --name ${GLASSES_NAME} --width ${STREAM_WIDTH} --height ${STREAM_HEIGHT} --fps ${STREAM_FPS} --input-order ${INPUT_ORDER}${GPIO_ARGS}
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
