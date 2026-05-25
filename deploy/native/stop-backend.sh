#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="$PROJECT_DIR/.run/llm-council-backend.pid"
SERVICE_NAME="llm-council-backend.service"

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

if systemd_available && systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
  sudo systemctl disable --now "$SERVICE_NAME"
  echo "Stopped and disabled systemd service $SERVICE_NAME"
  exit 0
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "No backend PID file found at $PID_FILE"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ -n "$PID" ]] && kill -0 "$PID" >/dev/null 2>&1; then
  kill "$PID"
  echo "Stopped backend process $PID"
else
  echo "Backend process $PID is not running"
fi

rm -f "$PID_FILE"

echo "Only the backend was stopped. Nginx may still listen on APP_PORT and serve the frontend."
echo "Use deploy/native/stop.sh to stop the backend and disable the Nginx site."
