#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$REPO_ROOT/config/cm5.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing CM5 config file: $CONFIG_FILE"
  exit 1
fi

set -a
source "$CONFIG_FILE"
set +a

SMARTGLASSES_OUTDIR="${SMARTGLASSES_OUTDIR:-$REPO_ROOT/out}"
if [[ "$SMARTGLASSES_OUTDIR" != /* ]]; then
  SMARTGLASSES_OUTDIR="$REPO_ROOT/$SMARTGLASSES_OUTDIR"
fi
export SMARTGLASSES_OUTDIR
mkdir -p "$SMARTGLASSES_OUTDIR"

echo "Using profile: ${DEVICE_PROFILE:-cm5}"
echo "Camera backend: ${SMARTGLASSES_CAMERA_BACKEND:-auto}"
echo "Scene camera: ${SCENE_CAMERA:-0}"
echo "Eye camera: ${EYE_CAMERA:-1}"
echo "Output: $SMARTGLASSES_OUTDIR"

python3 "$REPO_ROOT/dual_cam_gui_safe.py"
