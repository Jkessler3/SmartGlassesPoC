#!/usr/bin/env bash
set -u

PORT="${PI_PORT:-${STREAM_PORT:-8000}}"
PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo "== Pi IP addresses =="
hostname -I || true

echo
echo "== Listening TCP sockets =="
sudo ss -ltnp || true

echo
echo "== Local status =="
curl "http://127.0.0.1:${PORT}/status" || true

if [[ -n "${PI_IP}" ]]; then
  echo
  echo "== LAN status =="
  curl "http://${PI_IP}:${PORT}/status" || true
fi
