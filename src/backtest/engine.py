"""Backtesting engine — realistic simulation of the trading pipeline.

For every candle the engine:
    1.  Looks at data only up to and including that candle (no future).
    2.  Loads model prediction (precomputed for speed on historical data).
    3.  Calls the signal engine.
    4.  If no position: checks risk limits → optionally enters.
    5.  If in position: checks stop / take-profit → optionally exits.
    6.  Applies fee + slippage on every execution.
    7.  Records the trade and equity snapshot.

Execution policy (deterministic, documented):
    If both stop-loss and take-profit are breached within the same candle,
    the engine conservatively assumes the stop-loss was hit first. The exit
    price is then:  entry_price - stop_distance - slippage.

Slippage model (simple fixed-cost):
    - BUY  fill = candle_open × (1 + slippage)   (paying up)
    - SELL fill = candle_open × (1 - slippage)    (selling down)

    Using the candle's **open** price for fills avoids look-ahead bias
    (the high/low are not available at the open in real-time).

    Stop / target exits use the candle's **low** / **high** as boundary
    checks.  The fill is taken as the limit price ± slippage, clipped
    to the candle range [low, high].

Capital accounting:
    Cash = initial_capital
    On entry:  cash -= entry_notional + entry_fee
    On exit:   cash += exit_notional - exit_fee
    Unrealised (mark-to-market): cash + current_close × position_size

    Total PnL = exit_notional - entry_notional - entry_fee - exit_fee
    (slippage is embedded in entry/exit prices; tracked separately
     as the cost relative to the candle open for reporting only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from src.config import Config
from src.logging_config import get_logger
from src.ml.dataset import feature_columns
from src.ml.metrics import (
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    total_return_from_equity,
    trade_statistics,
)
from src.strategy.signal import generate_signal

logger = get_logger("backtest.engine")


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class Position:
    """Tracks the currently open long position."""

    entry_time: datetime
    entry_price: float
    position_size: float
    stop_price: float
    target_price: float
    risk_distance: float


@dataclass
class TradeRecord:
    """One completed trade."""

    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    position_size: float
    fees: float
    slippage: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestStats:
    """Summary statistics produced at the end of a backtest run."""

    initial_capital: float
    final_capital: float
    total_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    profit_factor: float
    win_rate: float
    num_trades: int
    avg_trade: float
    avg_win: float
    avg_loss: float
    largest_losing_streak: int
    total_fees: float
    total_slippage: float


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

class BacktestEngine:
    """Event-driven backtest over a labelled, feature-complete OHLCV frame.

    The engine is deterministic and reproducible given the same input data,
    model, and configuration.  It never accesses future data.  All prices
    are rounded to avoid floating-point display artefacts.
    """

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.capital: float = config.trading.initial_capital
        self.position: Position | None = None
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[tuple[datetime, float]] = []
        self.daily_start_equity: float | None = None

        from src.risk.risk_manager import RiskManager

        self.risk = RiskManager(config, capital=self.capital)

    # Convenience read-only aliases to the RiskManager (back-compat + clarity)
    @property
    def daily_losses(self) -> float:
        return self.risk.daily_losses

    @property
    def consecutive_losses(self) -> int:
        return self.risk.consecutive_losses

    @property
    def _trading_disabled(self) -> bool:
        return self.risk.trading_disabled

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def run(self) -> tuple[BacktestStats, pd.DataFrame, pd.DataFrame]:
        """Execute the backtest over the full labelled feature frame.

        Returns:
            (stats, equity_df, trades_df)
        """
        full = self._load_data()
        model, _ = self._load_model()
        feature_cols = feature_columns()

        equity_data: list[dict] = []
        self.daily_start_equity = self.capital
        self.risk.daily_losses = 0.0

        for idx in range(len(full)):
            row = full.iloc[idx]
            ts = row["timestamp"]
            candle_open = float(row["open"])
            candle_high = float(row["high"])
            candle_low = float(row["low"])
            candle_close = float(row["close"])

            # --- daily reset (new UTC day) --------------------------------
            self.risk.on_new_day(ts.date())
            if idx > 0 and ts.date() != full.iloc[idx - 1]["timestamp"].date():
                self.daily_start_equity = self.capital

            # --- position exit check ---------------------------------------
            if self.position is not None:
                exit_price, exit_reason = self._check_exit(
                    candle_open, candle_high, candle_low
                )
                if exit_price is not None:
                    self._close_position(ts, exit_price, exit_reason)
                    equity_data.append({"timestamp": ts, "equity": self.capital})

            # --- new entry (only if flat and not disabled) ----------------
            if self.position is None and not self.risk.trading_disabled:
                X_row = row[feature_cols].values.reshape(1, -1)
                prob = float(model.predict_proba(X_row)[0, 1])
                sig = generate_signal(prob, row.to_dict(), self.cfg, has_position=False)

                if sig.signal == "BUY":
                    self._try_entry(ts, candle_open, row, sig=sig)

            equity_data.append(
                {"timestamp": ts, "equity": self._mark_to_market(candle_close)}
            )

        # Close any remaining open position at last close.
        if self.position is not None:
            last_ts = full.iloc[-1]["timestamp"]
            last_close = float(full.iloc[-1]["close"])
            self._close_position(last_ts, last_close, "end_of_backtest")

        equity_df = pd.DataFrame(equity_data)
        trades_df = self._trades_to_df()
        stats = self._compute_stats(equity_df, trades_df)
        self._persist_outputs(equity_df, trades_df, stats)

        return stats, equity_df, trades_df

    # --------------------------------------------------------------------- #
    # Entry
    # --------------------------------------------------------------------- #

    def _try_entry(self, ts: datetime, candle_open: float, row: pd.Series, sig=None) -> None:
        """Attempt to open a new long position via the RiskManager."""
        atr_val = float(row["atr"]) if pd.notna(row.get("atr")) else 0.0
        entry_price = candle_open * (1 + self.cfg.trading.slippage)

        # Keep the RiskManager's view of available capital in sync.
        self.risk.capital = self.capital
        self.risk.equity_estimate = self.capital

        plan = self.risk.plan_position(
            entry_price=entry_price,
            atr=atr_val,
            signal=sig,
        )

        from src.risk.risk_manager import PositionPlan

        if not isinstance(plan, PositionPlan):
            return

        position_size = plan.position_size
        if position_size <= 0:
            return

        self.capital -= plan.entry_cost
        self.risk.open_positions += 1

        self.position = Position(
            entry_time=ts,
            entry_price=entry_price,
            position_size=position_size,
            stop_price=plan.stop_price,
            target_price=plan.target_price,
            risk_distance=plan.risk_distance,
        )

    # --------------------------------------------------------------------- #
    # Exit
    # --------------------------------------------------------------------- #

    def _check_exit(
        self, candle_open: float, candle_high: float, candle_low: float
    ) -> tuple[float | None, str]:
        """Check whether the current candle breaches stop or target.

        Deterministic policy: if both stop and target are hit in the same
        candle, the stop is assumed to be hit first (conservative).

        Returns:
            (exit_price, exit_reason) or (None, "") if no exit.
        """
        pos = self.position
        if pos is None:
            return None, ""

        stop_hit = candle_low <= pos.stop_price
        target_hit = candle_high >= pos.target_price

        if stop_hit:
            # Fill at stop_price minus slippage, clipped to candle low.
            raw_fill = pos.stop_price * (1 - self.cfg.trading.slippage)
            exit_price = max(raw_fill, candle_low)
            return exit_price, "stop"

        if target_hit:
            # Fill at target_price minus slippage, clipped to candle low.
            raw_fill = pos.target_price * (1 - self.cfg.trading.slippage)
            exit_price = max(raw_fill, candle_low)
            return exit_price, "target"

        return None, ""

    def _close_position(
        self, ts: datetime, exit_price: float, reason: str
    ) -> None:
        """Settle an open position and record the trade.

        Accounting:
            cash_before_exit = self.capital
            entry_notional   = entry_price × position_size
            exit_notional    = exit_price  × position_size
            entry_fee        = entry_notional × taker_fee
            exit_fee         = exit_notional  × taker_fee

            cash_after_exit  = cash_before_exit + exit_notional - exit_fee
            pnl              = exit_notional - entry_notional - entry_fee - exit_fee

        Slippage (reporting only):
            entry_slippage   = (entry_price - candle_open_at_entry) × position_size
            exit_slippage    = (exit_candle_open - exit_price)      × position_size
        """
        pos = self.position
        assert pos is not None

        entry_notional = pos.entry_price * pos.position_size
        exit_notional = exit_price * pos.position_size
        entry_fee = entry_notional * self.cfg.trading.taker_fee
        exit_fee = exit_notional * self.cfg.trading.taker_fee

        total_fees = entry_fee + exit_fee
        pnl = exit_notional - entry_notional - entry_fee - exit_fee

        # Slippage tracking (reporting only, not in PnL — embedded in prices)
        entry_slippage_cost = (
            (pos.entry_price - (pos.entry_price / (1 + self.cfg.trading.slippage)))
            * pos.position_size
        )
        exit_slippage_cost = (
            ((exit_price / (1 - self.cfg.trading.slippage)) - exit_price)
            * pos.position_size
        ) if self.cfg.trading.slippage < 1.0 else 0.0
        total_slippage = entry_slippage_cost + exit_slippage_cost

        self.capital += exit_notional - exit_fee

        self.trades.append(
            TradeRecord(
                entry_time=pos.entry_time,
                entry_price=pos.entry_price,
                exit_time=ts,
                exit_price=exit_price,
                position_size=pos.position_size,
                fees=round(total_fees, 6),
                slippage=round(total_slippage, 6),
                pnl=round(pnl, 6),
                exit_reason=reason,
            )
        )

        # Daily / consecutive loss tracking (delegated to RiskManager)
        self.risk.register_trade_result(pnl)
        if self.risk.open_positions > 0:
            self.risk.open_positions -= 1

        self.position = None

    # --------------------------------------------------------------------- #
    # Equity
    # --------------------------------------------------------------------- #

    def _mark_to_market(self, current_close: float) -> float:
        """Return total equity = cash + position market value."""
        base = self.capital
        if self.position is not None:
            base += current_close * self.position.position_size
        return round(base, 2)

    # --------------------------------------------------------------------- #
    # Persistence & reporting
    # --------------------------------------------------------------------- #

    def _load_data(self) -> pd.DataFrame:
        """Load the processed features CSV (OHLCV + features + timestamp)."""
        csv_path = self.cfg.data.processed_data_dir / "features.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"No features file found at {csv_path}. "
                "Run `python main.py build-features` first."
            )
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        return df

    def _load_model(self):
        """Load the trained model and metadata."""
        import joblib
        import json

        model_path = self.cfg.data.models_dir / "model.joblib"
        meta_path = self.cfg.data.models_dir / "model_metadata.json"
        if not model_path.exists():
            raise FileNotFoundError(
                f"No model found at {model_path}. Run `python main.py train` first."
            )
        model = joblib.load(model_path)
        metadata = {}
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)
        return model, metadata

    def _trades_to_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=[
                    "entry_time", "entry_price", "exit_time", "exit_price",
                    "position_size", "fees", "slippage", "pnl", "exit_reason",
                ]
            )
        return pd.DataFrame(
            [
                {
                    "entry_time": t.entry_time,
                    "entry_price": t.entry_price,
                    "exit_time": t.exit_time,
                    "exit_price": t.exit_price,
                    "position_size": t.position_size,
                    "fees": t.fees,
                    "slippage": t.slippage,
                    "pnl": t.pnl,
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ]
        )

    def _compute_stats(
        self, equity_df: pd.DataFrame, trades_df: pd.DataFrame
    ) -> BacktestStats:
        eq = (
            equity_df["equity"].values
            if not equity_df.empty
            else np.array([self.cfg.trading.initial_capital])
        )
        returns = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
        trade_pnls = trades_df["pnl"].values if not trades_df.empty else np.array([])

        ts = trade_statistics(trade_pnls)
        init = self.cfg.trading.initial_capital
        final = float(eq[-1]) if len(eq) > 0 else init

        return BacktestStats(
            initial_capital=init,
            final_capital=round(final, 2),
            total_return=round(total_return_from_equity(init, final), 6),
            max_drawdown=round(max_drawdown(eq), 6),
            sharpe=round(sharpe_ratio(returns), 4),
            sortino=round(sortino_ratio(returns), 4),
            profit_factor=round(ts["profit_factor"], 4),
            win_rate=round(ts["win_rate"], 4),
            num_trades=ts["num_trades"],
            avg_trade=round(ts["average_pnl"], 4),
            avg_win=round(ts["average_win"], 4),
            avg_loss=round(ts["average_loss"], 4),
            largest_losing_streak=ts["largest_losing_streak"],
            total_fees=round(
                float(trades_df["fees"].sum()) if not trades_df.empty else 0.0, 4
            ),
            total_slippage=round(
                float(trades_df["slippage"].sum()) if not trades_df.empty else 0.0, 4
            ),
        )

    def _persist_outputs(
        self,
        equity_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        stats: BacktestStats,
    ) -> None:
        out_dir = self.cfg.data.processed_data_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        eq_path = out_dir / "equity_curve.csv"
        equity_df.to_csv(eq_path, index=False)
        logger.info("Equity curve -> %s (%d rows)", eq_path, len(equity_df))

        trades_path = out_dir / "trades.csv"
        trades_df.to_csv(trades_path, index=False)
        logger.info("Trades log  -> %s (%d trades)", trades_path, len(trades_df))

        logger.info("=" * 55)
        logger.info("BACKTEST RESULTS")
        logger.info("=" * 55)
        logger.info("Initial Capital:     $%s", f"{stats.initial_capital:,.2f}")
        logger.info("Final Capital:       $%s", f"{stats.final_capital:,.2f}")
        logger.info("Total Return:        %s%%", f"{stats.total_return * 100:.2f}")
        logger.info("Max Drawdown:        %s%%", f"{stats.max_drawdown * 100:.2f}")
        logger.info("Sharpe:              %s", f"{stats.sharpe:.4f}")
        logger.info("Sortino:             %s", f"{stats.sortino:.4f}")
        logger.info("Profit Factor:       %s", f"{stats.profit_factor:.4f}")
        logger.info("Win Rate:            %s%%", f"{stats.win_rate * 100:.2f}")
        logger.info("Number of Trades:    %d", stats.num_trades)
        logger.info("Avg Trade:           $%s", f"{stats.avg_trade:,.4f}")
        logger.info("Avg Win:             $%s", f"{stats.avg_win:,.4f}")
        logger.info("Avg Loss:            $%s", f"{stats.avg_loss:,.4f}")
        logger.info("Largest Losing Streak: %d", stats.largest_losing_streak)
        logger.info("Total Fees:          $%s", f"{stats.total_fees:,.4f}")
        logger.info("Total Slippage:      $%s", f"{stats.total_slippage:,.4f}")
        logger.info("=" * 55)


def run_backtest(config: Config) -> None:
    """Top-level backtest entry point called by the CLI."""
    engine = BacktestEngine(config)
    engine.run()