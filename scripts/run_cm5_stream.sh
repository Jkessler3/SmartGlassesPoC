#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$REPO_ROOT/config/cm5.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing CM5 config file: $CONFIG_FILE" >&2
  exit 1
fi

set -a
source "$CONFIG_FILE"
set +a

export DEVICE_PROFILE="${DEVICE_PROFILE:-cm5}"
export SMARTGLASSES_CAMERA_BACKEND="${SMARTGLASSES_CAMERA_BACKEND:-picamera2}"
export SCENE_CAMERA="${SCENE_CAMERA:-0}"
export EYE_CAMERA="${EYE_CAMERA:-1}"
export SMARTGLASSES_OUTDIR="${SMARTGLASSES_OUTDIR:-/home/user/poc_out}"
export GLASSES_NAME="${GLASSES_NAME:-glasses-cm5}"
export STREAM_WIDTH="${STREAM_WIDTH:-640}"
export STREAM_HEIGHT="${STREAM_HEIGHT:-480}"
export STREAM_FPS="${STREAM_FPS:-15}"

mkdir -p "$SMARTGLASSES_OUTDIR" "$SMARTGLASSES_OUTDIR/snapshots" "$SMARTGLASSES_OUTDIR/recordings"

echo "Starting CM5 headless stream profile=$DEVICE_PROFILE backend=$SMARTGLASSES_CAMERA_BACKEND scene=$SCENE_CAMERA eye=$EYE_CAMERA out=$SMARTGLASSES_OUTDIR"

exec /usr/bin/python3 "$REPO_ROOT/scripts/cm5_headless_stream.py"
