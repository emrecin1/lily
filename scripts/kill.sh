#!/usr/bin/env bash
# ACIL DURDURMA — tum acik emirleri iptal et, tum pozisyonlari duzlestir, botu durdur.
# Freqtrade REST API uzerinden calisir (api_server.enabled = true olmali).
#
# Kullanim:
#   scripts/kill.sh [config/config.dry.json]
#
# Not: Bu, Freqtrade'in kendi guvenli yolu. Borsada "yetim" emir kaldigindan
# supheleniyorsan ayrica borsanin web arayuzunden / ccxt ile cancel_all_orders
# calistir (Asama 4'te scripts/reconcile.py bunu raporlar).

set -euo pipefail

CONFIG="${1:-config/config.dry.json}"

# API bilgisini config'den cek (jq gerekir).
if ! command -v jq >/dev/null 2>&1; then
  echo "jq gerekli: sudo apt install jq" >&2
  exit 1
fi

HOST=$(jq -r '.api_server.listen_ip_address // "127.0.0.1"' "$CONFIG")
PORT=$(jq -r '.api_server.listen_port // 8080' "$CONFIG")
USER=$(jq -r '.api_server.username' "$CONFIG")
PASS=$(jq -r '.api_server.password' "$CONFIG")
BASE="http://${HOST}:${PORT}/api/v1"

echo ">> Bot durduruluyor: ${BASE}"
curl -sf -u "${USER}:${PASS}" -X POST "${BASE}/stop" && echo " ok: stop"

echo ">> Tum pozisyonlar zorla kapatiliyor (forceexit all)"
curl -sf -u "${USER}:${PASS}" -X POST "${BASE}/forceexit" \
  -H "Content-Type: application/json" -d '{"tradeid": "all"}' && echo " ok: forceexit all"

echo ">> Durum:"
curl -sf -u "${USER}:${PASS}" "${BASE}/status" | jq '.[] | {pair, is_open, amount, profit_abs}' || true

echo ">> BITTI. Borsa arayuzunden de kontrol et."
