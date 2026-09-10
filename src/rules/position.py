"""Per-coin demo position with percentage TP/SL and trailing stop.

State model for one open long position in the demo account.

Exit rules (checked on each candle while a position is open):
    * take-profit  : price reaches entry * (1 + tp_pct)      -> close at TP.
    * stop-loss    : price touches entry * (1 - sl_pct)      -> close at SL.
    * trailing     : if enabled, track the highest price since entry and
                     close when price falls trailing_pct below that peak
                     (e.g. rose 1.0 -> 2.0, closes near 1.5 if trailing=0.25).
    * signal SAT   : rule-based SAT (handled by the engine, not this class).

Fees and slippage are applied by the engine on fill, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import Config


@dataclass
class DemoPosition:
    symbol: str
    entry_time: Any
    entry_price: float
    quantity: float          # amount of the coin held
    initial_balance_used: float
    cfg: Config = field(repr=False)
    highest_price: float = 0.0
    stop_price: float = 0.0
    tp_price: float = 0.0
    open_time: Any = None

    def __post_init__(self) -> None:
        self.highest_price = self.entry_price
        self.stop_price = self.entry_price * (1 - self.cfg.rules.stop_loss_pct)
        self.tp_price = self.entry_price * (1 + self.cfg.rules.take_profit_pct)
        self.open_time = self.entry_time

    def update_peak(self, high: float) -> None:
        """Track the highest price reached since entry (for trailing stop)."""
        if high > self.highest_price:
            self.highest_price = high

    def trailing_exit_price(self) -> float | None:
        """Return the trailing stop level if enabled, else None."""
        if not self.cfg.rules.use_trailing:
            return None
        return self.highest_price * (1 - self.cfg.rules.trailing_pct)

    def current_pnl_pct(self, price: float) -> float:
        return (price / self.entry_price) - 1.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_time": str(self.entry_time),
            "entry_price": round(self.entry_price, 6),
            "quantity": round(self.quantity, 8),
            "stop_price": round(self.stop_price, 6),
            "tp_price": round(self.tp_price, 6),
            "highest_price": round(self.highest_price, 6),
            "current_pnl_pct": round(self.current_pnl_pct(self.highest_price), 6),
            "trailing_exit": round(self.trailing_exit_price(), 6)
            if self.trailing_exit_price() is not None
            else None,
        }
