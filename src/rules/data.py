"""Rule-based AL/SAT demo trading — per-coin and cross-coin data access.

Reuses the existing downloader + indicator pipeline, generalized to run
for each configured symbol at the rules timeframe (default 4h).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd

from src.config import Config
from src.data.downloader import Downloader
from src.features.indicators import add_indicators
from src.logging_config import get_logger

logger = get_logger("rules.data")


def config_for_symbol(cfg: Config, symbol: str) -> Config:
    """Return a Config whose trading.symbol/timeframe match the rules for a
    given coin, so the shared Downloader/indicator pipeline works unchanged."""
    trading = dataclasses.replace(
        cfg.trading,
        symbol=symbol,
        timeframe=cfg.rules.timeframe,
        exchange=cfg.rules.exchange,
    )
    return dataclasses.replace(cfg, trading=trading)


def fetch_coin_features(cfg: Config, symbol: str) -> pd.DataFrame:
    """Fetch OHLCV for one coin at the rules timeframe, then add indicators.

    The returned frame is sorted ascending by timestamp and includes
    ema20, ema50, rsi plus raw OHLCV needed by the rules engine.
    """
    coin_cfg = config_for_symbol(cfg, symbol)
    downloader = Downloader(coin_cfg)
    raw = downloader.fetch_ohlcv()
    downloader.validate(raw)
    raw = raw.sort_values("timestamp").reset_index(drop=True)
    df = add_indicators(raw)
    df["symbol"] = symbol
    return df


def save_features(cfg: Config, df: pd.DataFrame, symbol: str) -> Path:
    """Persist a coin's computed features to processed/features_rules_<sym>.csv."""
    out_dir = cfg.data.processed_data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("/", "_")
    path = out_dir / f"features_rules_{safe}.csv"
    df.to_csv(path, index=False)
    return path
