"""Paper trading — live market data with a virtual account.

The PaperTrader consumes real (public) market data, computes features,
runs the trained model through the signal + risk pipeline, and simulates
trades against a virtual balance and virtual position.  It never sends a
real order to an exchange.

Trade order safety:
    This module NEVER calls an exchange's order API.  It does not even
    hold an authenticated ccxt client.  Even if LIVE_TRADING=true were set,
    the paper trader remains a pure simulation and refuses to place real
    orders.  Live trade placement would live in a separate, explicitly
    instrumented module guarded by LIVE_TRADING.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from src.config import Config
from src.logging_config import get_logger
from src.data.downloader import Downloader
from src.features.indicators import add_indicators, FeatureColumns as FC
from src.ml.dataset import feature_columns
from src.risk.risk_manager import PositionPlan, RiskManager
from src.strategy.signal import generate_signal

logger = get_logger("paper.trader")


@dataclass
class PaperPosition:
    """A virtual open long position."""

    entry_time: datetime
    entry_price: float
    position_size: float
    stop_price: float
    target_price: float
    risk_distance: float


@dataclass
class PaperStats:
    """Summary of a paper trading session."""

    initial_capital: float
    final_capital: float
    total_return: float
    num_trades: int
    win_rate: float
    total_fees: float
    trades_log_path: Path
    predictions_log_path: Path


class PaperTrader:
    """Runs the live pipeline in simulation mode.

    Pipeline:
        Live market data → feature engine → XGBoost → signal engine
        → risk manager → virtual trade.
    """

    def __init__(
        self,
        config: Config,
        lookback: int = 500,
    ) -> None:
        self.cfg = config
        self.lookback = max(lookback, 220)  # needs ema200 warmup

        self.cash: float = float(config.trading.initial_capital)
        self.position: PaperPosition | None = None
        self.trades: list[dict] = []
        self.predictions: list[dict] = []

        # Risk layer shared with backtest (exactly the same invariants).
        self.risk = RiskManager(config, capital=self.cash)

        # Live-order safety: the paper trader has no live order client and
        # records that zero real orders were ever attempted.
        self._live_order_client = None
        self._live_orders_placed = 0

        # Test injection hook.
        self._injected_df: pd.DataFrame | None = None

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #

    def run(self) -> PaperStats:
        """Execute one paper-trading pass over recent market data."""
        if self._injected_df is not None:
            df = self._injected_df
        else:
            downloader = Downloader(self.cfg)
            raw = downloader.fetch_ohlcv()
            downloader.validate(raw)
            df = add_indicators(raw)

        model = self._load_model()

        # Keep only the most recent `lookback` candles (after warmup).
        if len(df) > self.lookback:
            df = df.tail(self.lookback).reset_index(drop=True)

        feature_cols = feature_columns()
        missing = [c for c in feature_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing feature columns in paper data: {missing}")

        for idx in range(len(df)):
            row = df.iloc[idx]
            ts = row["timestamp"]
            day = pd.to_datetime(ts).date()
            self.risk.on_new_day(day)

            candle_open = float(row["open"])
            candle_high = float(row["high"])
            candle_low = float(row["low"])
            candle_close = float(row["close"])

            prob = self._predict(row, feature_cols, model)

            # Signal computed once per candle for both entry and audit log.
            current_signal = None

            # ---- exit check ------------------------------------------
            if self.position is not None:
                exit_price, reason = None, ""
                if candle_low <= self.position.stop_price:
                    exit_price = self.position.stop_price * (1 - self.cfg.trading.slippage)
                    reason = "stop"
                elif candle_high >= self.position.target_price:
                    exit_price = self.position.target_price * (1 - self.cfg.trading.slippage)
                    reason = "target"
                else:
                    sig = generate_signal(prob, row.to_dict(), self.cfg, has_position=True)
                    current_signal = sig.signal
                    if sig.signal == "EXIT":
                        exit_price = candle_close * (1 - self.cfg.trading.slippage)
                        reason = "signal_exit"
                if exit_price is not None:
                    self._close_virtual(ts, exit_price, reason)

            # ---- entry ------------------------------------------------
            plan = None
            if self.position is None and not self.risk.trading_disabled:
                sig = generate_signal(prob, row.to_dict(), self.cfg, has_position=False)
                current_signal = sig.signal
                atr_val = float(row[FC.ATR]) if pd.notna(row.get(FC.ATR)) else 0.0
                entry_price = candle_open * (1 + self.cfg.trading.slippage)

                self.risk.capital = self.cash
                self.risk.equity_estimate = self.cash
                planned = self.risk.plan_position(
                    entry_price=entry_price, atr=atr_val, signal=sig,
                )
                if isinstance(planned, PositionPlan):
                    self._open_virtual(ts, planned)
                    plan = planned

            # ---- audit log for this candle ---------------------------
            self._log_prediction(row, ts, candle_close, prob, current_signal)

        # ---- final close if still open --------------------------------
        if self.position is not None:
            last_ts = df.iloc[-1]["timestamp"]
            last_close = float(df.iloc[-1]["close"])
            self._close_virtual(last_ts, last_close * (1 - self.cfg.trading.slippage), "end_of_session")

        return self._finalize()

    # ------------------------------------------------------------------ #
    # Virtual trade helpers
    # ------------------------------------------------------------------ #

    def _open_virtual(self, ts: datetime, plan: PositionPlan) -> None:
        self.cash -= plan.entry_cost
        self.risk.open_positions += 1
        self.position = PaperPosition(
            entry_time=ts,
            entry_price=plan.entry_price,
            position_size=plan.position_size,
            stop_price=plan.stop_price,
            target_price=plan.target_price,
            risk_distance=plan.risk_distance,
        )
        logger.info(
            "[PAPER] OPEN  %s size=%.6f entry=%.2f stop=%.2f target=%.2f",
            ts, plan.position_size, plan.entry_price, plan.stop_price, plan.target_price,
        )

    def _close_virtual(self, ts: datetime, exit_price: float, reason: str) -> None:
        pos = self.position
        assert pos is not None

        entry_notional = pos.entry_price * pos.position_size
        exit_notional = exit_price * pos.position_size
        entry_fee = entry_notional * self.cfg.trading.taker_fee
        exit_fee = exit_notional * self.cfg.trading.taker_fee
        pnl = exit_notional - entry_notional - entry_fee - exit_fee

        self.cash += exit_notional - exit_fee
        self.risk.register_trade_result(pnl)
        if self.risk.open_positions > 0:
            self.risk.open_positions -= 1

        self.trades.append(
            {
                "entry_time": str(pos.entry_time),
                "entry_price": round(pos.entry_price, 6),
                "exit_time": str(ts),
                "exit_price": round(exit_price, 6),
                "position_size": round(pos.position_size, 8),
                "fees": round(entry_fee + exit_fee, 6),
                "slippage": 0.0,
                "pnl": round(pnl, 6),
                "exit_reason": reason,
            }
        )
        logger.info(
            "[PAPER] CLOSE %s exit=%.2f reason=%s pnl=%.2f cash=%.2f",
            ts, exit_price, reason, pnl, self.cash,
        )
        self.position = None

    # ------------------------------------------------------------------ #
    # Prediction + structured logging
    # ------------------------------------------------------------------ #

    def _predict(self, row, feature_cols, model) -> float:
        X = row[feature_cols].values.reshape(1, -1)
        return float(model.predict_proba(X)[0, 1])

    def _log_prediction(self, row, ts, price: float, prob: float, signal: str | None = None) -> None:
        """Structured per-candle prediction audit log (spec section 22)."""
        self.predictions.append(
            {
                "timestamp": str(ts),
                "symbol": self.cfg.trading.symbol,
                "price": round(price, 6),
                "model_probability": round(prob, 6),
                "signal": signal,
                "RSI": round(row.get(FC.RSI), 4) if pd.notna(row.get(FC.RSI)) else None,
                "EMA20": round(row.get(FC.EMA20), 4) if pd.notna(row.get(FC.EMA20)) else None,
                "EMA50": round(row.get(FC.EMA50), 4) if pd.notna(row.get(FC.EMA50)) else None,
                "ATR": round(row.get(FC.ATR), 4) if pd.notna(row.get(FC.ATR)) else None,
                "position_size": self.position.position_size if self.position is not None else None,
                "stop_price": self.position.stop_price if self.position is not None else None,
                "target_price": self.position.target_price if self.position is not None else None,
            }
        )

    # ------------------------------------------------------------------ #
    # Finalization / reporting
    # ------------------------------------------------------------------ #

    def _finalize(self) -> PaperStats:
        out_dir = self.cfg.data.processed_data_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        trades_path = out_dir / "paper_trades.csv"
        pd.DataFrame(self.trades).to_csv(trades_path, index=False)
        logger.info("Paper trades -> %s (%d trades)", trades_path, len(self.trades))

        preds_path = out_dir / "paper_predictions.csv"
        pred_cols = [
            "timestamp", "symbol", "price", "model_probability", "signal",
            "RSI", "EMA20", "EMA50", "ATR",
            "position_size", "stop_price", "target_price",
        ]
        pdf = pd.DataFrame(self.predictions, columns=pred_cols)
        pdf.to_csv(preds_path, index=False)
        logger.info("Paper predictions -> %s (%d rows)", preds_path, len(pdf))

        init = self.cfg.trading.initial_capital
        final = self.cash
        wins = sum(1 for t in self.trades if t["pnl"] > 0)

        stats = PaperStats(
            initial_capital=init,
            final_capital=round(final, 2),
            total_return=round((final / init) - 1 if init else 0.0, 6),
            num_trades=len(self.trades),
            win_rate=round(wins / len(self.trades), 4) if self.trades else 0.0,
            total_fees=round(sum(t["fees"] for t in self.trades), 4),
            trades_log_path=trades_path,
            predictions_log_path=preds_path,
        )

        logger.info("=" * 40)
        logger.info("PAPER TRADING SUMMARY")
        logger.info("=" * 40)
        logger.info("Initial Capital: $%.2f", init)
        logger.info("Final   Capital: $%.2f", final)
        logger.info("Total Return:    %.2f%%", stats.total_return * 100)
        logger.info("Trades:          %d", stats.num_trades)
        logger.info("Win Rate:        %.2f%%", stats.win_rate * 100)
        logger.info("Total Fees:      $%.2f", stats.total_fees)
        logger.info("Real orders sent: %d", self._live_orders_placed)
        logger.info("=" * 40)

        return stats

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _load_model(self):
        model_path = self.cfg.data.models_dir / "model.joblib"
        if not model_path.exists():
            raise FileNotFoundError(
                f"No model found at {model_path}. Run `python main.py train` first."
            )
        return joblib.load(model_path)

    def _inject_feature_frame(self, df: pd.DataFrame) -> None:
        """Test-only hook: inject a pre-computed featureframe, bypassing the
        live CCXT download.  Not part of the public trading flow."""
        self._injected_df = df