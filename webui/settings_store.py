"""/settings sayfasi — trading kurallarini OKUR/YAZAR.

Freqtrade calisirken config dosyalarini hot-reload ETMEZ; degisikligin
etkili olmasi icin ya surec yeniden baslamali ya da Freqtrade'in resmi
`POST /reload_config` ucu cagrilmali (ayni PID icinde config + strateji
yeniden yuklenir, acik islemlere dokunmaz — bkz. freqtrade_client.py).
Bu modul SADECE dosyalari okur/yazar; reload'u tetiklemek routes/settings.py'nin
isi (acik pozisyon kontrolu orada yapiliyor).

Iki dosyaya yazariz:
  1. config/config.dry.json      -> stake_amount, tradable_balance_ratio,
                                     max_open_trades, aicrypto.max_daily_loss_pct
  2. user_data/strategies/AiCryptoFreqAIStrategy.json
                                  -> freqtrade'in KENDI "hyperopt parametre
                                     dosyasi" formati (bkz. HyperStrategyMixin.
                                     load_params_from_file). Bu, hiperparametre
                                     override etmenin freqtrade-native, resmi
                                     yolu — panel bunu elle uydurmuyor.

Tum yazmalar atomik (temp dosya + os.replace).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webui.config import REPO_ROOT, get_settings

STRATEGY_NAME = "AiCryptoFreqAIStrategy"
STRATEGY_PARAMS_PATH = REPO_ROOT / "user_data" / "strategies" / f"{STRATEGY_NAME}.json"

# Telegram token/chat_id BURADA tutulur, config/config.dry.json'da DEGIL —
# o dosya git'te takip edilir (bkz. oradaki "telegram" bloğu yorumu), token'i
# oraya yazmak secret'i repoya sizdirir. Bu dosya *.local.json kalıbıyla
# .gitignore'da zaten kapsanıyor (bkz. config/config.testnet.json ile aynı
# mantık). Freqtrade'e ayrı bir "-c" katmanı olarak verilir (deep-merge ile
# sadece enabled/token/chat_id'yi ezer, config.dry.json'daki
# notification_settings aynen kalır) — bu katmanı EKLEMEK icin freqtrade
# sürecinin -c argümanıyla yeniden başlatılması gerekir (tek seferlik); o
# katman bir kez eklendikten sonra buradaki değişiklikler reload_config ile
# canlı uygulanır (webui/reload.py).
TELEGRAM_CONFIG_PATH = REPO_ROOT / "config" / "config.telegram.local.json"

# user_data/strategies/AiCryptoFreqAIStrategy.py'deki sinif sabitleriyle
# AYNI TUTULMALI — parametre dosyasi henuz yokken (ilk kurulum) gosterilecek
# varsayilanlar bunlar.
DEFAULTS: dict[str, Any] = {
    "buy_proba": 0.65,
    "time_stop_candles": 12,
    "time_stop_loss": -0.05,
    "roi": 0.15,
    "stoploss": -0.20,
}
# AiCryptoFreqAIStrategy.max_daily_loss_pct sinif sabitiyle AYNI (bkz. o dosya).
DEFAULT_MAX_DAILY_LOSS_PCT = 0.02
# AiCryptoFreqAIStrategy.stake_percent varsayilaniyla AYNI (bkz. o dosya).
DEFAULT_STAKE_PERCENT = 0.10

# Strateji sinifindaki RealParameter/DecimalParameter sinirlariyla AYNI (bkz.
# AiCryptoFreqAIStrategy.py) — hyperopt uzayinin disina cikan bir deger
# freqtrade tarafindan REDDEDILMEZ (BaseParameter.value setter'i sinirsiz),
# bu yuzden makul kalmasini panel garanti eder.
BOUNDS: dict[str, tuple[float, float]] = {
    "buy_proba": (0.50, 0.75),
    "time_stop_candles": (6, 24),
    "time_stop_loss": (-0.12, -0.02),
    "roi": (0.01, 1.00),
    "stoploss": (-0.90, -0.01),
    "tradable_balance_ratio": (0.10, 1.00),
    "max_open_trades": (1, 10),
    "stake_amount": (10, 1_000_000),
    "max_daily_loss_pct": (0.005, 0.50),
    "stake_percent": (0.005, 1.00),
}


def _clamp(key: str, value: float) -> float:
    lo, hi = BOUNDS[key]
    return max(lo, min(hi, value))


@dataclass
class CurrentSettings:
    # Giris
    buy_proba: float
    # Cikis
    time_stop_candles: int
    time_stop_loss: float
    roi: float
    stoploss: float
    # Pozisyon buyuklugu
    stake_mode: str  # "unlimited" | "fixed" | "percent"
    stake_amount: float
    stake_percent: float
    tradable_balance_ratio: float
    max_open_trades: int
    # Genel
    max_daily_loss_pct: float
    has_param_file: bool


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_current() -> CurrentSettings:
    trading_cfg = _read_json(get_settings().freqtrade_config_path)
    params = _read_json(STRATEGY_PARAMS_PATH)
    has_param_file = bool(params)
    p = params.get("params", {})

    buy = p.get("buy", {})
    sell = p.get("sell", {})
    roi = p.get("roi", {})
    stoploss = p.get("stoploss", {})

    stake_amount_raw = trading_cfg.get("stake_amount", 1000)
    aicrypto_cfg = trading_cfg.get("aicrypto", {})
    stake_mode = aicrypto_cfg.get("stake_mode")
    if stake_mode not in ("unlimited", "fixed", "percent"):
        # Eski dosyalarda aicrypto.stake_mode henuz yok — stake_amount'tan turet.
        stake_mode = "unlimited" if stake_amount_raw == "unlimited" else "fixed"

    return CurrentSettings(
        buy_proba=float(buy.get("buy_proba", DEFAULTS["buy_proba"])),
        time_stop_candles=int(sell.get("time_stop_candles", DEFAULTS["time_stop_candles"])),
        time_stop_loss=float(sell.get("time_stop_loss", DEFAULTS["time_stop_loss"])),
        roi=float(roi.get("0", DEFAULTS["roi"])),
        stoploss=float(stoploss.get("stoploss", DEFAULTS["stoploss"])),
        stake_mode=stake_mode,
        stake_amount=float(stake_amount_raw) if stake_mode == "fixed" else 1000.0,
        stake_percent=float(aicrypto_cfg.get("stake_percent", DEFAULT_STAKE_PERCENT)),
        tradable_balance_ratio=float(trading_cfg.get("tradable_balance_ratio", 0.99)),
        max_open_trades=int(trading_cfg.get("max_open_trades", 3)),
        max_daily_loss_pct=float(
            trading_cfg.get("aicrypto", {}).get(
                "max_daily_loss_pct", DEFAULT_MAX_DAILY_LOSS_PCT
            )
        ),
        has_param_file=has_param_file,
    )


def apply(new: dict[str, Any]) -> None:
    """`new` en azindan CurrentSettings alanlarinin bir alt kumesini icerir
    (route zaten hepsini gonderiyor). Degerler CAGIRAN tarafindan zaten
    clamp edilmis olmali; burda yine de guvenlik icin tekrar clamp edilir."""

    # ---- 1) config/config.dry.json --------------------------------------
    cfg_path = get_settings().freqtrade_config_path
    cfg = _read_json(cfg_path)

    stake_mode = new["stake_mode"]
    if stake_mode == "fixed":
        cfg["stake_amount"] = _clamp("stake_amount", float(new["stake_amount"]))
    else:
        # "unlimited" VE "percent" ikisi de freqtrade'e "unlimited" olarak
        # gecer; "percent" modunda gercek tutar AiCryptoFreqAIStrategy.
        # custom_stake_amount() ile ezilir (bkz. o dosya + asagidaki
        # aicrypto.stake_mode/stake_percent).
        cfg["stake_amount"] = "unlimited"

    cfg["tradable_balance_ratio"] = round(
        _clamp("tradable_balance_ratio", float(new["tradable_balance_ratio"])), 3
    )
    cfg["max_open_trades"] = int(_clamp("max_open_trades", int(new["max_open_trades"])))

    cfg.setdefault("aicrypto", {})
    cfg["aicrypto"]["max_daily_loss_pct"] = round(
        _clamp("max_daily_loss_pct", float(new["max_daily_loss_pct"])), 4
    )
    cfg["aicrypto"]["stake_mode"] = stake_mode
    cfg["aicrypto"]["stake_percent"] = round(
        _clamp("stake_percent", float(new.get("stake_percent", DEFAULT_STAKE_PERCENT))), 4
    )

    _write_json_atomic(cfg_path, cfg)

    # ---- 2) user_data/strategies/AiCryptoFreqAIStrategy.json -------------
    params_doc = _read_json(STRATEGY_PARAMS_PATH)
    params_doc["strategy_name"] = STRATEGY_NAME
    params_doc.setdefault("ft_stratparam_v", 1)
    params = params_doc.setdefault("params", {})

    params.setdefault("buy", {})["buy_proba"] = round(
        _clamp("buy_proba", float(new["buy_proba"])), 3
    )
    sell = params.setdefault("sell", {})
    sell["time_stop_candles"] = int(_clamp("time_stop_candles", int(new["time_stop_candles"])))
    sell["time_stop_loss"] = round(_clamp("time_stop_loss", float(new["time_stop_loss"])), 3)

    params["roi"] = {"0": round(_clamp("roi", float(new["roi"])), 3)}
    params["stoploss"] = {"stoploss": round(_clamp("stoploss", float(new["stoploss"])), 3)}

    _write_json_atomic(STRATEGY_PARAMS_PATH, params_doc)


@dataclass
class TelegramSettings:
    enabled: bool
    chat_id: str
    has_token: bool
    token_tail: str  # token'in son 4 karakteri — dogrulama icin, tam deger ASLA UI'ye donmez


def read_telegram() -> TelegramSettings:
    tg = _read_json(TELEGRAM_CONFIG_PATH).get("telegram", {})
    token = tg.get("token", "") or ""
    return TelegramSettings(
        enabled=bool(tg.get("enabled", False)),
        chat_id=str(tg.get("chat_id", "") or ""),
        has_token=bool(token),
        token_tail=token[-4:] if token else "",
    )


def apply_telegram(enabled: bool, token: str, chat_id: str) -> None:
    """Bos birakilan token alani MEVCUT token'i korur (her kaydetmede yeniden
    girmeye zorlamamak icin) — sadece enabled/chat_id degistirmek istenen
    ortak durumu destekler."""
    cfg = _read_json(TELEGRAM_CONFIG_PATH)
    tg = cfg.setdefault("telegram", {})
    tg["enabled"] = bool(enabled)
    token = token.strip()
    if token:
        tg["token"] = token
    tg["chat_id"] = chat_id.strip()
    _write_json_atomic(TELEGRAM_CONFIG_PATH, cfg)


def read_dry_run_wallet() -> float:
    cfg = _read_json(get_settings().freqtrade_config_path)
    return float(cfg.get("dry_run_wallet", 10_000))


def apply_dry_run_wallet(amount: float) -> None:
    """Demo (dry-run) baslangic bakiyesi. SADECE yeni baslangic degerini
    degistirir — gecmis simule islemlerin karini/zararini SIFIRLAMAZ (gercek
    bakiye = bu deger + o ana kadarki gerceklesen PnL). Tam sifirlama icin
    islem gecmisinin de temizlenmesi gerekir; bu, bot calisirken guvenle
    yapilamayacagi icin (ayni SQLite dosyasina aktif baglanti) panelden
    SUNULMUYOR — gerekirse bota SSH ile, bot durdurulup elle yapilmali."""
    cfg_path = get_settings().freqtrade_config_path
    cfg = _read_json(cfg_path)
    cfg["dry_run_wallet"] = _clamp_dry_run_wallet(amount)
    _write_json_atomic(cfg_path, cfg)


def _clamp_dry_run_wallet(amount: float) -> float:
    return round(max(10.0, min(100_000_000.0, float(amount))), 2)
