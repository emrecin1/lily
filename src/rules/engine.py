"""Rule-based demo trading engine — simulates one coin over its candles.

For each candle (in chronological order):
  1. If a position is open, apply price-based exits first:
       stop-loss, take-profit, trailing stop.
  2. If a position is open, check the rule signal for a SAT (close at close
     price), unless a price-based exit already closed it.
  3. If flat, check the rule signal for an AL; on AL open a position at the
     candle's open price (plus slippage), sized from a per-coin allocation.

All fills include taker fee + slippage. No real orders are ever sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import Config
from src.features.indicators import FeatureColumns as FC
from src.logging_config import get_logger
from src.rules.position import DemoPosition
from src.rules.signal import RulesSignal, rules_signal

logger = get_logger("rules.engine")


@dataclass
class RulesTrade:
    symbol: str
    entry_time: Any
    entry_price: float
    exit_time: Any
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees: float
    exit_reason: str  # "signal_sat" | "take_profit" | "stop_loss" | "trailing_stop"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_time": str(self.entry_time),
            "entry_price": round(self.entry_price, 6),
            "exit_time": str(self.exit_time),
            "exit_price": round(self.exit_price, 6),
            "quantity": round(self.quantity, 8),
            "pnl": round(self.pnl, 6),
            "pnl_pct": round(self.pnl_pct, 6),
            "fees": round(self.fees, 6),
            "exit_reason": self.exit_reason,
        }


@dataclass
class CoinResult:
    symbol: str
    starting_balance: float
    ending_balance: float
    total_return: float
    num_trades: int
    win_rate: float
    open_position: DemoPosition | None
    signals: list[RulesSignal] = field(default_factory=list)
    trades: list[RulesTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "starting_balance": round(self.starting_balance, 2),
            "ending_balance": round(self.ending_balance, 2),
            "total_return": round(self.total_return, 6),
            "num_trades": self.num_trades,
            "win_rate": round(self.win_rate, 4),
            "open_position": self.open_position.to_dict()
            if self.open_position is not None
            else None,
            "signals": [s.to_dict() for s in self.signals],
            "trades": [t.to_dict() for t in self.trades],
        }


def run_coin(
    cfg: Config,
    df,
    symbol: str,
    starting_balance: float,
    close_open_position: bool = True,
) -> CoinResult:
    """Run the rule strategy over one coin's feature frame (sorted ascending).

    Args:
        cfg: application config (uses cfg.rules.*).
        df: OHLCV + feature frame with columns timestamp/open/high/low/close/volume
            plus ema20/ema50/rsi. Must be sorted by timestamp ascending.
        symbol: coin symbol.
        starting_balance: demo balance allocated to this coin.
        close_open_position: if True, any position still open at the end is
            marked-to-market and closed at the final close (end_of_session).

    Returns:
        CoinResult with trades, signals, end state and equity curve.
    """
    df = df.sort_values("timestamp").reset_index(drop=True)

    alloc = starting_balance * cfg.rules.allocation_per_coin
    cash = starting_balance
    position: DemoPosition | None = None
    trades: list[RulesTrade] = []
    signals: list[RulesSignal] = []
    equity: list[dict] = []
    fee = cfg.rules.taker_fee
    slip = cfg.rules.slippage

    for _, row in df.iterrows():
        ts = row["timestamp"]
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])

        # ---------------- exit handling -------------------------------------------------
        if position is not None:
            position.update_peak(h)
            exit_price = None
            reason = None

            # take-profit
            if h >= position.tp_price:
                exit_price = position.tp_price * (1 - slip)
                reason = "take_profit"
            # stop-loss
            elif l <= position.stop_price:
                exit_price = position.stop_price * (1 - slip)
                reason = "stop_loss"
            # trailing stop
            else:
                trail = position.trailing_exit_price()
                if trail is not None and l <= trail:
                    exit_price = trail * (1 - slip)
                    reason = "trailing_stop"

            # rule-based SAT (fills at close)
            if exit_price is None:
                sig = rules_signal(cfg, row, symbol, has_position=True)
                signals.append(sig)
                if sig.action == "SAT":
                    exit_price = c * (1 - slip)
                    reason = "signal_sat"

            if exit_price is not None and position is not None:
                proceeds = _close(cfg, trades, position, ts, exit_price, reason, fee)
                cash += proceeds
                position = None
                equity.append({"timestamp": str(ts), "equity": cash, "symbol": symbol})

        # ---------------- entry handling -------------------------------------------------
        if position is None:
            sig = rules_signal(cfg, row, symbol, has_position=False)
            signals.append(sig)
            # Only enter if we have enough cash to both size the position and
            # pay the entry fee — this guarantees cash never goes negative and
            # caps risk per coin (minimum risk requirement).
            risk_cap = min(alloc, cash)
            if sig.action == "AL" and risk_cap > 0:
                price = o * (1 + slip)
                entry_fee = risk_cap * fee
                quantity = risk_cap / price
                cash -= risk_cap + entry_fee
                position = DemoPosition(
                    symbol=symbol,
                    entry_time=ts,
                    entry_price=price,
                    quantity=quantity,
                    initial_balance_used=risk_cap,
                    cfg=cfg,
                )
                logger.info("[%s] AL %s @ %.4f qty=%.6f", symbol, ts, price, quantity)
                equity.append({"timestamp": str(ts), "equity": cash, "symbol": symbol})
        else:
            equity.append({"timestamp": str(ts), "equity": cash, "symbol": symbol})

    # ---------------- force-close a still-open position at end -------------------------------------------------
    if position is not None and close_open_position:
        last = df.iloc[-1]
        proceeds = _close(cfg, trades, position, last["timestamp"], float(last["close"]) * (1 - slip), "end_of_session", fee)
        cash += proceeds
        position = None
        equity.append({"timestamp": str(last["timestamp"]), "equity": cash, "symbol": symbol})

    ending_balance = cash
    # If still open without close, mark-to-market the open position value.
    if position is not None:
        last = df.iloc[-1]
        mark = float(last["close"])
        ending_balance = cash + position.quantity * mark

    ret = (ending_balance / starting_balance) - 1 if starting_balance else 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return CoinResult(
        symbol=symbol,
        starting_balance=round(starting_balance, 2),
        ending_balance=round(ending_balance, 2),
        total_return=round(ret, 6),
        num_trades=len(trades),
        win_rate=round(wins / len(trades), 4) if trades else 0.0,
        open_position=position,
        trades=trades,
        signals=signals,
        equity_curve=equity,
    )


def _close(
    cfg: Config,
    trades: list[RulesTrade],
    position: DemoPosition,
    exit_time: Any,
    exit_price: float,
    reason: str,
    fee: float,
) -> float:
    """Close a position, record the trade, and return cash proceeds (>=0)."""
    entry_notional = position.entry_price * position.quantity
    exit_notional = exit_price * position.quantity
    entry_fee = entry_notional * fee
    exit_fee = exit_notional * fee
    pnl = exit_notional - entry_notional - entry_fee - exit_fee
    pnl_pct = pnl / entry_notional if entry_notional else 0.0
    proceeds = exit_notional - exit_fee

    trades.append(
        RulesTrade(
            symbol=position.symbol,
            entry_time=position.entry_time,
            entry_price=position.entry_price,
            exit_time=exit_time,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=entry_fee + exit_fee,
            exit_reason=reason,
        )
    )
    logger.info("[%s] SAT %s @ %.4f (%s) pnl=%.2f", position.symbol, exit_time, exit_price, reason, pnl)
    return proceeds
