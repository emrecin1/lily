"""webui/ ayarlari — env degiskenlerinden okunur.

Freqtrade kimlik bilgileri (Basic Auth + ws_token) BURADAN degil, dogrudan
Freqtrade'in kendi config dosyasindan (FREQTRADE_CONFIG_PATH) okunur — tek
dogruluk kaynagi. Panel sadece kendi DASHBOARD_PASSWORD'unu env'den okur.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class FreqtradeCreds:
    base_url: str
    username: str
    password: str
    ws_token: str


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(_env("WEBUI_PORT", "8082")))
    host: str = field(default_factory=lambda: _env("WEBUI_HOST", "127.0.0.1"))

    dashboard_password: str = field(
        default_factory=lambda: _env("DASHBOARD_PASSWORD", "")
    )
    session_secret: str = field(
        default_factory=lambda: _env("DASHBOARD_SESSION_SECRET", "")
    )

    freqtrade_config_path: Path = field(
        default_factory=lambda: Path(
            _env("FREQTRADE_CONFIG_PATH", str(REPO_ROOT / "config" / "config.dry.json"))
        )
    )

    # webui/deploy.py (zip ile kod guncelleme) SADECE ayri canli dizininde
    # anlamli -- oradaki .env "LIVE_DEPLOY_ENABLED=true" ile acikca ACAR.
    # Varsayilan false: dev/testnet panelinde bu buton hic gorunmez/calismaz
    # -- yanlislikla config/config.live.json'a karsi bir freqtrade sureci
    # baslatilmasini (bkz. scripts/live_ctl.sh) ONLER.
    live_deploy_enabled: bool = field(
        default_factory=lambda: _env("LIVE_DEPLOY_ENABLED", "false").lower() == "true"
    )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.dashboard_password:
        raise RuntimeError(
            "DASHBOARD_PASSWORD ayarlanmamis. .env dosyasina ekle: "
            "DASHBOARD_PASSWORD=<rastgele-guclu-sifre>"
        )
    if not s.session_secret:
        raise RuntimeError(
            "DASHBOARD_SESSION_SECRET ayarlanmamis. .env dosyasina ekle: "
            "DASHBOARD_SESSION_SECRET=<rastgele-uzun-string>"
        )
    return s


@lru_cache
def get_freqtrade_creds() -> FreqtradeCreds:
    """Freqtrade config dosyasindan api_server bilgilerini oku."""
    settings = get_settings()
    path = settings.freqtrade_config_path
    if not path.exists():
        raise RuntimeError(f"Freqtrade config bulunamadi: {path}")
    with open(path) as f:
        cfg = json.load(f)
    api = cfg.get("api_server", {})
    if not api.get("enabled"):
        raise RuntimeError(f"{path}: api_server.enabled=false — panel calisamaz.")

    # Container icinde calisirken FREQTRADE_API_BASE ile override edilebilir
    # (bkz. docker-compose Faz 5 — sibling container'a servis-adiyla erisim).
    override = os.getenv("FREQTRADE_API_BASE")
    if override:
        base_url = override.rstrip("/")
    else:
        host = api.get("listen_ip_address", "127.0.0.1")
        port = api.get("listen_port", 8080)
        base_url = f"http://{host}:{port}/api/v1"

    return FreqtradeCreds(
        base_url=base_url,
        username=api.get("username", ""),
        password=api.get("password", ""),
        ws_token=api.get("ws_token", ""),
    )


def get_max_daily_loss_pct() -> float:
    """Gunluk-kayip pili icin esik. AiCryptoFreqAIStrategy.max_daily_loss_pct
    ile AYNI kaynaktan (config.dry.json > aicrypto.max_daily_loss_pct) okunur
    — /settings sayfasi bu degeri degistirir, strateji de aynisini okur, elle
    senkron tutma ihtiyaci kalmaz (bkz. webui/settings_store.py). Her cagrida
    dosyadan tazeler (kucuk dosya, /overview her yenilemede zaten okuyor)."""
    path = get_settings().freqtrade_config_path
    try:
        with open(path) as f:
            cfg = json.load(f)
        return float(cfg.get("aicrypto", {}).get("max_daily_loss_pct", 0.02))
    except (OSError, json.JSONDecodeError):
        return 0.02


def get_freqai_info() -> dict:
    """FreqAI identifier + son egitim zamani. Freqtrade REST API'sinin bunu
    veren bir endpoint'i yok; ayni host/volume'de oldugumuz icin dogrudan
    config/config.freqai.json + user_data/models/<identifier>/ dizin
    mtime'larindan okuyoruz (bkz. docs/freqai-notes.md)."""
    freqai_cfg_path = Path(
        os.getenv("FREQAI_CONFIG_PATH", str(REPO_ROOT / "config" / "config.freqai.json"))
    )
    identifier = None
    if freqai_cfg_path.exists():
        try:
            with open(freqai_cfg_path) as f:
                identifier = json.load(f).get("freqai", {}).get("identifier")
        except (json.JSONDecodeError, OSError):
            pass

    last_trained = None
    model_count = 0
    if identifier:
        model_dir = REPO_ROOT / "user_data" / "models" / identifier
        if model_dir.is_dir():
            sub_dirs = [d for d in model_dir.iterdir() if d.is_dir()]
            model_count = len(sub_dirs)
            if sub_dirs:
                newest = max(sub_dirs, key=lambda d: d.stat().st_mtime)
                last_trained = newest.stat().st_mtime

    return {"identifier": identifier, "last_trained": last_trained, "model_count": model_count}
