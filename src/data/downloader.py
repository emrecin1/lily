"""Market data downloader using CCXT public endpoints.

Downloads OHLCV candles, validates the data, and persists to SQLite.
No API keys are required for public market data.
"""

import os
from datetime import datetime
from typing import Any

import ccxt
import pandas as pd

from src.config import Config
from src.logging_config import get_logger
from src.data.database import Candle, Database


OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

logger = get_logger("data.downloader")


class DataValidationError(Exception):
    """Raised when fetched market data fails validation."""


class Downloader:
    """Fetch OHLCV data from an exchange via CCXT and persist it."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = get_logger("data.downloader")

        exchange_id = config.trading.exchange
        if exchange_id not in ccxt.exchanges:
            raise ValueError(f"Unknown exchange: {exchange_id}")

        ccxt_params: dict[str, Any] = {"enableRateLimit": True}
        # Public market data does NOT require credentials. Only load API keys
        # from the environment if present; otherwise force public-only mode.
        api_key = os.getenv("EXCHANGE_API_KEY", "") or ""
        api_secret = os.getenv("EXCHANGE_API_SECRET", "") or ""
        if api_key:
            ccxt_params["apiKey"] = api_key
            ccxt_params["secret"] = api_secret
        else:
            ccxt_params["apiKey"] = ""
            ccxt_params["secret"] = ""

        self.exchange = getattr(ccxt, exchange_id)(ccxt_params)
        self.db = Database(config)

    def fetch_ohlcv(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles for the configured symbol/timeframe.

        Uses CCXT's pagination to walk backwards from ``end`` towards ``start``,
        fetching batches of candles at a time to avoid rate limits.

        Args:
            start: Earliest timestamp. Defaults to a reasonable historical point.
            end: Latest timestamp. Defaults to now.

        Returns:
            A validated DataFrame with columns
            timestamp, open, high, low, close, volume.
        """
        symbol = self.config.trading.symbol
        timeframe = self.config.trading.timeframe
        exchange_id = self.config.trading.exchange

        start = start or datetime.fromisoformat(self.config.data.train_start)
        end = end or datetime.utcnow()

        since_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_rows: list[list[Any]] = []

        while since_ms < end_ms:
            try:
                batch = self.exchange.fetch_ohlcv(
                    symbol, timeframe, since=since_ms, limit=1000
                )
            except ccxt.NetworkError as exc:
                raise DataValidationError(
                    f"Network error fetching {symbol}: {exc}"
                ) from exc

            if not batch:
                break

            all_rows.extend(batch)

            last_ts = batch[-1][0]
            if last_ts <= since_ms:
                break  # no progress — avoid infinite loop

            since_ms = last_ts + 1

        if not all_rows:
            raise DataValidationError(
                f"No OHLCV data returned for {symbol} ({timeframe}) on {exchange_id}."
            )

        df = pd.DataFrame(all_rows, columns=OHLCV_COLUMNS)
        df = df.drop_duplicates(subset="timestamp", keep="last")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        return df

    def validate(self, df: pd.DataFrame) -> None:
        """Validate a candle DataFrame. Raises on any problem."""
        required = set(OHLCV_COLUMNS)
        missing = required - set(df.columns)
        if missing:
            raise DataValidationError(
                f"Missing columns: {sorted(missing)}. "
                f"Expected {sorted(required)}, got {sorted(df.columns)}."
            )

        if df.empty:
            raise DataValidationError("DataFrame is empty.")

        # Duplicate timestamps
        dupes = df.duplicated(subset="timestamp").sum()
        if dupes:
            raise DataValidationError(f"{dupes} duplicate timestamps found.")

        # Missing (null) values
        nulls = df.isna().sum()
        null_cols = list(nulls[nulls > 0].index)
        if null_cols:
            raise DataValidationError(f"NaN values in columns: {null_cols}")

        # Timestamp ordering
        if not df["timestamp"].is_monotonic_increasing:
            raise DataValidationError("Timestamps are not monotonically increasing.")

        # OHLC logic
        bad_ohlc = (
            ~(df["high"] >= df["low"])
            | ~(df["high"] >= df["open"])
            | ~(df["high"] >= df["close"])
            | ~(df["low"] <= df["open"])
            | ~(df["low"] <= df["close"])
        )
        if bad_ohlc.any():
            raise DataValidationError(
                f"{int(bad_ohlc.sum())} candles violate OHLC price consistency."
            )

        # Volume >= 0
        neg_vol = (df["volume"] < 0).sum()
        if neg_vol:
            raise DataValidationError(f"{int(neg_vol)} candles have negative volume.")

        # Prices > 0
        nonpositive = (
            (df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()
        )
        if nonpositive:
            raise DataValidationError(f"{int(nonpositive)} candles have non-positive prices.")

    def download(self) -> pd.DataFrame:
        """Fetch, validate, and persist candles to the database.

        Returns:
            The validated DataFrame that was stored.
        """
        self.logger.info(
            "Fetching %s %s from %s",
            self.config.trading.symbol,
            self.config.trading.timeframe,
            self.config.trading.exchange,
        )

        df = self.fetch_ohlcv()
        self.validate(df)
        self.logger.info("Fetched %d candles, validation passed.", len(df))

        self._persist(df)
        self.logger.info("Persisted %d candles to %s", len(df), self.db.db_path)
        return df

    def _persist(self, df: pd.DataFrame) -> None:
        """Insert candles into the database, skipping already-existing ones."""
        with self.db.session() as session:
            for _, row in df.iterrows():
                existing = (
                    session.query(Candle)
                    .filter_by(
                        symbol=self.config.trading.symbol,
                        timeframe=self.config.trading.timeframe,
                        timestamp=row["timestamp"].to_pydatetime(),
                    )
                    .one_or_none()
                )
                if existing is not None:
                    continue
                session.add(
                    Candle(
                        exchange=self.config.trading.exchange,
                        symbol=self.config.trading.symbol,
                        timeframe=self.config.trading.timeframe,
                        timestamp=row["timestamp"].to_pydatetime(),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            session.commit()