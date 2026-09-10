"""Dataset creation and time-ordered split utilities.

Builds the ML target from feature frames and splits data chronologically
(NOT randomly) into train / validation / test.

The target is defined as: does price rise by at least ``target_return``
over the next ``target_horizon`` candles?

    future_return_4h = close.shift(-4) / close - 1
    target = (future_return_4h >= 0.008).astype(int)

Leakage safety:
    - ``close.shift(-horizon)`` is used, so the last ``horizon`` rows have
      no target (dropped). Features never see the label.
    - Splits are strictly chronological; the validation and test sets are
      never used during training.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from src.config import Config
from src.features.indicators import FeatureColumns as FC
from src.logging_config import get_logger


logger = get_logger("ml.dataset")


# Feature columns used by the model (excludes timestamp, raw OHLCV, and target).
def feature_columns() -> list[str]:
    """Return the ordered list of model feature column names."""
    return [
        FC.EMA20, FC.EMA50, FC.EMA100, FC.EMA200,
        FC.CLOSE_EMA20, FC.CLOSE_EMA50, FC.EMA20_EMA50, FC.EMA50_EMA200,
        FC.RSI, FC.MACD, FC.MACD_SIGNAL, FC.MACD_HIST, FC.ROC,
        FC.ATR, FC.VOL_12, FC.VOL_24, FC.VOL_48,
        FC.VOLUME_CHANGE, FC.VOLUME_SMA_RATIO, FC.VOLUME_ZSCORE,
        FC.RET_1, FC.RET_3, FC.RET_6, FC.RET_12, FC.RET_24,
    ]


def add_target(df: pd.DataFrame, horizon: int, min_return: float) -> pd.DataFrame:
    """Add the binary target column to a feature frame.

    Args:
        df: Feature frame (must contain 'close', sorted by timestamp asc).
        horizon: Number of lookahead candles for the future return.
        min_return: Minimum fractional price increase (e.g. 0.008 = 0.8%).

    Returns:
        A new frame with a binary 'target' column. Rows where the future
        return cannot be computed (the last ``horizon`` rows) have NaN
        targets and MUST be dropped downstream.
    """
    out = df.copy()
    future_return = out["close"].shift(-horizon) / out["close"] - 1
    out["future_return"] = future_return
    out["target"] = (future_return >= min_return).astype("float")
    out.loc[future_return.isna(), "target"] = np.nan
    return out


def drop_unlabelled(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows without a valid target and rows with missing features.

    Returns:
        A copy with only rows that have a defined target and no NaN features.
    """
    if "target" not in df.columns:
        raise ValueError("DataFrame has no 'target' column; run add_target first.")

    feature_cols = feature_columns()
    missing_feats = [c for c in feature_cols if c not in df.columns]
    if missing_feats:
        raise ValueError(f"Missing feature columns: {missing_feats}")

    out = df.copy()
    out = out.dropna(subset=["target"])
    out = out.dropna(subset=feature_cols)
    out = out.sort_values("timestamp").reset_index(drop=True)
    return out


@dataclass(frozen=True)
class DatasetSplits:
    """Chronological partition of a labelled dataset."""

    X_train: pd.DataFrame
    y_train: pd.Series
    X_val: pd.DataFrame
    y_val: pd.Series
    X_test: pd.DataFrame
    y_test: pd.Series
    train_timestamps: pd.Series
    val_timestamps: pd.Series
    test_timestamps: pd.Series

    @property
    def sizes(self) -> tuple[int, int, int]:
        return (len(self.X_train), len(self.X_val), len(self.X_test))


def _build_splits(df: pd.DataFrame, cfg: Config) -> DatasetSplits:
    """Split a labelled, feature-complete frame by timestamp ranges."""
    timestamps = df["timestamp"]
    start_dates: dict[str, datetime | None] = {
        "train": datetime.fromisoformat(cfg.data.train_start),
        "val": datetime.fromisoformat(cfg.data.val_start),
        "test": datetime.fromisoformat(cfg.data.test_start),
    }
    end_dates: dict[str, datetime] = {
        "train": datetime.fromisoformat(cfg.data.train_end),
        "val": datetime.fromisoformat(cfg.data.val_end),
        "test": datetime.fromisoformat(cfg.data.test_end),
    }

    assigned: dict[str, pd.Series] = {}
    for name in ["train", "val", "test"]:
        lo = start_dates[name]
        hi = end_dates[name]
        # Normalize timestamps to tz-naive for comparison.
        ts = pd.to_datetime(timestamps)
        if ts.dt.tz is not None:
            ts = ts.dt.tz_localize(None)
        mask = (ts >= pd.Timestamp(lo)) & (ts <= pd.Timestamp(hi))
        assigned[name] = df.loc[mask.values, :]

    for name in ["train", "val", "test"]:
        if assigned[name].empty:
            logger.warning("Split '%s' has no rows in [%s, %s].",
                           name, start_dates[name], end_dates[name])

    # Columns that must NOT appear as model features (raw OHLCV, metadata, targets).
    drop_cols = [
        "timestamp", "target", "future_return",
        "open", "high", "low", "close", "volume",
    ]

    return DatasetSplits(
        X_train=assigned["train"].drop(columns=drop_cols, errors="ignore"),
        y_train=assigned["train"]["target"].astype(int),
        X_val=assigned["val"].drop(columns=drop_cols, errors="ignore"),
        y_val=assigned["val"]["target"].astype(int),
        X_test=assigned["test"].drop(columns=drop_cols, errors="ignore"),
        y_test=assigned["test"]["target"].astype(int),
        train_timestamps=assigned["train"]["timestamp"],
        val_timestamps=assigned["val"]["timestamp"],
        test_timestamps=assigned["test"]["timestamp"],
    )


def make_dataset(cfg: Config, df: pd.DataFrame | None = None) -> DatasetSplits:
    """Build a leakage-free chronological dataset from a feature frame.

    Args:
        cfg: Application configuration.
        df: Optional feature+target frame. If None, loads from the processed
            features CSV produced by Phase 3.

    Returns:
        Chronological train/val/test splits. Test set is never used in training.
    """
    if df is None:
        processed_csv = cfg.data.processed_data_dir / "features.csv"
        if not processed_csv.exists():
            raise FileNotFoundError(
                f"No features found at {processed_csv}. Run `python main.py "
                "build-features` first."
            )
        df = pd.read_csv(processed_csv, parse_dates=["timestamp"])

    labelled = add_target(df, cfg.ml.target_horizon, cfg.ml.target_return)
    clean = drop_unlabelled(labelled)
    return _build_splits(clean, cfg)