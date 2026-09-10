"""Feature Engineering — technical indicators.

All indicators are computed with forward-looking data strictly excluded.
Every feature value at index *i* depends only on data up to and including
index *i* (rolling/moving window computations look backwards only).

Feature categories and documentation:
    Trends (EMA-based)
        ema20, ema50, ema100, ema200      : exponential moving averages
        close_ema20_ratio                 : close / ema20
        close_ema50_ratio                 : close / ema50
        ema20_ema50_ratio                 : ema20 / ema50
        ema50_ema200_ratio                : ema50 / ema200
    Momentum
        rsi                                : Relative Strength Index (period 14)
        macd, macd_signal, macd_hist        : MACD line, signal line, histogram
        roc                                : rate of change over 10 periods
    Volatility
        atr                                : Average True Range
        vol_12, vol_24, vol_48             : rolling std of returns (12/24/48)
    Volume
        volume_change                      : pct change of volume
        volume_sma_ratio                   : volume / rolling mean volume
        volume_zscore                      : (volume - mean) / std
    Returns
        ret_1, ret_3, ret_6, ret_12, ret_24 : returns over N periods
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from ta.momentum import ROCIndicator, RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange

if TYPE_CHECKING:
    from src.config import Config

# NOT: Bu modul bilerek yalnizca numpy/pandas/ta'ya baglidir (src.config /
# src.logging_config'e DEGIL) — Freqtrade stratejisi add_indicators()'i dogrudan
# import edip V1 ile birebir ayni feature'lari uretebilsin diye. Bkz. Asama 2.
logger = logging.getLogger("ai-crypto-bot.features.indicators")


@dataclass(frozen=True)
class FeatureColumns:
    """Feature column names shared across modules."""

    # Trend
    EMA20 = "ema20"
    EMA50 = "ema50"
    EMA100 = "ema100"
    EMA200 = "ema200"
    CLOSE_EMA20 = "close_ema20_ratio"
    CLOSE_EMA50 = "close_ema50_ratio"
    EMA20_EMA50 = "ema20_ema50_ratio"
    EMA50_EMA200 = "ema50_ema200_ratio"

    # Momentum
    RSI = "rsi"
    MACD = "macd"
    MACD_SIGNAL = "macd_signal"
    MACD_HIST = "macd_hist"
    ROC = "roc"

    # Volatility
    ATR = "atr"
    VOL_12 = "vol_12"
    VOL_24 = "vol_24"
    VOL_48 = "vol_48"

    # Volume
    VOLUME_CHANGE = "volume_change"
    VOLUME_SMA_RATIO = "volume_sma_ratio"
    VOLUME_ZSCORE = "volume_zscore"

    # Returns
    RET_1 = "ret_1"
    RET_3 = "ret_3"
    RET_6 = "ret_6"
    RET_12 = "ret_12"
    RET_24 = "ret_24"


# Every feature column add_indicators() produces (the 25 model features).
ALL_FEATURE_COLUMNS: tuple[str, ...] = (
    FeatureColumns.EMA20, FeatureColumns.EMA50, FeatureColumns.EMA100, FeatureColumns.EMA200,
    FeatureColumns.CLOSE_EMA20, FeatureColumns.CLOSE_EMA50,
    FeatureColumns.EMA20_EMA50, FeatureColumns.EMA50_EMA200,
    FeatureColumns.RSI, FeatureColumns.MACD, FeatureColumns.MACD_SIGNAL,
    FeatureColumns.MACD_HIST, FeatureColumns.ROC,
    FeatureColumns.ATR, FeatureColumns.VOL_12, FeatureColumns.VOL_24, FeatureColumns.VOL_48,
    FeatureColumns.VOLUME_CHANGE, FeatureColumns.VOLUME_SMA_RATIO, FeatureColumns.VOLUME_ZSCORE,
    FeatureColumns.RET_1, FeatureColumns.RET_3, FeatureColumns.RET_6,
    FeatureColumns.RET_12, FeatureColumns.RET_24,
)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return EMAIndicator(series, window=period).ema_indicator()


def _no_lookahead_shift(series: pd.Series, periods: int) -> pd.Series:
    """Re-export of pandas shift with explicit documentation that it only
    uses past values. Kept as a named helper for clarity/safety."""
    return series.shift(periods)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicator features to a raw OHLCV frame.

    The input must already be sorted by timestamp ascending. The result
    contains the original columns plus the computed features.

    Important: this function mutates/annotates a copy; the original frame
    is not modified.

    Robustness: some callers (e.g. FreqAI's feature-population probes) pass a
    very short frame. The `ta` library's ATR/RSI crash with an IndexError on
    fewer than ~15 rows, so for short inputs we return the frame with every
    feature column present but NaN (warm-up rows would be NaN anyway).
    """
    out = df.copy()

    if len(out) < 30:
        for col in ALL_FEATURE_COLUMNS:
            out[col] = np.nan
        return out

    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]

    # ---- Trend ---------------------------------------------------------
    out[FeatureColumns.EMA20] = _ema(close, 20)
    out[FeatureColumns.EMA50] = _ema(close, 50)
    out[FeatureColumns.EMA100] = _ema(close, 100)
    out[FeatureColumns.EMA200] = _ema(close, 200)

    out[FeatureColumns.CLOSE_EMA20] = close / out[FeatureColumns.EMA20]
    out[FeatureColumns.CLOSE_EMA50] = close / out[FeatureColumns.EMA50]
    out[FeatureColumns.EMA20_EMA50] = (
        out[FeatureColumns.EMA20] / out[FeatureColumns.EMA50]
    )
    out[FeatureColumns.EMA50_EMA200] = (
        out[FeatureColumns.EMA50] / out[FeatureColumns.EMA200]
    )

    # ---- Momentum ------------------------------------------------------
    out[FeatureColumns.RSI] = RSIIndicator(close, window=14).rsi()

    macd = MACD(close)
    out[FeatureColumns.MACD] = macd.macd()
    out[FeatureColumns.MACD_SIGNAL] = macd.macd_signal()
    out[FeatureColumns.MACD_HIST] = macd.macd_diff()

    out[FeatureColumns.ROC] = ROCIndicator(close, window=10).roc()

    # ---- Volatility ----------------------------------------------------
    atr = AverageTrueRange(high, low, close, window=14)
    out[FeatureColumns.ATR] = atr.average_true_range()

    returns = close.pct_change()
    out[FeatureColumns.VOL_12] = returns.rolling(12).std().fillna(0.0)
    out[FeatureColumns.VOL_24] = returns.rolling(24).std().fillna(0.0)
    out[FeatureColumns.VOL_48] = returns.rolling(48).std().fillna(0.0)

    # ---- Volume --------------------------------------------------------
    volume_sma = volume.rolling(20).mean()
    volume_safe = volume.replace(0.0, np.nan)
    prev_volume = volume_safe.shift(1)
    out[FeatureColumns.VOLUME_CHANGE] = (volume_safe - prev_volume) / prev_volume

    out[FeatureColumns.VOLUME_SMA_RATIO] = volume / volume_sma

    volume_mean = volume.rolling(20).mean()
    volume_std = volume.rolling(20).std().replace(0.0, np.nan)
    out[FeatureColumns.VOLUME_ZSCORE] = (volume - volume_mean) / volume_std

    # ---- Returns -------------------------------------------------------
    out[FeatureColumns.RET_1] = close.pct_change(1)
    out[FeatureColumns.RET_3] = close.pct_change(3)
    out[FeatureColumns.RET_6] = close.pct_change(6)
    out[FeatureColumns.RET_12] = close.pct_change(12)
    out[FeatureColumns.RET_24] = close.pct_change(24)

    # Safety: no inf values must survive into the output. Replace any inf
    # with NaN (warm-up rows are already NaN). This prevents downstream
    # crashes in ML training and scoring.
    out.replace([np.inf, -np.inf], np.nan, inplace=True)

    return out


def build_feature_frame(config: Config) -> pd.DataFrame:
    """Load candles from the database, compute features, and persist to
    `data/processed/features.csv`.

    Returns:
        The full frame with features (sorted by timestamp).
    """
    from src.data.database import Candle, Database

    db = Database(config)
    with db.session() as session:
        rows = (
            session.query(Candle)
            .filter(
                Candle.symbol == config.trading.symbol,
                Candle.timeframe == config.trading.timeframe,
            )
            .order_by(Candle.timestamp)
            .all()
        )
        df = pd.DataFrame(
            [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in rows
            ]
        )

    if df.empty:
        raise RuntimeError(
            "No candles found in database. Run `python main.py download-data` first."
        )

    feats = add_indicators(df)

    config.data.processed_data_dir.mkdir(parents=True, exist_ok=True)
    out_path = config.data.processed_data_dir / "features.csv"
    feats.to_csv(out_path, index=False)
    logger.info("Wrote %d feature rows to %s", len(feats), out_path)

    return feats