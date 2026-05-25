#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"$PROJECT_DIR/deploy/native/stop-backend.sh"

if [[ -L /etc/nginx/sites-enabled/llm-council.conf || -f /etc/nginx/sites-enabled/llm-council.conf ]]; then
  sudo rm -f /etc/nginx/sites-enabled/llm-council.conf
  sudo nginx -t
  sudo nginx -s reload >/dev/null 2>&1 || true
  echo "Disabled Nginx site /etc/nginx/sites-enabled/llm-council.conf"
else
  echo "Nginx site is not enabled."
fi

