"""Phase 7 tests: standalone RiskManager behavior and invariant enforcement."""

import dataclasses
import datetime as dt
from pathlib import Path

import pytest

from src.config import CONFIG, Config
from src.risk.risk_manager import (
    PositionPlan,
    RiskDecision,
    RiskManager,
)
from src.strategy.signal import SignalResult


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


def _buy_signal(prob=0.9) -> SignalResult:
    return SignalResult(
        signal="BUY", probability=prob, trend_ok=True, rsi_ok=True, reason="test buy"
    )


# --------------------------------------------------------------------------- #
# Position sizing and risk limit
# --------------------------------------------------------------------------- #

def test_risk_per_trade_never_exceeds_limit(tmp_path):
    cfg = _cfg(tmp_path)
    rm = RiskManager(cfg, capital=10_000.0)

    plan = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    assert isinstance(plan, PositionPlan)

    # risk on full stop-out must be <= capital * max_risk_per_trade
    realized = plan.position_size * plan.risk_distance
    assert realized <= 10_000 * cfg.trading.max_risk_per_trade + 1e-9
    assert not rm.requested_risk_about_exceeds(plan)


def test_stop_distance_from_atr():
    rm = RiskManager(_cfg(Path(".")), capital=10_000.0)
    plan = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    stop_distance = 100.0 * _cfg(Path(".")).trading.atr_stop_multiplier
    assert plan.stop_price == pytest.approx(1000.0 - stop_distance)
    assert plan.risk_distance == pytest.approx(stop_distance)


def test_take_profit_from_risk_reward():
    cfg = _cfg(Path("."))
    rm = RiskManager(cfg, capital=10_000.0)
    plan = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    rr = cfg.trading.risk_reward_ratio
    assert plan.target_price == pytest.approx(1000.0 + plan.risk_distance * rr)


def test_entry_fee_included_in_cost():
    cfg = _cfg(Path("."))
    rm = RiskManager(cfg, capital=10_000.0)
    plan = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    assert plan.entry_cost == pytest.approx(plan.notional + plan.entry_fee)
    assert plan.entry_cost <= 10_000.0


def test_entry_rejected_when_cost_exceeds_capital(tmp_path):
    cfg = _cfg(tmp_path, initial_capital=1000.0)
    rm = RiskManager(cfg, capital=1.0)  # tiny
    decision = rm.plan_position(entry_price=1000.0, atr=0.0001, signal=_buy_signal())
    assert isinstance(decision, RiskDecision)
    assert decision.allowed is False


def test_signal_not_buy_rejected(tmp_path):
    rm = RiskManager(_cfg(tmp_path), capital=10_000.0)
    hold = SignalResult("HOLD", 0.9, True, True, "hold")
    decision = rm.plan_position(entry_price=1000.0, atr=100.0, signal=hold)
    assert decision.allowed is False
    assert decision.coin == "ml_signal"


# --------------------------------------------------------------------------- #
# Daily loss protection
# --------------------------------------------------------------------------- #

def test_daily_loss_limit_disables_new_positions(tmp_path):
    cfg = _cfg(tmp_path, max_daily_loss=0.01, max_risk_per_trade=0.005)
    rm = RiskManager(cfg, capital=10_000.0)

    # A single loss > 1% of capital
    rm.register_trade_result(pnl=-200.0)  # -2% of 10k
    assert rm.trading_disabled is True

    decision = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    assert decision.allowed is False
    assert decision.coin == "disabled"


def test_daily_loss_resets_on_new_day(tmp_path):
    cfg = _cfg(tmp_path, max_daily_loss=0.01, max_risk_per_trade=0.005)
    rm = RiskManager(cfg, capital=10_000.0)

    rm.register_trade_result(pnl=-150.0)
    assert rm.trading_disabled is True

    # New day resets daily losses.
    rm.on_new_day(dt.date(2024, 1, 2))
    rm.resume()
    assert rm.trading_disabled is False


def test_small_loss_does_not_disable(tmp_path):
    cfg = _cfg(tmp_path, max_daily_loss=0.01, max_risk_per_trade=0.005)
    rm = RiskManager(cfg, capital=10_000.0)
    rm.register_trade_result(pnl=-30.0)  # -0.3% < 1%
    assert rm.trading_disabled is False


# --------------------------------------------------------------------------- #
# Consecutive loss protection
# --------------------------------------------------------------------------- #

def test_consecutive_loss_pause(tmp_path):
    cfg = _cfg(tmp_path, max_consecutive_losses=2, max_daily_loss=0.5)
    rm = RiskManager(cfg, capital=10_000.0)

    rm.register_trade_result(pnl=-50.0)
    rm.register_trade_result(pnl=-50.0)
    assert rm.consecutive_losses == 2
    assert rm.trading_disabled is True

    decision = rm.plan_position(entry_price=1000.0, atr=100.0, signal=_buy_signal())
    assert decision.allowed is False


def test_win_resets_consecutive_losses(tmp_path):
    cfg = _cfg(tmp_path, max_consecutive_losses=2, max_daily_loss=0.5)
    rm = RiskManager(cfg, capital=10_000.0)

    rm.register_trade_result(pnl=-50.0)
    assert rm.consecutive_losses == 1
    rm.register_trade_result(pnl=+100.0)
    assert rm.consecutive_losses == 0
    assert rm.trading_disabled is False


# --------------------------------------------------------------------------- #
# Sizing caps: available balance & max position size
# --------------------------------------------------------------------------- #

def test_position_size_capped_by_available_balance(tmp_path):
    cfg = _cfg(tmp_path, max_risk_per_trade=0.01)
    rm = RiskManager(cfg, capital=500.0)
    plan = rm.plan_position(entry_price=1000.0, atr=10.0, signal=_buy_signal())
    assert isinstance(plan, PositionPlan)
    # notional + fee must fit inside the 500 capital
    assert plan.entry_cost <= 500.0


def test_position_size_capped_by_max_position_size(tmp_path):
    cfg = _cfg(tmp_path)
    rm = RiskManager(cfg, capital=10_000.0)
    plan = rm.plan_position(
        entry_price=1000.0, atr=10.0, signal=_buy_signal(),
        overrides={"max_position_size": 0.01},
    )
    assert isinstance(plan, PositionPlan)
    assert plan.position_size <= 0.01


def test_max_open_positions_limit(tmp_path):
    cfg = _cfg(tmp_path, max_open_positions=1)
    rm = RiskManager(cfg, capital=10_000.0)
    rm.open_positions = 1
    decision = rm.plan_position(entry_price=1000.0, atr=10.0, signal=_buy_signal())
    assert decision.allowed is False


def test_plan_metadata_reason(tmp_path):
    rm = RiskManager(_cfg(tmp_path), capital=10_000.0)
    plan = rm.plan_position(entry_price=1000.0, atr=10.0, signal=_buy_signal())
    assert "risk=$" in plan.reason
    assert "stop=" in plan.reason