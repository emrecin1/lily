"""Phase 3 tests: feature engineering and no-lookahead safety."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.features.indicators import (
    FeatureColumns as FC,
    add_indicators,
    build_feature_frame,
)


ALL_FEATURES = [
    FC.EMA20, FC.EMA50, FC.EMA100, FC.EMA200,
    FC.CLOSE_EMA20, FC.CLOSE_EMA50, FC.EMA20_EMA50, FC.EMA50_EMA200,
    FC.RSI, FC.MACD, FC.MACD_SIGNAL, FC.MACD_HIST, FC.ROC,
    FC.ATR, FC.VOL_12, FC.VOL_24, FC.VOL_48,
    FC.VOLUME_CHANGE, FC.VOLUME_SMA_RATIO, FC.VOLUME_ZSCORE,
    FC.RET_1, FC.RET_3, FC.RET_6, FC.RET_12, FC.RET_24,
]


def _make_ohlcv(n=300, seed=0) -> pd.DataFrame:
    """Build a monotonically increasing, synthetic OHLCV frame."""
    rng = np.random.default_rng(seed)
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=i) for i in range(n)]
    close = 100.0 + np.cumsum(rng.normal(0, 1.0, n))
    close = np.abs(close) + 10
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 1.0, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 1.0, n))
    volume = np.abs(rng.normal(1000, 200, n))
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.fixture
def df() -> pd.DataFrame:
    return _make_ohlcv()


def test_all_features_present(df):
    out = add_indicators(df)
    for f in ALL_FEATURES:
        assert f in out.columns, f"missing feature column: {f}"


def test_original_columns_preserved(df):
    out = add_indicators(df)
    for col in ["timestamp", "open", "high", "low", "close", "volume"]:
        assert col in out.columns


def test_no_infinite_values(df):
    out = add_indicators(df)
    # Reject only true infinities; NaN is acceptable during warm-up periods.
    inf = np.isinf(out[ALL_FEATURES].values)
    assert not inf.any(), "features contain infinite values"


def test_no_lookahead_future_not_used(df):
    """Critical invariant: each feature value at index i must equal the value
    computed using only data [0..i]. We verify by recomputing a feature on a
    truncated frame and comparing the last row.

    The strongest guarantee: for any split point k, the feature at k computed
    on the full series equals the feature at k computed on the first k+1 rows.
    """
    out_full = add_indicators(df)

    for k in [50, 100, 150, 200, 250]:
        prefix = df.iloc[: k + 1].copy()
        out_prefix = add_indicators(prefix)
        last_full = out_full.iloc[k]
        last_prefix = out_prefix.iloc[k]

        for f in ALL_FEATURES:
            a = last_full[f]
            b = last_prefix[f]
            # Both may be NaN (insufficient history) — accept either equal or
            # both-null; must NOT differ when both are finite.
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(a, b, equal_nan=True), (
                f"feature {f} at index {k} depends on future data "
                f"(full={a!r}, prefix={b!r})"
            )


def test_ema_reference_values(df):
    """EMA should match a manual recursive EMA implementation."""
    close = df["close"].values
    period = 20
    alpha = 2 / (period + 1)
    ema = np.zeros(len(close))
    ema[0] = close[0]
    for i in range(1, len(close)):
        ema[i] = alpha * close[i] + (1 - alpha) * ema[i - 1]

    out = add_indicators(df)
    actual = out[FC.EMA20].values

    # Skip warm-up region
    for i in range(period, len(close)):
        assert np.isclose(actual[i], ema[i], atol=1e-6), f"EMA20 mismatch at {i}"


def test_rsi_range(df):
    out = add_indicators(df)
    rsi = out[FC.RSI].dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_returns_formula(df):
    out = add_indicators(df)
    close = df["close"]
    expected = close.pct_change(1)
    actual = out[FC.RET_1]
    # compare where both finite
    mask = ~(expected.isna() | actual.isna())
    np.testing.assert_allclose(actual[mask], expected[mask], rtol=1e-6)


def test_warmup_nans_expected(df):
    """Long-period indicators should be NaN until enough lookback exists."""
    out = add_indicators(df)
    # EMA200 needs ~200 points of warmup
    assert out[FC.EMA200].iloc[0:5].isna().all()
    # EMA20 should be defined by index 20
    assert out[FC.EMA20].iloc[20:].notna().all()


def test_build_feature_frame_from_empty_db_raises(tmp_path):
    import dataclasses

    from src.config import CONFIG, Config

    cfg = dataclasses.replace(
        CONFIG,
        data=dataclasses.replace(
            CONFIG.data,
            raw_data_dir=tmp_path / "raw",
            processed_data_dir=tmp_path / "processed",
            database_dir=tmp_path / "database",
            database_path=tmp_path / "database" / "bot.db",
            models_dir=tmp_path / "models",
            logs_dir=tmp_path / "logs",
        ),
    )
    with pytest.raises(RuntimeError, match="No candles"):
        build_feature_frame(cfg)