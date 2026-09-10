"""Persistent, dashboard-editable settings for the rules signal system.

Stored as JSON in `data/processed/rules_settings.json`. Lets the user pick
which coins to track and which rule parameters to use, without editing .env.

The file is the source of truth for the running dashboard; values written here
override the defaults from cfg.rules on the relevant coins/params.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.config import Config
from src.logging_config import get_logger

logger = get_logger("rules.settings")

DEFAULT_ALL_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT")


@dataclass
class SignalSettings:
    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_ALL_SYMBOLS))
    timeframe: str = "4h"
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_buy_max: float = 45.0
    rsi_sell_max: float = 70.0
    accuracy_horizon: int = 4       # candles ahead to judge a signal
    accuracy_min_move_pct: float = 0.01  # required move (+1%) to count as hit

    def to_dict(self) -> dict:
        return {
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi_buy_max": self.rsi_buy_max,
            "rsi_sell_max": self.rsi_sell_max,
            "accuracy_horizon": self.accuracy_horizon,
            "accuracy_min_move_pct": self.accuracy_min_move_pct,
        }


def settings_path(cfg: Config) -> Path:
    return cfg.data.processed_data_dir / "rules_settings.json"


def load_settings(cfg: Config) -> SignalSettings:
    """Load saved settings, falling back to defaults merged with cfg.rules."""
    defaults = SignalSettings(
        timeframe=cfg.rules.timeframe,
        ema_fast=cfg.rules.ema_fast,
        ema_slow=cfg.rules.ema_slow,
        rsi_buy_max=cfg.rules.rsi_buy_max,
        rsi_sell_max=cfg.rules.rsi_sell_max,
    )
    path = settings_path(cfg)
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text())
        symbols = list(raw.get("symbols") or defaults.symbols)
        return SignalSettings(
            symbols=symbols,
            timeframe=raw.get("timeframe", defaults.timeframe),
            ema_fast=int(raw.get("ema_fast", defaults.ema_fast)),
            ema_slow=int(raw.get("ema_slow", defaults.ema_slow)),
            rsi_buy_max=float(raw.get("rsi_buy_max", defaults.rsi_buy_max)),
            rsi_sell_max=float(raw.get("rsi_sell_max", defaults.rsi_sell_max)),
            accuracy_horizon=int(raw.get("accuracy_horizon", defaults.accuracy_horizon)),
            accuracy_min_move_pct=float(
                raw.get("accuracy_min_move_pct", defaults.accuracy_min_move_pct)
            ),
        )
    except Exception as exc:  # noqa: BLE001 - corrupted settings should not crash
        logger.warning("Could not parse settings %s (%s); using defaults", path, exc)
        return defaults


def save_settings(cfg: Config, settings: SignalSettings) -> SignalSettings:
    path = settings_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), indent=2))
    logger.info("Saved signals settings to %s", path)
    return settings
