#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_FILE="$PROJECT_DIR/.run/llm-council-backend.pid"
LOG_FILE="$PROJECT_DIR/logs/backend.log"

strip_outer_quotes() {
  local value="${1:-}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

validate_port() {
  local name="$1"
  local value="$2"

  if ! [[ "$value" =~ ^[0-9]+$ ]] || (( value < 1 || value > 65535 )); then
    echo "$name must be a TCP port between 1 and 65535; got '$value'." >&2
    exit 1
  fi
}

mkdir -p "$PROJECT_DIR/.run" "$PROJECT_DIR/logs"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" >/dev/null 2>&1; then
    echo "Backend already running as PID $old_pid"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "Missing $PROJECT_DIR/.env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$PROJECT_DIR/.env"
set +a

export BACKEND_HOST
export BACKEND_PORT
BACKEND_HOST="$(strip_outer_quotes "${BACKEND_HOST:-127.0.0.1}")"
BACKEND_PORT="$(strip_outer_quotes "${BACKEND_PORT:-8001}")"
validate_port BACKEND_PORT "$BACKEND_PORT"

if [[ "${BACKEND_USE_PROXY:-1}" == "0" || "${BACKEND_USE_PROXY:-}" == "false" ]]; then
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
fi

cd "$PROJECT_DIR"
if [[ -x "$PROJECT_DIR/.venv/bin/python3" ]]; then
  backend_cmd=("$PROJECT_DIR/.venv/bin/python3" -m backend.main)
elif command -v uv >/dev/null 2>&1; then
  backend_cmd=(uv run python -m backend.main)
else
  echo "No .venv/bin/python3 or uv found for backend startup." >&2
  exit 1
fi

setsid "${backend_cmd[@]}" >> "$LOG_FILE" 2>&1 < /dev/null &
pid="$!"
echo "$pid" > "$PID_FILE"
sleep 1

if ! kill -0 "$pid" >/dev/null 2>&1; then
  rm -f "$PID_FILE"
  echo "Backend failed to start. See $LOG_FILE" >&2
  exit 1
fi

echo "Backend running as PID $pid"
echo "Backend bind: $BACKEND_HOST:$BACKEND_PORT"
echo "Log: $LOG_FILE"
