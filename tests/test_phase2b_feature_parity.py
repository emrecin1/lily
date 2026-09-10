"""Asama 2 regresyon: add_indicators() Freqtrade tarafinda kullanildigi icin
   (bkz. user_data/strategies/AiCryptoFeatureStrategy.py, docs/parity-notes.md)
   asagidaki invariant'lar korunmali."""

import datetime as dt
import importlib

import numpy as np
import pandas as pd

from src.features.indicators import FeatureColumns as FC
from src.features.indicators import add_indicators
from src.ml.dataset import feature_columns


def _make_ohlcv(n=800, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=4 * i) for i in range(n)]
    close = np.abs(100.0 + np.cumsum(rng.normal(0, 1.0, n))) + 10
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 1.0, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 1.0, n))
    volume = np.abs(rng.normal(1000, 200, n)) + 1
    return pd.DataFrame(
        {"timestamp": times, "open": open_, "high": high, "low": low,
         "close": close, "volume": volume}
    )


def test_indicators_module_has_no_src_config_dependency():
    """Strateji .venv-rt icinde import edebilsin diye: bu modul src.config /
    src.logging_config'e (dolayisiyla dotenv'e) baglanmamali."""
    mod = importlib.import_module("src.features.indicators")
    src_imports = {
        v.__name__
        for v in vars(mod).values()
        if getattr(v, "__module__", "").startswith("src.")
    }
    # FeatureColumns ayni modulde tanimli; disaridan src.* sinifi cekilmemis olmali.
    assert not any(name.startswith("src.config") or name.startswith("src.logging")
                   for name in src_imports)


def test_add_indicators_produces_all_25_model_features():
    out = add_indicators(_make_ohlcv())
    missing = set(feature_columns()) - set(out.columns)
    assert not missing, f"eksik feature: {sorted(missing)}"


def test_add_indicators_is_deterministic():
    df = _make_ohlcv()
    a = add_indicators(df)[feature_columns()]
    b = add_indicators(df)[feature_columns()]
    pd.testing.assert_frame_equal(a, b)


def test_add_indicators_no_lookahead():
    """Bir satirin feature'lari, ILERIDEKI satirlar eklendiginde DEGISMEMELI.
    (EMA/RSI/MACD/ATR yalnizca gecmise bakar.)"""
    full = _make_ohlcv(n=800)
    cut = 600
    partial = full.iloc[:cut].copy()

    f_full = add_indicators(full).iloc[:cut][feature_columns()].reset_index(drop=True)
    f_part = add_indicators(partial)[feature_columns()].reset_index(drop=True)

    # Ilk satirlar warmup NaN; ortak non-NaN bolgede bit-ozdes olmali.
    both = f_full.notna() & f_part.notna()
    diff = (f_full[both] - f_part[both]).abs().max().max()
    assert diff < 1e-9, f"lookahead suphesi: max feature farki {diff}"


def test_add_indicators_does_not_mutate_input():
    df = _make_ohlcv()
    before = df.copy()
    add_indicators(df)
    pd.testing.assert_frame_equal(df, before)
