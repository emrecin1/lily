"""SQLite + SQLAlchemy database layer for the AI Crypto Trading Bot.

Stores candles, predictions, signals, trades, and portfolio snapshots.
"""

from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import Config


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Candle(Base):
    """OHLCV market candle."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class Prediction(Base):
    """Model prediction record."""

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    model_probability = Column(Float, nullable=False)
    signal = Column(String, nullable=False)
    rsi = Column(Float, nullable=True)
    ema20 = Column(Float, nullable=True)
    ema50 = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    position_size = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)


class Signal(Base):
    """Signal engine output record."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    signal = Column(String, nullable=False)
    probability = Column(Float, nullable=True)
    trend_ok = Column(Integer, nullable=True)
    rsi_ok = Column(Integer, nullable=True)
    reason = Column(String, nullable=True)


class Trade(Base):
    """Completed trade record."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_time = Column(DateTime, nullable=False)
    exit_price = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    fees = Column(Float, nullable=False)
    slippage = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    exit_reason = Column(String, nullable=False)


class PortfolioSnapshot(Base):
    """Snapshot of account equity over time."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    equity = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    position = Column(Float, nullable=True)
    open_pnl = Column(Float, nullable=True)


class Database:
    """Thin wrapper around a SQLAlchemy engine/session for SQLite."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.db_path: Path = config.data.database_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine: Engine = create_engine(
            f"sqlite:///{self.db_path.absolute()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def session(self) -> Session:
        """Open a new session."""
        return self._session_factory()

    def close(self) -> None:
        """Dispose the engine and release resources."""
        self.engine.dispose()


def init_db(config: Config) -> Database:
    """Create and return a Database instance."""
    return Database(config)


def export_table(db_path: Path, table_name: str) -> "pandas.DataFrame":
    """Read a table into a pandas DataFrame (test/util helper)."""
    import pandas as pd

    engine = create_engine(f"sqlite:///{db_path.absolute()}")
    return pd.read_sql_table(table_name, engine)