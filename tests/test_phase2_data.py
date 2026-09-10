"""Phase 2 tests: data validation and database persistence."""

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect

from src.config import Config
from src.data.database import Candle, Database
from src.data.downloader import DataValidationError, Downloader, OHLCV_COLUMNS
from src.logging_config import setup_logging


def _make_config(tmp_path: Path) -> Config:
    """Build a Config pointing all data dirs into a temp directory."""
    import dataclasses

    from src.config import CONFIG

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


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return _make_config(tmp_path)


@pytest.fixture
def valid_df() -> pd.DataFrame:
    """A well-formed OHLCV frame starting at a fixed epoch."""
    n = 50
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    times = [start + dt.timedelta(hours=i) for i in range(n)]
    close = pd.Series(range(100, 100 + n), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": times,
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_valid_data_has_schema(cfg):
    db = Database(cfg)
    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    assert {"candles", "predictions", "signals", "trades", "portfolio_snapshots"} <= tables


def test_candle_roundtrip(cfg, valid_df):
    db = Database(cfg)
    with db.session() as session:
        for _, row in valid_df.iterrows():
            session.add(
                Candle(
                    exchange="binance",
                    symbol="BTC/USDT",
                    timeframe="1h",
                    timestamp=row["timestamp"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                )
            )
        session.commit()

    with db.session() as session:
        count = session.query(Candle).count()
    assert count == len(valid_df)


def test_unique_constraint_prevents_duplicates(cfg, valid_df):
    db = Database(cfg)
    with db.session() as session:
        for _, row in valid_df.iterrows():
            session.add(
                Candle(
                    exchange="binance", symbol="BTC/USDT", timeframe="1h",
                    timestamp=row["timestamp"], open=row["open"], high=row["high"],
                    low=row["low"], close=row["close"], volume=row["volume"],
                )
            )
        session.commit()

    # Insert a duplicate -> should raise IntegrityError
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db.session() as session:
            r = valid_df.iloc[0]
            session.add(
                Candle(
                    exchange="binance", symbol="BTC/USDT", timeframe="1h",
                    timestamp=r["timestamp"], open=r["open"], high=r["high"],
                    low=r["low"], close=r["close"], volume=r["volume"],
                )
            )
            session.commit()


# ---- Validation tests -------------------------------------------------------

def test_validate_accepts_good_df(cfg, valid_df):
    Downloader(cfg).validate(valid_df)  # should not raise


def test_validate_rejects_missing_columns(cfg, valid_df):
    bad = valid_df.drop(columns=["volume"])
    with pytest.raises(DataValidationError, match="Missing columns"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_duplicate_timestamps(cfg, valid_df):
    bad = valid_df.copy()
    bad.loc[10, "timestamp"] = bad.loc[0, "timestamp"]
    with pytest.raises(DataValidationError, match="duplicate"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_nan(cfg, valid_df):
    bad = valid_df.copy()
    bad.loc[5, "close"] = float("nan")
    with pytest.raises(DataValidationError, match="NaN"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_unsorted_timestamps(cfg, valid_df):
    bad = valid_df.copy()
    bad["timestamp"] = bad["timestamp"].iloc[::-1].values
    with pytest.raises(DataValidationError, match="monotonically"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_bad_ohlc(cfg, valid_df):
    bad = valid_df.copy()
    # high < low
    bad.loc[3, "high"] = bad.loc[3, "low"] - 5
    with pytest.raises(DataValidationError, match="OHLC"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_negative_volume(cfg, valid_df):
    bad = valid_df.copy()
    bad.loc[3, "volume"] = -1.0
    with pytest.raises(DataValidationError, match="negative volume"):
        Downloader(cfg).validate(bad)


def test_validate_rejects_nonpositive_price(cfg, valid_df):
    bad = valid_df.copy()
    # Set an entire row to a small negative price, keeping OHLC internally consistent
    bad.loc[3, ["open", "high", "low", "close"]] = -5.0
    with pytest.raises(DataValidationError, match="non-positive"):
        Downloader(cfg).validate(bad)


# ---- fetch pagination logic -------------------------------------------------

def test_fetch_ohlcv_deduplicates(tmp_path, monkeypatch):
    """fetch_ohlcv drops duplicate timestamps from consecutive batches."""
    cfg = _make_config(tmp_path)
    dl = Downloader(cfg)

    class FakeExchange:
        def __init__(self):
            self.calls = 0

        def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
            self.calls += 1
            # Return a batch that overlaps with the previous since by one row.
            granularity_ms = 3600 * 1000
            rows = []
            for i in range(5):
                ts = since + i * granularity_ms
                rows.append([ts, 100.0, 101.0, 99.0, 100.5, 10.0])
            # force progress stop after two calls
            if self.calls >= 2:
                return rows
            return rows

    monkeypatch.setattr(dl, "exchange", FakeExchange())

    import datetime as _dt

    start = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)
    end = _dt.datetime(2024, 1, 1, 6, tzinfo=_dt.timezone.utc)
    df = dl.fetch_ohlcv(start, end)

    # Duplicates removed => each timestamp appears once.
    assert df["timestamp"].is_unique
    assert df.shape[1] == len(OHLCV_COLUMNS)