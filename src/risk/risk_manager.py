"""Risk Manager — the risk-engineering core of the system.

The RiskManager is the sole authority that decides:
    - whether new positions may be opened (max positions, daily loss,
      consecutive-loss pause, live-trading checks, enough capital)
    - how large a position may be (ATR-based sizing, capped by available
      balance / max position size)
    - where the stop-loss and take-profit levels are placed

It is deliberately stateless between calls except for the few fields it owns
(daily_losses, consecutive_losses, last day) so it can be reused identically
by the backtest engine, the paper trader, and (future) live trading.

Key invariants enforced here:
    1. Risk per trade never exceeds ``max_risk_per_trade``.
    2. No new position is opened once the daily loss limit is hit.
    3. No new position is opened once the consecutive-loss pause is active.
    4. Position sizing accounts for fees + slippage and available balance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date

from src.config import Config
from src.logging_config import get_logger
from src.strategy.signal import SignalResult

logger = get_logger("risk.risk_manager")


@dataclass
class PositionPlan:
    """Output of risk manager: how/what to trade (no order placement)."""

    entry_price: float
    position_size: float  # in base asset (e.g. BTC)
    notional: float
    entry_fee: float
    entry_cost: float
    stop_price: float
    target_price: float
    risk_distance: float
    risk_amount: float
    reason: str = ""


@dataclass
class RiskDecision:
    """Outcome of a risk manager check before opening a position."""

    allowed: bool
    coin: str  # 'size' | 'entry' | 'disabled' | 'ml_signal'
    reason: str = ""


@dataclass
class RiskManager:
    """Standalone, reusable risk-management unit."""

    cfg: Config
    capital: float
    equity_estimate: float | None = None

    # Persistent internal state
    daily_losses: float = 0.0
    consecutive_losses: int = 0
    _last_day: date | None = None
    _paused: bool = False
    _paused_reason: str = ""

    # Runtime non-persistent state
    open_positions: int = 0

    # ------------------------------------------------------------------ #
    # Daily / consecutive-loss protection
    # ------------------------------------------------------------------ #

    def on_new_day(self, day: date) -> None:
        """Roll over to a new trading day: reset daily losses."""
        if self._last_day is not None and day != self._last_day:
            self.daily_losses = 0.0
            # Pause from consecutive losses is NOT cleared daily by default;
            # only the daily counter resets. (This is the documented policy:
            # a consecutive-loss pause is a stronger protection.)
        self._last_day = day

    def register_trade_result(self, pnl: float) -> None:
        """Feed back a settled trade's PnL to update loss trackers."""
        if pnl < 0:
            self.daily_losses += abs(pnl) / self.cfg.trading.initial_capital
            self.consecutive_losses += 1
            if (self.daily_losses >= self.cfg.trading.max_daily_loss
                    or self.consecutive_losses >= self.cfg.trading.max_consecutive_losses):
                self._paused = True
                self._paused_reason = (
                    "daily_loss" if self.daily_losses >= self.cfg.trading.max_daily_loss
                    else "consecutive_loss"
                )
                logger.warning(
                    "Risk pause triggered (%s): daily=%.4f consecutive=%d",
                    self._paused_reason, self.daily_losses, self.consecutive_losses,
                )
        else:
            self.consecutive_losses = 0

    @property
    def trading_disabled(self) -> bool:
        """True if the risk layer refuses any new position."""
        if self._paused:
            return True
        # A loss so severe that equity can't cover a single unit of risk.
        effective_equity = self.equity_estimate or self.capital
        min_risk = effective_equity * self.cfg.trading.max_risk_per_trade
        return min_risk <= 0

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    def plan_position(
        self,
        entry_price: float,
        atr: float,
        signal: SignalResult | None = None,
        overrides: dict | None = None,
    ) -> RiskDecision | PositionPlan:
        """Compute an executable position plan, or return a RiskDecision
        explaining why the position is not allowed.

        Returns:
            PositionPlan on success, or RiskDecision with allowed=False.
        """
        if signal is not None and signal.signal != "BUY":
            return RiskDecision(False, "ml_signal",
                                f"signal={signal.signal} — not a BUY")

        if self.trading_disabled:
            return RiskDecision(False, "disabled", self._paused_reason or "disabled")

        if self.cfg.trading.max_open_positions > 0 and self.open_positions >= self.cfg.trading.max_open_positions:
            return RiskDecision(False, "disabled", "max_open_positions reached")

        stop_distance = atr * self.cfg.trading.atr_stop_multiplier
        if stop_distance <= 0 or entry_price <= stop_distance:
            return RiskDecision(False, "size", "invalid stop distance")

        stop_price = entry_price - stop_distance
        target_price = entry_price + stop_distance * self.cfg.trading.risk_reward_ratio

        effective_equity = self.equity_estimate or self.capital
        risk_amount = effective_equity * self.cfg.trading.max_risk_per_trade
        raw_size = risk_amount / stop_distance

        # ---- Sizing caps: available balance, max position size ---------
        taker_fee = self.cfg.trading.taker_fee
        slippage = self.cfg.trading.slippage
        # Entry price already includes slippage from the caller perspective;
        # we account for fee here so the cost stays within capital.
        affordable = self.capital / (entry_price * (1 + taker_fee))
        position_size = min(raw_size, affordable)

        cap = overrides.get("max_position_size") if overrides else None
        if cap is not None:
            position_size = min(position_size, cap)

        if position_size <= 0:
            return RiskDecision(False, "size", "position size <= 0")

        notional = entry_price * position_size
        entry_fee = notional * taker_fee
        entry_cost = notional + entry_fee
        if entry_cost > self.capital:
            return RiskDecision(False, "entry", "entry cost exceeds available capital")

        return PositionPlan(
            entry_price=entry_price,
            position_size=position_size,
            notional=notional,
            entry_fee=entry_fee,
            entry_cost=entry_cost,
            stop_price=stop_price,
            target_price=target_price,
            risk_distance=stop_distance,
            risk_amount=risk_amount,
            reason=(
                f"size={position_size:.6f} risk=${risk_amount:.2f} "
                f"stop={stop_price:.2f} target={target_price:.2f}"
            ),
        )

    def requested_risk_about_exceeds(self, plan: PositionPlan) -> bool:
        """Defensive check: the realized risk on a full stop-out must not
        exceed the configured per-trade risk limit."""
        realized = plan.position_size * plan.risk_distance
        effective_equity = self.equity_estimate or self.capital
        return realized > effective_equity * self.cfg.trading.max_risk_per_trade + 1e-9

    def resume(self) -> None:
        """Manually clear a pause (used by paper/live recovery, not auto)."""
        self._paused = False
        self._paused_reason = ""
        self.daily_losses = 0.0
        self.consecutive_losses = 0