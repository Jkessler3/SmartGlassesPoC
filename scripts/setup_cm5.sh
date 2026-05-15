#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DEVICE_PROFILE="${DEVICE_PROFILE:-cm5}"
export GLASSES_NAME="${GLASSES_NAME:-glasses-cm5}"
export STREAM_WIDTH="${STREAM_WIDTH:-1280}"
export STREAM_HEIGHT="${STREAM_HEIGHT:-720}"
export STREAM_FPS="${STREAM_FPS:-30}"
export SERVICE_NAME="${SERVICE_NAME:-smart-glasses-stream.service}"

bash "$SCRIPT_DIR/setup_pi.sh"
