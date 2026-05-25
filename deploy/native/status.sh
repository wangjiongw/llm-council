#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="$PROJECT_DIR/.run/llm-council-backend.pid"
APP_PORT="$(grep -E '^APP_PORT=' "$PROJECT_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
APP_PORT="${APP_PORT:-18080}"
APP_PORT="${APP_PORT%\"}"
APP_PORT="${APP_PORT#\"}"
APP_PORT="${APP_PORT%\'}"
APP_PORT="${APP_PORT#\'}"
SERVICE_NAME="llm-council-backend.service"

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

if ss -ltn 2>/dev/null | grep -q ":$APP_PORT "; then
  echo "Nginx/frontend entry appears to be listening on APP_PORT=$APP_PORT"
else
  echo "No listener detected on APP_PORT=$APP_PORT"
fi

if systemd_available && systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
  systemctl status "$SERVICE_NAME" --no-pager || true
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    exit 0
  fi
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if [[ -n "$PID" ]] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "Backend running as PID $PID"
    echo "Log: $PROJECT_DIR/logs/backend.log"
    exit 0
  fi
fi

echo "Backend is not running"
exit 1
