"""Signal engine + accuracy evaluation for the rule-based AL/SAT system.

Produces per-coin signals (AL/SAT/HOLD) over a feature frame and evaluates
their historical accuracy: for every AL signal, does the price actually move
up in the following `horizon` candles by at least `min_move_pct`?

This is the "sinyallerin doğru gelip gelmediğini kontrol et" requirement:
the dashboard shows signal-by-signal outcomes and an aggregate accuracy %.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import Config
from src.logging_config import get_logger
from src.rules.signal import RulesSignal, rules_signal

logger = get_logger("rules.engine")


@dataclass
class SignalRecord:
    symbol: str
    timestamp: Any
    action: str
    price: float
    ema_fast: float | None
    ema_slow: float | None
    rsi: float | None
    reason: str
    # accuracy fields (for AL signals)
    close_after: float | None = None
    outcome: str | None = None  # "hit" | "miss" | None (too recent to evaluate)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": str(self.timestamp),
            "action": self.action,
            "price": round(self.price, 6),
            "ema_fast": round(self.ema_fast, 4) if self.ema_fast is not None else None,
            "ema_slow": round(self.ema_slow, 4) if self.ema_slow is not None else None,
            "rsi": round(self.rsi, 4) if self.rsi is not None else None,
            "reason": self.reason,
            "close_after": round(self.close_after, 6) if self.close_after is not None else None,
            "outcome": self.outcome,
            "accuracy_pct": self.would_hit if hasattr(self, "would_hit") else None,
        }


@dataclass
class SignalResultSet:
    symbol: str
    timeframe: str
    records: list[SignalRecord] = field(default_factory=list)

    def al_signals(self) -> list[SignalRecord]:
        return [r for r in self.records if r.action == "AL"]

    def accuracy(self) -> float | None:
        """Fraction of evaluated AL signals that were hits, else None."""
        hits = [r for r in self.al_signals() if r.outcome == "hit"]
        evaluated = [r for r in self.al_signals() if r.outcome in ("hit", "miss")]
        if not evaluated:
            return None
        return len(hits) / len(evaluated)

    def evaluated_count(self) -> int:
        return sum(1 for r in self.al_signals() if r.outcome in ("hit", "miss"))

    def to_dict(self) -> dict:
        acc = self.accuracy()
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "num_signals": len(self.records),
            "num_al": len(self.al_signals()),
            "accuracy": round(acc, 4) if acc is not None else None,
            "evaluated": self.evaluated_count(),
            "records": [r.to_dict() for r in self.records[-200:]],
        }


def evaluate_accuracy(
    cfg: Config,
    df,
    symbol: str,
    horizon: int = 4,
    min_move_pct: float = 0.01,
) -> SignalResultSet:
    """Generate signals over a feature frame and evaluate AL accuracy.

    For each candle whose AL signal fires, look ahead `horizon` candles; if
    the close `horizon` bars later is at least `min_move_pct` above the AL
    signal price, the signal is a "hit", otherwise a "miss". Signals too
    recent to evaluate get outcome=None.

    Args:
        cfg: application config (uses cfg.rules.* for signal params).
        df: OHLCV + feature frame sorted ascending by timestamp.
        symbol: coin symbol.
        horizon: how many candles ahead to evaluate (default 4 -> ~16h on 4h).
        min_move_pct: required upward move to count as a hit (default 1%).
    """
    df = df.sort_values("timestamp").reset_index(drop=True)
    closes = df["close"].tolist()
    records: list[SignalRecord] = []

    for i, row in df.iterrows():
        sig = rules_signal(cfg, row, symbol, has_position=False)
        rec = SignalRecord(
            symbol=symbol,
            timestamp=row["timestamp"],
            action=sig.action,
            price=sig.price,
            ema_fast=sig.ema_fast,
            ema_slow=sig.ema_slow,
            rsi=sig.rsi,
            reason=sig.reason,
        )
        if sig.action == "AL":
            j = i + horizon
            if j < len(closes):
                future_close = closes[j]
                rec.close_after = future_close
                rec.outcome = (
                    "hit" if (future_close / sig.price - 1.0) >= min_move_pct else "miss"
                )
            else:
                rec.outcome = None  # too recent
        records.append(rec)

    logger.info(
        "[%s] %d signals (%d AL), accuracy=%s",
        symbol, len(records), sum(1 for r in records if r.action == "AL"),
        SignalResultSet(symbol, cfg.rules.timeframe, records).accuracy(),
    )
    return SignalResultSet(symbol=symbol, timeframe=cfg.rules.timeframe, records=records)
