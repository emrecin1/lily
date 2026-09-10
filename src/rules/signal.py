"""Rule-based AL/SAT signal generation (Trend + RSI).

Decision logic (per coin, on the closing of each candle):

    AL   — no position AND EMA(fast) > EMA(slow) AND RSI < rsi_buy_max
    SAT  — holding a position AND (EMA(fast) < EMA(slow) OR RSI > rsi_sell_max)
    HOLD — otherwise

This is deliberately simple and deterministic (no ML), so behaviour is easy
to reason about and backtest — the "sorunsuz çalışması" requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import math

from src.config import Config
from src.features.indicators import FeatureColumns as FC
from src.logging_config import get_logger

logger = get_logger("rules.signal")


@dataclass
class RulesSignal:
    """One signal for a coin at a given candle."""

    symbol: str
    timestamp: Any
    action: str  # "AL" | "SAT" | "HOLD"
    price: float
    ema_fast: float | None
    ema_slow: float | None
    rsi: float | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": str(self.timestamp),
            "action": self.action,
            "price": self.price,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi": self.rsi,
            "reason": self.reason,
        }


def _notna(v: Any) -> bool:
    if v is None:
        return False
    try:
        return not math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def rules_signal(
    cfg: Config,
    row: Any,
    symbol: str,
    has_position: bool,
) -> RulesSignal:
    """Compute the AL/SAT/HOLD signal for one candle.

    Args:
        cfg: Config (uses cfg.rules.* parameters).
        row: a Series/dict with EMA fast, EMA slow and RSI columns.
        symbol: coin symbol for the log/output.
        has_position: whether the portfolio holds a position for this coin.
    """
    fast_col = FC.EMA20 if cfg.rules.ema_fast == 20 else _env_ema(cfg, row, "fast")
    slow_col = FC.EMA50 if cfg.rules.ema_slow == 50 else _env_ema(cfg, row, "slow")

    ema_f = float(row[fast_col]) if _notna(row.get(fast_col)) else None
    ema_s = float(row[slow_col]) if _notna(row.get(slow_col)) else None
    rsi = float(row[FC.RSI]) if _notna(row.get(FC.RSI)) else None
    price = float(row["close"])

    trend_up = ema_f is not None and ema_s is not None and ema_f > ema_s
    trend_down = ema_f is not None and ema_s is not None and ema_f < ema_s
    rsi_ok = rsi is not None and rsi < cfg.rules.rsi_buy_max
    rsi_high = rsi is not None and rsi > cfg.rules.rsi_sell_max

    # ---- AL (only when flat) ----
    if not has_position and trend_up and rsi_ok:
        return RulesSignal(
            symbol=symbol,
            timestamp=row["timestamp"],
            action="AL",
            price=price,
            ema_fast=ema_f,
            ema_slow=ema_s,
            rsi=rsi,
            reason=(
                f"EMA_fast({ema_f:.2f}) > EMA_slow({ema_s:.2f}) ve "
                f"RSI({rsi:.2f}) < {cfg.rules.rsi_buy_max:.0f}"
            ),
        )

    # ---- SAT (only when holding) ----
    if has_position and (trend_down or rsi_high):
        reasons = []
        if trend_down:
            reasons.append(f"EMA_fast({ema_f:.2f}) < EMA_slow({ema_s:.2f})")
        if rsi_high:
            reasons.append(f"RSI({rsi:.2f}) > {cfg.rules.rsi_sell_max:.0f}")
        return RulesSignal(
            symbol=symbol,
            timestamp=row["timestamp"],
            action="SAT",
            price=price,
            ema_fast=ema_f,
            ema_slow=ema_s,
            rsi=rsi,
            reason="; ".join(reasons),
        )

    # ---- HOLD ----
    reasons = []
    if not trend_up:
        reasons.append("trend yok (EMA_fast <= EMA_slow)")
    if not rsi_ok:
        reasons.append(f"RSI({rsi if rsi is not None else 'n/a'}) >= {cfg.rules.rsi_buy_max:.0f}")
    return RulesSignal(
        symbol=symbol,
        timestamp=row["timestamp"],
        action="HOLD",
        price=price,
        ema_fast=ema_f,
        ema_slow=ema_s,
        rsi=rsi,
        reason="; ".join(reasons) if reasons else "bekle",
    )


def _env_ema(cfg: Config, row: Any, which: str) -> str:
    """Resolve a non-20/50 EMA column name from the rules params.

    For the default config (20/50) the standard FeatureColumns are used.
    For custom windows this returns a dynamic column name computed inline.
    """
    window = cfg.rules.ema_fast if which == "fast" else cfg.rules.ema_slow
    col = f"ema_{window}"
    if col not in row:
        raise KeyError(
            f"EMA column '{col}' not present. Rules EMA windows must be "
            "produced by the feature engine (supported generically only for "
            "20/50 by default; add custom windows to src/features/indicators.py)."
        )
    return col
