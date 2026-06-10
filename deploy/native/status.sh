#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="$PROJECT_DIR/.run/llm-council-backend.pid"
SERVICE_NAME="llm-council-backend.service"

strip_outer_quotes() {
  local value="${1:-}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

read_env_value() {
  local name="$1"
  local default_value="$2"
  local value
  value="$(grep -E "^${name}=" "$PROJECT_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  strip_outer_quotes "${value:-$default_value}"
}

APP_PORT="$(read_env_value APP_PORT 18080)"
BACKEND_HOST="$(read_env_value BACKEND_HOST 127.0.0.1)"
BACKEND_PORT="$(read_env_value BACKEND_PORT 8001)"

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
    if command -v curl >/dev/null 2>&1; then
      if version_json="$(curl -fsS --max-time 2 "http://$BACKEND_HOST:$BACKEND_PORT/api/version" 2>/dev/null)"; then
        echo "Backend API responded on $BACKEND_HOST:$BACKEND_PORT"
        if command -v python3 >/dev/null 2>&1; then
          VERSION_JSON="$version_json" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ.get("VERSION_JSON", "{}"))
for key in ("commit", "pid", "started_at", "backend_host", "backend_port", "data_dir", "python"):
    print(f"{key}: {payload.get(key, '-')}")
PY
        else
          echo "$version_json"
        fi
        exit 0
      fi
      if curl -fsS --max-time 2 "http://$BACKEND_HOST:$BACKEND_PORT/api/conversations" >/dev/null 2>&1; then
        echo "Backend API responded, but /api/version did not. This may be an old backend process."
        exit 1
      fi
      echo "Backend PID exists, but API did not respond on $BACKEND_HOST:$BACKEND_PORT"
      exit 1
    fi
    exit 0
  fi
fi

echo "Backend is not running"
exit 1
