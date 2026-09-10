"""Phase 4 tests: dataset creation, target generation, leakage safety."""

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.config import CONFIG, Config
from src.features.indicators import add_indicators, FeatureColumns as FC
from src.ml.dataset import (
    add_target,
    drop_unlabelled,
    feature_columns,
    make_dataset,
)


def _make_features(n=300, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=i) for i in range(n)]
    close = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    close = np.abs(close) + 10
    open_ = close + rng.normal(0, 0.05, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.1, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.1, n))
    volume = np.abs(rng.normal(1000, 100, n))
    df = pd.DataFrame(
        {
            "timestamp": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return add_indicators(df)


def _split_cfg(tmp_path) -> Config:
    """Config with date windows spanning the full synthetic 2021 year."""
    cfg = _make_cfg(tmp_path)
    return dataclasses.replace(
        cfg,
        data=dataclasses.replace(
            cfg.data,
            train_start="2021-01-01", train_end="2021-06-30",
            val_start="2021-07-01", val_end="2021-09-30",
            test_start="2021-10-01", test_end="2021-12-31",
        ),
    )


def _make_cfg(tmp_path) -> Config:
    return dataclasses.replace(
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


def test_target_formula_matches_spec():
    """target = (close.shift(-h)/close - 1 >= min_ret).astype(int), NaN at tail."""
    close = pd.Series([100.0, 105.0, 108.0, 104.0, 120.0, 130.0])
    df = pd.DataFrame({"close": close})
    horizon, min_ret = 2, 0.02
    out = add_target(df, horizon, min_ret)

    # future_return at idx0 = close[2]/close[0]-1 = 108/100-1 = 0.08 >= 0.02 -> 1
    assert out["future_return"].iloc[0] == pytest.approx(0.08)
    assert out["target"].iloc[0] == 1.0

    # idx1: close[3]/close[1]-1 = 104/105-1 = -0.0095 < 0.02 -> 0
    assert out["future_return"].iloc[1] == pytest.approx(104 / 105 - 1)
    assert out["target"].iloc[1] == 0.0

    # last `horizon` rows have NaN target (insufficient future data)
    assert out["target"].iloc[-1] != out["target"].iloc[-1]  # is NaN
    assert out["target"].iloc[-2] != out["target"].iloc[-2]

    # earlier rows are labelled
    assert out["target"].iloc[0] == out["target"].iloc[0]


def test_target_tail_rows_is_nan_exactly_horizon():
    df = pd.DataFrame({"close": pd.Series(np.linspace(100, 200, 50))})
    horizon = 4
    out = add_target(df, horizon, 0.008)
    tail_nan = out["target"].isna().sum()
    assert tail_nan == horizon


def test_drop_unlabelled_removes_tail_and_feature_nans():
    df = _make_features(n=300)
    labelled = add_target(df, 4, 0.008)
    clean = drop_unlabelled(labelled)

    assert (clean["target"].notna()).all()
    assert (clean[feature_columns()].notna().all(axis=1)).all()
    # warmup rows (no ema200 yet) + horizon tail rows are removed
    assert len(clean) < len(df)


def test_make_dataset_chronology_no_overlap(tmp_path, monkeypatch):
    """Splits must be strictly chronological and not overlap."""
    cfg = _split_cfg(tmp_path)
    feats = _make_features(n=9000, seed=7)  # spans well into 2022

    splits = make_dataset(cfg, df=feats)

    # All split timestamps disjoint in time.
    test_ts = splits.test_timestamps.dropna()
    train_ts = splits.train_timestamps.dropna()
    val_ts = splits.val_timestamps.dropna()

    assert len(train_ts) > 0 and len(val_ts) > 0 and len(test_ts) > 0
    assert (train_ts.max() < val_ts.min()), "train and val overlap"
    assert (val_ts.max() < test_ts.min()), "val and test overlap"

    # Input order preserved within each split.
    assert splits.X_train.index.is_monotonic_increasing or len(splits.X_train) == 0


def test_make_dataset_no_shuffle_reproducible(tmp_path, monkeypatch):
    """make_dataset is deterministic (no random shuffle)."""
    cfg = _split_cfg(tmp_path)
    feats = _make_features(n=9000, seed=7)

    s1 = make_dataset(cfg, df=feats)
    s2 = make_dataset(cfg, df=feats)
    pd.testing.assert_frame_equal(s1.X_train, s2.X_train)


def test_feature_columns_exclude_target_and_raw():
    cols = feature_columns()
    assert "target" not in cols
    assert "close" not in cols
    assert "timestamp" not in cols
    assert len(cols) == len(set(cols))


def test_make_dataset_requires_features_file(tmp_path):
    cfg = _make_cfg(tmp_path)  # no features.csv present
    with pytest.raises(FileNotFoundError, match="No features"):
        make_dataset(cfg)


def test_test_observations_never_used_in_training(tmp_path):
    """Strong leakage invariant: no training sample shares a timestamp with
    a test sample, and every training timestamp predates every test one."""
    cfg = _split_cfg(tmp_path)
    feats = _make_features(n=9000, seed=13)
    splits = make_dataset(cfg, df=feats)

    train_ts = set(pd.to_datetime(splits.train_timestamps))
    test_ts = set(pd.to_datetime(splits.test_timestamps))
    val_ts = set(pd.to_datetime(splits.val_timestamps))

    assert not (train_ts & test_ts), "train/test timestamp overlap -> leakage"
    assert not (train_ts & val_ts), "train/val timestamp overlap -> leakage"

    assert max(train_ts) < min(val_ts) < min(test_ts)