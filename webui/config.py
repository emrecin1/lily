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

    # AiCryptoFreqAIStrategy.max_daily_loss_pct ile AYNI TUTULMALI (bkz. o dosya).
    # Freqtrade'in bunu veren bir endpoint'i yok; panel kendi hesaplar.
    daily_loss_pct: float = field(
        default_factory=lambda: float(_env("WEBUI_DAILY_LOSS_PCT", "0.02"))
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
