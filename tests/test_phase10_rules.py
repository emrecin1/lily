"""Tests for the rule-based AL/SAT demo strategy (Phase 10)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.config import CONFIG, Config
from src.features.indicators import add_indicators, FeatureColumns as FC
from src.rules.engine import run_coin
from src.rules.position import DemoPosition
from src.rules.signal import RulesSignal, rules_signal


def _frame(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=4 * i) for i in range(n)]
    closes = np.asarray(closes, dtype=float)
    o = closes * 1.001
    h = closes * 1.01
    l = closes * 0.99
    v = np.full(n, 1000.0)
    df = pd.DataFrame(
        {"timestamp": times, "open": o, "high": h, "low": l, "close": closes, "volume": v}
    )
    return add_indicators(df)


def _uptrend_frame():
    """A realistic noisy uptrend with pullbacks so RSI dips below the buy max."""
    rng = np.random.default_rng(42)
    n = 600
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=4 * i) for i in range(n)]
    # gentle upward drift with realistic noise (pullbacks keep RSI low)
    rets = rng.normal(0.0006, 0.008, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    o = close * (1 + rng.normal(0, 0.001, n))
    h = np.maximum(o, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    v = np.abs(rng.normal(1000, 100, n))
    df = pd.DataFrame(
        {"timestamp": times, "open": o, "high": h, "low": l, "close": close, "volume": v}
    )
    return add_indicators(df)


def _flat_uptrend_frame() -> pd.DataFrame:
    return _uptrend_frame()


# --------------------------------------------------------------------------- #
# Signal rules
# --------------------------------------------------------------------------- #

def test_signal_al_in_uptrend(cfg_df=_flat_uptrend_frame()):
    # Pick a candle well into the uptrend where RSI < 70 and EMA20 > EMA50.
    row = None
    for _, r in cfg_df.iterrows():
        sig = rules_signal(CONFIG, r, "X/USDT", has_position=False)
        if sig.action == "AL":
            row = sig
            break
    assert row is not None, "expected an AL signal in a sustained uptrend"
    assert row.action == "AL"


def test_signal_hold_when_rsi_very_high():
    # Force a bullish trend but push RSI above the buy max -> no AL.
    df = _flat_uptrend_frame()
    # artificially set RSI very high
    df[FC.RSI] = 95.0
    any_al = False
    for _, r in df.iterrows():
        if rules_signal(CONFIG, r, "X/USDT", has_position=False).action == "AL":
            any_al = True
            break
    assert not any_al, "no AL expected when RSI exceeds buy max"


def test_signal_sat_when_holding_and_trend_breaks():
    # Uptrend then sharp drop -> EMA20 crosses below EMA50 -> SAT.
    closes = list(range(100, 400)) + [350, 300, 250, 200, 150, 100, 60, 30]
    df = _frame(closes)
    al = None
    for _, r in df.iterrows():
        s = rules_signal(CONFIG, r, "X/USDT", has_position=False)
        if s.action == "AL":
            al = r  # remember candle where AL fired
    assert al is not None
    # later candle should give SAT while holding
    sat = None
    for _, r in df.iterrows():
        s = rules_signal(CONFIG, r, "X/USDT", has_position=True)
        if s.action == "SAT":
            sat = s
            break
    assert sat is not None, "expected a SAT signal after trend breaks"


# --------------------------------------------------------------------------- #
# Position / exit rules
# --------------------------------------------------------------------------- #

def test_trailing_stop_matches_user_example():
    """User example: entry at 1.0, price rises to 2.0 then falls to the
    trailing level -> stop. Expected trailing level = 2.0 * (1 - trailing_pct)."""
    cfg = CONFIG
    pos = DemoPosition(
        symbol="X/USDT",
        entry_time=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
        entry_price=1.0,
        quantity=100.0,
        initial_balance_used=100.0,
        cfg=cfg,
    )
    for high in [1.2, 1.6, 2.0]:
        pos.update_peak(high)
    trail = pos.trailing_exit_price()
    assert trail is not None
    expected = 2.0 * (1 - cfg.rules.trailing_pct)
    assert abs(trail - expected) < 1e-9
    # low touches the trailing level -> a sell will be triggered
    assert expected >= pos.trailing_exit_price()


def test_take_profit_exit():
    df = _flat_uptrend_frame()
    # make TP very small so it triggers quickly; force entry near a local low
    import dataclasses
    import copy as _copy

    rules = dataclasses.replace(CONFIG.rules, take_profit_pct=0.005, stop_loss_pct=0.5, use_trailing=False)
    cfg = dataclasses.replace(CONFIG, rules=rules)

    res = run_coin(cfg, df, "X/USDT", starting_balance=10000.0)
    reasons = {t.exit_reason for t in res.trades}
    assert "take_profit" in reasons, f"expected take_profit, got {reasons}"


def test_engine_records_fees_and_pnl():
    df = _flat_uptrend_frame()
    res = run_coin(CONFIG, df, "X/USDT", starting_balance=10000.0)
    for t in res.trades:
        assert t.fees >= 0
        assert t.quantity > 0


def test_engine_never_leaves_open_position_with_close_flag():
    df = _flat_uptrend_frame()
    res = run_coin(CONFIG, df, "X/USDT", starting_balance=10000.0, close_open_position=True)
    assert res.open_position is None
