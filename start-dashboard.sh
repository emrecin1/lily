#!/usr/bin/env bash
# Start the FastAPI dashboard backend in the background (detached).
# Usage: ./start-dashboard.sh [port]   (default 8000)
set -euo pipefail

cd "$(dirname "$0")"
PORT="${1:-8000}"

# Start uvicorn fully detached so it survives the terminal/shell session.
setsid nohup .venv/bin/python -m uvicorn src.dashboard.app:app \
  --host 127.0.0.1 --port "${PORT}" \
  </dev/null >"logs/dashboard.log" 2>&1 &

echo "Dashboard backend başlatıldı: http://127.0.0.1:${PORT}"
sleep 3
if curl -s -o /dev/null "http://127.0.0.1:${PORT}/api/health"; then
  echo "Sağlık kontrolü başarılı (HTTP 200)."
else
  echo "Uyarı: sağlık kontrolü başarısız — logs/dashboard.log dosyasını kontrol et."
fi
