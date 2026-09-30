#!/usr/bin/env bash
# Lily V2 (Freqtrade + FreqAI runtime) otomatik kurulum betiği.
# Taze bir sunucuda repo klonlandıktan sonra tek komutla:
#   ./install.sh
# çalıştırır; sanal ortamları, dizinleri, .env'i ve config/*.json dosyalarını
# örneklerden oluşturur, gerekli gizli anahtarları (session secret, jwt,
# ws_token, panel/API şifresi) otomatik üretir. Borsa API key/secret'ı
# ASLA otomatik üretilmez — interaktif oturumda sorulur, aksi halde
# placeholder olarak bırakılır (sonra elle doldurulmalı).
#
# Detaylı aşama planı: docs/MIGRATION.md. Mimari: docs/ARCHITECTURE.md.

set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bold()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
info()  { printf '  -> %s\n' "$1"; }
warn()  { printf '  !! %s\n' "$1" >&2; }

bold "Lily kurulum betiği (V2 — Freqtrade + webui)"

# --------------------------------------------------------------------------
# 0. Ön kontroller
# --------------------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || { warn "python3 bulunamadı, kurulumdan sonra tekrar dene."; exit 1; }
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$PYVER" != "3.12" ]; then
  warn "python3 sürümü $PYVER — proje 3.12 için test edildi (bkz. .python-version)."
fi

# --------------------------------------------------------------------------
# 1. Sanal ortamlar
# --------------------------------------------------------------------------
bold "[1/5] Sanal ortamlar"

if [ ! -d .venv-rt ]; then
  python3 -m venv .venv-rt
  info ".venv-rt oluşturuldu (Freqtrade runtime, ana .venv'den ayrı)."
else
  info ".venv-rt zaten var, dokunulmadı."
fi
.venv-rt/bin/pip install -q --upgrade pip
.venv-rt/bin/pip install -q freqtrade ta python-dotenv
info "Freqtrade kuruldu: $(.venv-rt/bin/freqtrade --version 2>/dev/null | head -1 || echo '?')"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  info ".venv oluşturuldu (webui)."
else
  info ".venv zaten var, dokunulmadı."
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[webui]"
info "webui bağımlılıkları kuruldu (.venv)."

# --------------------------------------------------------------------------
# 2. Çalışma dizinleri
# --------------------------------------------------------------------------
bold "[2/5] Çalışma dizinleri"
mkdir -p user_data/logs logs data/raw data/processed data/database models
info "user_data/logs, logs/, data/{raw,processed,database}, models/ hazır."

# --------------------------------------------------------------------------
# 3. .env
# --------------------------------------------------------------------------
bold "[3/5] .env"
if [ ! -f .env ]; then
  cp .env.example .env
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  DASH_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')"
  sed -i "s/^DASHBOARD_SESSION_SECRET=.*/DASHBOARD_SESSION_SECRET=${SESSION_SECRET}/" .env
  sed -i "s/^DASHBOARD_PASSWORD=.*/DASHBOARD_PASSWORD=${DASH_PASS}/" .env
  info ".env oluşturuldu (DASHBOARD_SESSION_SECRET otomatik üretildi)."
  info "webui panel şifren: ${DASH_PASS}  (değiştirmek istersen .env'den düzenle)"
else
  info ".env zaten var, dokunulmadı."
fi

# --------------------------------------------------------------------------
# 4. Freqtrade config dosyaları (testnet / live) + Telegram
# --------------------------------------------------------------------------
bold "[4/5] Freqtrade config dosyaları"

gen_secrets_json() {
  # $1 = dosya yolu. api_server.jwt_secret_key / ws_token'ı her zaman,
  # password'u yalnızca hâlâ "DEGISTIR" ise üretir.
  python3 - "$1" <<'PYEOF'
import json, secrets, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
api = cfg.setdefault("api_server", {})
api["jwt_secret_key"] = secrets.token_hex(32)
api["ws_token"] = secrets.token_hex(16)
if api.get("password") == "DEGISTIR":
    api["password"] = secrets.token_urlsafe(12)
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=4, ensure_ascii=False)
    f.write("\n")
print(api["password"])
PYEOF
}

prompt_exchange_keys() {
  # $1 = dosya yolu, $2 = etiket (Testnet / Mainnet)
  local real="$1" label="$2" key secret
  [ -t 0 ] || return 0
  read -r -p "  ${label} borsa API key (boş bırakıp geçebilirsin): " key || true
  [ -n "${key:-}" ] || return 0
  read -r -s -p "  ${label} borsa API secret: " secret; echo
  [ -n "${secret:-}" ] || { warn "Secret girilmedi, key/secret yazılmadı."; return 0; }
  python3 - "$real" "$key" "$secret" <<'PYEOF'
import json, sys
path, key, secret = sys.argv[1:4]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
cfg["exchange"]["key"] = key
cfg["exchange"]["secret"] = secret
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=4, ensure_ascii=False)
    f.write("\n")
PYEOF
  info "${label} exchange.key/secret ${real} içine yazıldı."
}

setup_config() {
  local example="$1" real="$2" label="$3"
  if [ -f "$real" ]; then
    info "$real zaten var, dokunulmadı."
    return
  fi
  cp "$example" "$real"
  local pass
  pass="$(gen_secrets_json "$real" | tail -1)"
  info "$real oluşturuldu (jwt_secret_key/ws_token otomatik). FreqUI/API şifresi: ${pass}"
  prompt_exchange_keys "$real" "$label"
  if grep -q '"key": "TESTNET_API_KEY"\|"key": "MAINNET_API_KEY"' "$real"; then
    warn "$real içindeki exchange.key/secret HALA PLACEHOLDER — elle doldurmadan çalıştırma."
  fi
}

setup_config config/config.testnet.example.json config/config.testnet.json "Testnet"
setup_config config/config.live.example.json   config/config.live.json   "Mainnet (CANLI PARA)"

if [ ! -f config/config.telegram.local.json ]; then
  cat > config/config.telegram.local.json <<'JSON'
{
    "telegram": {
        "enabled": false,
        "token": "",
        "chat_id": ""
    }
}
JSON
  info "config/config.telegram.local.json oluşturuldu (devre dışı)."
  info "Kullanmak için: token/chat_id doldur, enabled:true yap."
else
  info "config/config.telegram.local.json zaten var, dokunulmadı."
fi

# --------------------------------------------------------------------------
# 5. Özet
# --------------------------------------------------------------------------
bold "[5/5] Özet"
cat <<'EOF'

Kurulum tamam. Kalan manuel adımlar (varsa):
  - config/config.testnet.json / config.live.json -> exchange.key / exchange.secret
    (yukarıda girmediysen hâlâ placeholder)
  - config/config.telegram.local.json -> token / chat_id (opsiyonel, Telegram alarmları için)
  - .env -> BINANCE_*_API_KEY/SECRET, TELEGRAM_* (scripts/reconcile.py gibi yardımcılar için)

Çalıştırmak için:
  scripts/testnet_ctl.sh start    # testnet: Freqtrade :8081 + webui :8082
  scripts/testnet_ctl.sh status
  scripts/live_ctl.sh   start     # mainnet — SADECE docs/MIGRATION.md Aşama 5-6 tamamlandıktan sonra

Acil durdurma: scripts/kill.sh
Detay: docs/MIGRATION.md, docs/ARCHITECTURE.md, README.md
EOF
