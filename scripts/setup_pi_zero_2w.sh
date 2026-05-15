#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export DEVICE_PROFILE="${DEVICE_PROFILE:-pi_zero_2w}"
export GLASSES_NAME="${GLASSES_NAME:-glasses-zero2w}"
export STREAM_WIDTH="${STREAM_WIDTH:-640}"
export STREAM_HEIGHT="${STREAM_HEIGHT:-480}"
export STREAM_FPS="${STREAM_FPS:-10}"

bash "$SCRIPT_DIR/setup_pi.sh"
