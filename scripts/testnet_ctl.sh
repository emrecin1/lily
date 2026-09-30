#!/usr/bin/env bash
# Testnet ortaminin Freqtrade + webui sureclerini baslat/durdur/yeniden
# baslat. Bu dizinde her zaman config/config.testnet.json calisir (canli
# icin ayni deseni kullanan scripts/live_ctl.sh'a bakin, ayri dizinde).
#
# Kullanim: scripts/testnet_ctl.sh {start|stop|restart|status}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

FT_LOG="user_data/logs/freqtrade-testnet.log"
WEBUI_LOG="logs/webui.log"
WEBUI_PORT="${WEBUI_PORT:-8082}"

FT_CMD=(.venv-rt/bin/freqtrade trade
  -c config/config.testnet.json
  -c config/config.freqai.json
  -c config/config.telegram.local.json
  --freqaimodel XGBoostClassifier
  --strategy AiCryptoFreqAIStrategy
  --logfile "$FT_LOG")

WEBUI_CMD=(.venv/bin/python3 -m uvicorn webui.app:app --host 127.0.0.1 --port "$WEBUI_PORT")

# Bir sürecin GERÇEKTEN bu dizine ait olduğunu, cwd'sini kontrol ederek
# doğrular — aynı makinede birden fazla lily kopyası (dev/testnet +
# canlı) çalışırken pgrep'in yanlış dizindeki bir süreci yakalamasını önler.
_pids_in_this_dir() {
  local pattern="$1"
  # "|| true": pgrep eslesme bulamayinca 1 donuyor -- pipefail altinda bu,
  # butun pipeline'i (ve set -e ile TUM script'i) hatali sonlandirirdi.
  pgrep -f "$pattern" 2>/dev/null | while read -r pid; do
    if [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$SCRIPT_DIR" ]; then
      echo "$pid"
    fi
  done || true
}

_stop() {
  local ft_pids webui_pids
  ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.testnet.json")
  webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")

  if [ -n "$ft_pids" ]; then
    echo ">> Freqtrade (testnet) durduruluyor: $ft_pids"
    kill $ft_pids
    sleep 2
    ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.testnet.json")
    [ -n "$ft_pids" ] && kill -9 $ft_pids || true
  else
    echo ">> Freqtrade (testnet) zaten calismiyor."
  fi

  if [ -n "$webui_pids" ]; then
    echo ">> webui durduruluyor: $webui_pids"
    kill $webui_pids
    sleep 1
    webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")
    [ -n "$webui_pids" ] && kill -9 $webui_pids || true
  else
    echo ">> webui zaten calismiyor."
  fi
}

_start() {
  echo ">> Freqtrade (testnet) baslatiliyor..."
  setsid nohup "${FT_CMD[@]}" >>"$FT_LOG" 2>&1 &
  disown

  echo ">> webui baslatiliyor (port $WEBUI_PORT)..."
  setsid nohup "${WEBUI_CMD[@]}" >>"$WEBUI_LOG" 2>&1 &
  disown

  echo ">> Baslatildi. Durum icin: scripts/testnet_ctl.sh status"
}

_status() {
  local ft_pids webui_pids
  ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.testnet.json")
  webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")
  echo "Freqtrade (testnet): ${ft_pids:-calismiyor}"
  echo "webui:                ${webui_pids:-calismiyor}"
}

case "${1:-}" in
  start)   _start ;;
  stop)    _stop ;;
  restart) _stop; sleep 1; _start ;;
  status)  _status ;;
  *)
    echo "Kullanim: $0 {start|stop|restart|status}" >&2
    exit 1
    ;;
esac
