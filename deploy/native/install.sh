#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

require_command() {
  local command_name="$1"
  local install_hint="${2:-}"

  if command -v "$command_name" >/dev/null 2>&1; then
    return
  fi

  if [[ -n "$install_hint" ]]; then
    echo "$command_name is required. $install_hint" >&2
  else
    echo "$command_name is required." >&2
  fi
  exit 1
}

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

sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

run_npm() {
  if [[ "${NPM_USE_PROXY:-0}" == "1" || "${NPM_USE_PROXY:-}" == "true" ]]; then
    npm "$@"
    return
  fi

  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy npm "$@"
}

reload_nginx() {
  if systemd_available; then
    sudo systemctl reload-or-restart nginx
    return
  fi

  sudo nginx -s reload >/dev/null 2>&1 || sudo nginx
}

start_backend_without_systemd() {
  "$PROJECT_DIR/deploy/native/stop-backend.sh" >/dev/null 2>&1 || true
  "$PROJECT_DIR/deploy/native/start-backend.sh"
}

require_command nginx "Install it first, for example: sudo apt-get install nginx"
require_command uv "Install it first, for example: curl -LsSf https://astral.sh/uv/install.sh | sh"
require_command node "Install Node.js before running the native deployment installer."
require_command npm "Install npm before running the native deployment installer."

UV_BIN="$(command -v uv)"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "Created $PROJECT_DIR/.env. Edit it before starting the service." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$PROJECT_DIR/.env"
set +a

APP_PORT="$(strip_outer_quotes "${APP_PORT:-18080}")"
BACKEND_HOST="$(strip_outer_quotes "${BACKEND_HOST:-127.0.0.1}")"
BACKEND_PORT="$(strip_outer_quotes "${BACKEND_PORT:-8001}")"
validate_port APP_PORT "$APP_PORT"
validate_port BACKEND_PORT "$BACKEND_PORT"

cd "$PROJECT_DIR"
uv sync

cd "$PROJECT_DIR/frontend"
run_npm ci --no-audit --no-fund
run_npm run build

tmp_nginx="$(mktemp)"
nginx_root="$(sed_replacement "$PROJECT_DIR/frontend/dist")"
backend_url="$(sed_replacement "http://$BACKEND_HOST:$BACKEND_PORT/api/")"
sed \
  -e "s|listen 18080;|listen $APP_PORT;|" \
  -e "s|root /data/projects/llm-council/frontend/dist;|root $nginx_root;|" \
  -e "s|proxy_pass http://127.0.0.1:8001/api/;|proxy_pass $backend_url;|" \
  "$PROJECT_DIR/deploy/native/llm-council.nginx.conf" > "$tmp_nginx"

sudo install -m 0644 "$tmp_nginx" /etc/nginx/sites-available/llm-council.conf
rm -f "$tmp_nginx"
sudo ln -sfn /etc/nginx/sites-available/llm-council.conf /etc/nginx/sites-enabled/llm-council.conf
sudo nginx -t
reload_nginx

if systemd_available; then
  tmp_service="$(mktemp)"
  service_workdir="$(sed_replacement "$PROJECT_DIR")"
  service_env_file="$(sed_replacement "$PROJECT_DIR/.env")"
  service_exec="$(sed_replacement "$UV_BIN run python -m backend.main")"
  service_backend_host="$(sed_replacement "$BACKEND_HOST")"
  service_backend_port="$(sed_replacement "$BACKEND_PORT")"
  sed \
    -e "s|WorkingDirectory=/data/projects/llm-council|WorkingDirectory=$service_workdir|" \
    -e "s|EnvironmentFile=/data/projects/llm-council/.env|EnvironmentFile=$service_env_file|" \
    -e "s|Environment=BACKEND_HOST=127.0.0.1|Environment=BACKEND_HOST=$service_backend_host|" \
    -e "s|Environment=BACKEND_PORT=8001|Environment=BACKEND_PORT=$service_backend_port|" \
    -e "s|ExecStart=/usr/bin/env uv run python -m backend.main|ExecStart=$service_exec|" \
    "$PROJECT_DIR/deploy/native/llm-council-backend.service" > "$tmp_service"

  if [[ "$RUN_USER" != "root" ]]; then
    sed -i "/^Type=simple/a User=$RUN_USER" "$tmp_service"
  fi
  if [[ "${BACKEND_USE_PROXY:-1}" == "0" || "${BACKEND_USE_PROXY:-}" == "false" ]]; then
    sed -i "/^EnvironmentFile=/a Environment=HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= all_proxy=" "$tmp_service"
  fi

  sudo install -m 0644 "$tmp_service" /etc/systemd/system/llm-council-backend.service
  rm -f "$tmp_service"

  sudo systemctl daemon-reload
  sudo systemctl enable llm-council-backend.service
  sudo systemctl restart llm-council-backend.service
  echo "Backend mode: systemd service llm-council-backend.service"
else
  start_backend_without_systemd
  echo "Backend mode: background process"
  echo "Backend PID: $(cat "$PROJECT_DIR/.run/llm-council-backend.pid")"
  echo "Backend log: $PROJECT_DIR/logs/backend.log"
fi
echo "Backend bind: $BACKEND_HOST:$BACKEND_PORT"
echo "Backend proxy mode: ${BACKEND_USE_PROXY:-1} (1/inherit uses HTTP_PROXY/HTTPS_PROXY; 0 disables them for backend)"

echo "LLM Council native deployment is installed."
echo "Compute-node URL: http://localhost:$APP_PORT/"
echo "Map the management-node external port to this compute-node's port $APP_PORT."
