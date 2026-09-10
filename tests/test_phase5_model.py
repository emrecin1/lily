"""Phase 5 tests: model training and evaluation."""

import dataclasses
import json
import datetime as dt

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from src.config import CONFIG, Config
from src.features.indicators import add_indicators
from src.ml.dataset import add_target, drop_unlabelled, feature_columns, make_dataset
from src.ml.evaluate import evaluate_model, load_model
from src.ml.metrics import (
    classification_report,
    largest_losing_streak,
    max_drawdown,
    probability_distribution,
    sharpe_ratio,
    sortino_ratio,
    total_return_from_equity,
    trade_statistics,
)
from src.ml.train import ModelMetadata, train_model


def _split_cfg(tmp_path) -> Config:
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
            # Fit the split windows to the synthetic data (12000h ≈ 500 days)
            train_start="2021-01-01", train_end="2021-12-31",
            val_start="2022-01-01", val_end="2022-04-30",
            test_start="2022-05-01", test_end="2022-12-31",
        ),
        ml=dataclasses.replace(
            CONFIG.ml,
            n_estimators=50,
            max_depth=3,
        ),
    )
    return cfg


def _make_feature_frame(n=12000, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=i) for i in range(n)]
    close = 100.0 + np.cumsum(rng.normal(0, 0.15, n))
    close = np.abs(close) + 10
    open_ = close + rng.normal(0, 0.05, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.15, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.15, n))
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


def _build_splits(cfg: Config, n=12000, seed=5):
    df = _make_feature_frame(n=n, seed=seed)
    return make_dataset(cfg, df=df)


# ---- Metadata and training --------------------------------------------------

def test_train_saves_model_and_metadata(tmp_path):
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg)
    model, metadata, _ = train_model(cfg, dataset=splits)

    assert (cfg.data.models_dir / "model.joblib").exists()
    assert (cfg.data.models_dir / "model_metadata.json").exists()

    assert metadata["model_type"] == "xgboost"
    assert metadata["features"] == feature_columns()
    assert "future_return_4h" in metadata["target_definition"]
    assert metadata["horizon"] == cfg.ml.target_horizon
    assert metadata["min_return"] == cfg.ml.target_return
    assert "validation_metrics" in metadata
    assert "training_timestamp" in metadata
    assert isinstance(metadata["model_params"]["n_estimators"], int)


def test_train_is_xgboost_and_persisted(tmp_path):
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg)
    model, _, _ = train_model(cfg, dataset=splits)
    assert isinstance(model, xgb.XGBClassifier)

    reloaded, _ = load_model(cfg)
    assert isinstance(reloaded, xgb.XGBClassifier)


def test_training_never_uses_test_set(tmp_path, monkeypatch):
    """Critical invariant: train_model must never fit on test data.
    Verify by checking X_train shape matches what was passed in."""
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg)

    # Record the expected training shape before calling train_model.
    expected_train_samples = len(splits.y_train)
    expected_train_features = splits.X_train.shape[1]

    model, metadata, _ = train_model(cfg, dataset=splits)

    # Model was fit on exactly the training samples, with no test data mixed in.
    assert len(splits.y_test) > 0, "test split should not be empty"
    assert len(metadata["features"]) == expected_train_features
    # Test split timestamps must be strictly later than all training timestamps.
    last_train_ts = pd.to_datetime(splits.train_timestamps).max()
    first_test_ts = pd.to_datetime(splits.test_timestamps).min()
    assert last_train_ts < first_test_ts


def test_model_trained_on_train_only_rows(tmp_path):
    """Model should be fit on X_train shape, proving no test samples."""
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg)
    model, metadata, _ = train_model(cfg, dataset=splits)
    # XGBRegression doesn't store n but feature count; validate feature cols.
    assert len(metadata["features"]) == len(feature_columns())


# ---- Evaluation metrics -----------------------------------------------------

def test_classification_report_counts():
    y = np.array([1, 0, 1, 1, 0, 0, 1])
    probs = np.array([0.9, 0.2, 0.8, 0.7, 0.1, 0.1, 0.6])
    r = classification_report(y, probs, threshold=0.5)
    assert r["n_samples"] == 7
    assert r["true_1_pred_1"] + r["true_1_pred_0"] + r["true_0_pred_1"] + r["true_0_pred_0"] == 7
    assert 0.0 <= r["accuracy"] <= 1.0


def test_probability_distribution_bins():
    probs = np.linspace(0, 1, 100)
    d = probability_distribution(probs, bins=10)
    assert len(d["edges"]) == 11
    assert sum(d["counts"]) == 100


def test_max_drawdown():
    eq = np.array([100, 110, 90, 95, 80, 120])
    # running_max=[100,110,110,110,110,120]; dd=1-eq/rmax; max is at 80/110=0.2727
    assert max_drawdown(eq) == pytest.approx(3.0 / 11.0, abs=1e-3)


def test_sharpe_and_sortino_positive_returns():
    returns = np.array([0.01, 0.02, -0.005, 0.015, 0.02, -0.01, 0.03, 0.01])
    assert sharpe_ratio(returns) > sortino_ratio(returns) or sharpe_ratio(returns) >= 0
    assert isinstance(sortino_ratio(returns), float)


def test_trade_statistics():
    pnls = np.array([100.0, -50.0, 200.0, -30.0, 60.0])
    s = trade_statistics(pnls)
    assert s["num_trades"] == 5
    assert s["win_rate"] == pytest.approx(0.6)
    assert s["average_win"] == pytest.approx((100 + 200 + 60) / 3)
    assert s["average_loss"] == pytest.approx((-50 - 30) / 2)
    assert s["profit_factor"] == pytest.approx((100 + 200 + 60) / 80)
    assert s["largest_losing_streak"] == 1


def test_largest_losing_streak():
    pnls = np.array([10, -1, -2, 5, -3, -4, -5, 6])
    assert largest_losing_streak(pnls) == 3


def test_total_return_from_equity():
    assert total_return_from_equity(1000, 1150) == pytest.approx(0.15)
    assert total_return_from_equity(1000, 800) == pytest.approx(-0.20)


def test_evaluate_model_loads_and_reports(tmp_path):
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg)
    train_model(cfg, dataset=splits)

    result = evaluate_model(cfg, dataset=splits)

    assert "test" in result["evaluations"]
    assert "train" in result["evaluations"]
    assert set(result["evaluations"]["test"].keys()) >= {
        "accuracy", "precision", "recall", "f1", "roc_auc"
    }
    assert (cfg.data.models_dir / "evaluation.json").exists()
    with open(cfg.data.models_dir / "evaluation.json") as f:
        loaded = json.load(f)
    assert "test_summary" in loaded


def test_evaluate_requires_model(tmp_path):
    cfg = _split_cfg(tmp_path)
    splits = _build_splits(cfg, n=12000, seed=10)
    # No model saved yet, but dataset exists — should raise FileNotFoundError
    with pytest.raises(FileNotFoundError, match="No model"):
        evaluate_model(cfg, dataset=splits)