"""Phase 6 tests: backtest accounting, entry/exit logic, fee handling."""

import dataclasses
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine, Position, TradeRecord
from src.config import CONFIG, Config


def _cfg(tmp_path: Path, **overrides) -> Config:
    data = dataclasses.replace(
        CONFIG.data,
        raw_data_dir=tmp_path / "raw",
        processed_data_dir=tmp_path / "processed",
        database_dir=tmp_path / "database",
        database_path=tmp_path / "database" / "bot.db",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    trading = CONFIG.trading
    ml = CONFIG.ml

    for k, v in overrides.items():
        if hasattr(trading, k):
            trading = dataclasses.replace(trading, **{k: v})
        elif hasattr(ml, k):
            ml = dataclasses.replace(ml, **{k: v})

    return dataclasses.replace(CONFIG, data=data, trading=trading, ml=ml)


# --------------------------------------------------------------------------- #
# Entry accounting
# --------------------------------------------------------------------------- #

def test_position_sizing_never_exceeds_risk_limit(tmp_path):
    """position_size must be risk_amount / stop_distance, i.e. the risk per
    trade never exceeds max_risk_per_trade."""
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    engine.capital = 10_000.0

    row = pd.Series({"atr": 100.0})
    engine._try_entry(dt.datetime(2024, 1, 1), candle_open=1_000.0, row=row)

    assert engine.position is not None
    # risk realized on a full stop-out must be <= capital * max_risk_per_trade
    pos = engine.position
    stop_distance = 100.0 * cfg.trading.atr_stop_multiplier
    risk = pos.position_size * stop_distance
    assert risk <= 10_000 * cfg.trading.max_risk_per_trade + 1e-6


def test_entry_cash_deduction_equals_notional_plus_fee(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    initial = engine.capital
    row = pd.Series({"atr": 100.0})
    engine._try_entry(dt.datetime(2024, 1, 1), candle_open=1_000.0, row=row)

    pos = engine.position
    notional = pos.entry_price * pos.position_size
    entry_fee = notional * cfg.trading.taker_fee
    expected_cash = initial - notional - entry_fee
    assert engine.capital == pytest.approx(expected_cash, abs=1e-6)


def test_entry_rejected_when_cost_exceeds_capital(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    engine.capital = 1.0  # tiny capital
    capital_before = engine.capital
    row = pd.Series({"atr": 0.0001})
    engine._try_entry(dt.datetime(2024, 1, 1), candle_open=1_000.0, row=row)
    # The affordable-balance cap must keep the entry cost within capital.
    if engine.position is not None:
        cost = engine.position.entry_price * engine.position.position_size * (1 + cfg.trading.taker_fee)
        assert cost <= capital_before + 1e-6


# --------------------------------------------------------------------------- #
# Exit / accounting
# --------------------------------------------------------------------------- #

def _open_position(engine, entry_price=1_000.0, atr=100.0):
    engine._try_entry(dt.datetime(2024, 1, 1), candle_open=entry_price, row=pd.Series({"atr": atr}))
    assert engine.position is not None
    return engine.position


def test_stop_loss_accounting(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    initial = engine.capital
    pos = _open_position(engine)

    exit_price = pos.stop_price
    entry_notional = pos.entry_price * pos.position_size
    exit_notional = exit_price * pos.position_size
    entry_fee = entry_notional * cfg.trading.taker_fee
    exit_fee = exit_notional * cfg.trading.taker_fee
    expected_pnl = exit_notional - entry_notional - entry_fee - exit_fee

    engine._close_position(dt.datetime(2024, 1, 2), exit_price, "stop")

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.pnl == pytest.approx(expected_pnl, abs=1e-6)
    # cash after exit = cash_after_entry + exit_notional - exit_fee
    expected_cash = (
        cfg.trading.initial_capital
        - (pos.entry_price * pos.position_size + entry_fee)
        + exit_notional - exit_fee
    )
    assert engine.capital == pytest.approx(expected_cash, abs=1e-6)


def test_check_exit_stop_trumps_target_within_same_candle(tmp_path):
    """Conservative policy: stop first when both breached in one candle."""
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    pos = _open_position(engine)

    # Craft a candle that breaches both stop AND target.
    candle_open = pos.entry_price
    candle_low = pos.stop_price - 100
    candle_high = pos.target_price + 100

    exit_price, reason = engine._check_exit(candle_open, candle_high, candle_low)
    assert reason == "stop"
    assert exit_price <= pos.stop_price


def test_check_exit_stop_only(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    pos = _open_position(engine)
    exit_price, reason = engine._check_exit(
        pos.entry_price, pos.entry_price, pos.stop_price - 10
    )
    assert reason == "stop"


def test_check_exit_target_only(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    pos = _open_position(engine)
    exit_price, reason = engine._check_exit(
        pos.entry_price, pos.target_price + 10, pos.entry_price
    )
    assert reason == "target"


def test_check_exit_no_breach(tmp_path):
    cfg = _cfg(tmp_path)
    engine = BacktestEngine(cfg)
    pos = _open_position(engine)
    # Candle stays within stop/target boundaries.
    exit_price, reason = engine._check_exit(pos.entry_price, pos.target_price - 10, pos.stop_price + 10)
    assert exit_price is None
    assert reason == ""


# --------------------------------------------------------------------------- #
# Risk limits
# --------------------------------------------------------------------------- #

def test_daily_loss_limit_blocks_new_trades(tmp_path):
    """After the daily loss limit is breached, no new position opens."""
    cfg = _cfg(tmp_path, max_daily_loss=0.01, max_risk_per_trade=0.005)
    engine = BacktestEngine(cfg)
    _open_position(engine)

    # Force a loss larger than the daily limit (1% of initial capital).
    # Close far below entry so the loss exceeds 1% of capital.
    pos = engine.position
    engine._close_position(dt.datetime(2024, 1, 2), pos.entry_price * 0.50, "stop")
    assert engine._trading_disabled is True

    # Attempt a new entry — it must be rejected because disabled.
    engine._try_entry(
        dt.datetime(2024, 1, 3), candle_open=1_000.0, row=pd.Series({"atr": 100.0})
    )
    assert engine.position is None


def test_consecutive_loss_limit_blocks_new_trades(tmp_path):
    """After max consecutive losses, trading is paused."""
    cfg = _cfg(tmp_path, max_consecutive_losses=2, max_daily_loss=0.5)
    engine = BacktestEngine(cfg)

    # Make two losing trades.
    for i in range(2):
        pos = _open_position(engine)
        engine._close_position(
            dt.datetime(2024, 1, 1 + i), pos.stop_price * 0.99, "stop"
        )

    assert engine.consecutive_losses == 2
    assert engine._trading_disabled is True

    # New entry must be rejected.
    engine._try_entry(dt.datetime(2024, 1, 3), candle_open=1_000.0, row=pd.Series({"atr": 100.0}))
    assert engine.position is None


def test_win_resets_consecutive_losses(tmp_path):
    cfg = _cfg(tmp_path, max_consecutive_losses=2, max_daily_loss=0.5)
    engine = BacktestEngine(cfg)

    # One loss
    _open_position(engine)
    engine._close_position(dt.datetime(2024, 1, 1), engine.position.stop_price * 0.99, "stop")
    assert engine.consecutive_losses == 1

    # One win
    _open_position(engine)
    engine._close_position(dt.datetime(2024, 1, 2), engine.position.target_price, "target")
    assert engine.consecutive_losses == 0


# --------------------------------------------------------------------------- #
# Backtest accounting integrity
# --------------------------------------------------------------------------- #

def test_pnl_math_consistent_with_fees():
    """Verify PnL from a close equals the known theoretical PnL."""
    engine = BacktestEngine(_cfg(Path(".")))
    # Manually set position to control numbers precisely.
    size = 10.0
    entry = 100.0
    fee = engine.cfg.trading.taker_fee  # 0.001

    engine.capital = 10_000.0
    engine.position = Position(
        entry_time=dt.datetime(2024, 1, 1),
        entry_price=entry,
        position_size=size,
        stop_price=90.0,
        target_price=120.0,
        risk_distance=10.0,
    )
    # Deduct entry cost the same way _try_entry would.
    entry_notional = entry * size
    entry_fee = entry_notional * fee
    engine.capital -= entry_notional + entry_fee

    engine._close_position(dt.datetime(2024, 1, 2), 120.0, "target")

    # pnl = 1200 - 1000 - 1000*0.001 - 1200*0.001 = 200 - 1 - 1.2 = 197.8
    exit_notional = 120.0 * size
    exit_fee = exit_notional * fee
    expected_pnl = exit_notional - entry_notional - entry_fee - exit_fee
    assert engine.trades[0].pnl == pytest.approx(expected_pnl, abs=1e-6)

    # equity after: initial(10000) - (1000+1) [entry] + (1200-1.2) [exit]
    expected_cash = 10_000.0 - (entry_notional + entry_fee) + (exit_notional - exit_fee)
    assert engine.capital == pytest.approx(expected_cash, abs=1e-6)