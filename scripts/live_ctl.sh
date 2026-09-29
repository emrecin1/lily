#!/usr/bin/env bash
# Canli (mainnet) ortamin Freqtrade + webui sureclerini baslat/durdur/yeniden
# baslat. Bu script'e OZEL: dev/testnet icin bir "profil" secenegi YOK, bu
# dizinde her zaman config/config.live.json calisir (kasitli dar kapsam,
# bkz. plan). webui/deploy.py bunu guncelleme sonrasi otomatik cagirir;
# elle de calistirilabilir.
#
# Kullanim: scripts/live_ctl.sh {start|stop|restart}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

FT_LOG="user_data/logs/freqtrade-live.log"
WEBUI_LOG="user_data/logs/webui-live.log"
WEBUI_PORT="${WEBUI_PORT:-8084}"

FT_CMD=(.venv-rt/bin/freqtrade trade
  -c config/config.live.json
  -c config/config.freqai.json
  -c config/config.freqai.live.json
  -c config/config.telegram.local.json
  --freqaimodel XGBoostClassifier
  --strategy AiCryptoFreqAIStrategy
  --logfile "$FT_LOG")

WEBUI_CMD=(.venv/bin/python3 -m uvicorn webui.app:app --host 127.0.0.1 --port "$WEBUI_PORT")

# Bir sürecin GERÇEKTEN bu dizine ait olduğunu, cwd'sini kontrol ederek
# doğrular — aynı makinede birden fazla ai-crypto-bot kopyası (dev/testnet +
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
  ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.live.json")
  webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")

  if [ -n "$ft_pids" ]; then
    echo ">> Freqtrade (canli) durduruluyor: $ft_pids"
    kill $ft_pids
    sleep 2
    ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.live.json")
    [ -n "$ft_pids" ] && kill -9 $ft_pids || true
  else
    echo ">> Freqtrade (canli) zaten calismiyor."
  fi

  if [ -n "$webui_pids" ]; then
    echo ">> webui (canli) durduruluyor: $webui_pids"
    kill $webui_pids
    sleep 1
    webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")
    [ -n "$webui_pids" ] && kill -9 $webui_pids || true
  else
    echo ">> webui (canli) zaten calismiyor."
  fi
}

_start() {
  echo ">> Freqtrade (canli) baslatiliyor..."
  setsid nohup "${FT_CMD[@]}" >>"$FT_LOG" 2>&1 &
  disown

  echo ">> webui (canli) baslatiliyor (port $WEBUI_PORT)..."
  setsid nohup "${WEBUI_CMD[@]}" >>"$WEBUI_LOG" 2>&1 &
  disown

  echo ">> Baslatildi. Durum icin: scripts/live_ctl.sh status"
}

_status() {
  local ft_pids webui_pids
  ft_pids=$(_pids_in_this_dir "freqtrade trade -c config/config.live.json")
  webui_pids=$(_pids_in_this_dir "uvicorn webui.app:app")
  echo "Freqtrade (canli): ${ft_pids:-calismiyor}"
  echo "webui (canli):     ${webui_pids:-calismiyor}"
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
