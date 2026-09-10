"""Signal Engine — BUY / HOLD / EXIT decision from model output.

In V1 the signal engine is a thin deterministic filter on top of model
probabilities. It never trades on its own; it produces a structured signal
that downstream components (risk manager / backtest / paper trader) consume.

Decision logic:
    BUY  — probability >= threshold  AND  trend_ok (EMA20 > EMA50)  AND  rsi_ok (RSI < RSI_BUY_MAX)
    HOLD — probability >= threshold but a filter fails (or no position to exit)
    EXIT — probability < 0.40  (optional early-exit hint; stop/target override)

The backtest engine can use the signal hint but stop/target are the
authoritative exit triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import Config
from src.logging_config import get_logger
from src.features.indicators import FeatureColumns as FC

logger = get_logger("strategy.signal")


@dataclass
class SignalResult:
    """Deterministic output of the signal engine for one timestep."""

    signal: str  # "BUY" | "HOLD" | "EXIT"
    probability: float
    trend_ok: bool
    rsi_ok: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "probability": self.probability,
            "trend_ok": self.trend_ok,
            "rsi_ok": self.rsi_ok,
            "reason": self.reason,
        }


def generate_signal(
    probability: float,
    row: dict | Any,
    cfg: Config,
    has_position: bool = False,
) -> SignalResult:
    """Produce a deterministic BUY / HOLD / EXIT signal.

    Args:
        probability: Model predicted probability (0..1).
        row: A single-row feature dict or pandas Series containing at least
            ``ema20``, ``ema50``, ``rsi``, ``atr``.
        cfg: Application configuration.
        has_position: Whether the portfolio currently holds a position.

    Returns:
        SignalResult with signal, probability, flags, and a human-readable
        reason string.
    """
    threshold = cfg.trading.ai_threshold
    rsi_max = cfg.trading.rsi_buy_max

    ema20 = float(row[FC.EMA20]) if pd_notna(row.get(FC.EMA20)) else None
    ema50 = float(row[FC.EMA50]) if pd_notna(row.get(FC.EMA50)) else None
    rsi_val = float(row[FC.RSI]) if pd_notna(row.get(FC.RSI)) else None

    trend_ok = ema20 is not None and ema50 is not None and ema20 > ema50
    rsi_ok = rsi_val is not None and rsi_val < rsi_max

    # --- EXIT ---
    if probability < 0.40 and has_position:
        return SignalResult(
            signal="EXIT",
            probability=probability,
            trend_ok=trend_ok,
            rsi_ok=rsi_ok,
            reason=f"probability {probability:.4f} < 0.40 — weak signal, consider exit",
        )

    # --- BUY ---
    if probability >= threshold and trend_ok and rsi_ok:
        reason = (
            f"probability {probability:.4f} >= {threshold:.2f}, "
            f"EMA20({ema20:.2f}) > EMA50({ema50:.2f}), "
            f"RSI({rsi_val:.2f}) < {rsi_max:.0f}"
        )
        return SignalResult(
            signal="BUY",
            probability=probability,
            trend_ok=trend_ok,
            rsi_ok=rsi_ok,
            reason=reason,
        )

    # --- HOLD ---
    reasons: list[str] = []
    if probability < threshold:
        reasons.append(f"probability {probability:.4f} < {threshold:.2f}")
    if not trend_ok:
        reasons.append(
            f"trend_fail: EMA20={ema20}, EMA50={ema50}"
            if ema20 is not None and ema50 is not None
            else "trend_fail: missing EMA data"
        )
    if not rsi_ok:
        reasons.append(
            f"RSI_fail: RSI={rsi_val}" if rsi_val is not None else "RSI_fail: missing RSI"
        )

    return SignalResult(
        signal="HOLD",
        probability=probability,
        trend_ok=trend_ok,
        rsi_ok=rsi_ok,
        reason="; ".join(reasons),
    )


def pd_notna(value: Any) -> bool:
    """Check that a value is not NaN (works with numpy/pandas NaN)."""
    import math

    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False