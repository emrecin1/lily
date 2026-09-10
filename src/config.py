"""Central configuration for the AI Crypto Trading Bot.

All values are read from environment variables with sensible defaults,
so the application can be configured without modifying source code.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _env_int(key: str, default: int) -> int:
    """Read an integer environment variable with a default value."""
    return int(os.getenv(key, str(default)))


def _env_float(key: str, default: float) -> float:
    """Read a float environment variable with a default value."""
    return float(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    """Read a boolean environment variable with a default value."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(key: str, default: str) -> str:
    """Read a string environment variable with a default value."""
    return os.getenv(key, default)


@dataclass(frozen=True)
class TradingConfig:
    """Core market and trading parameters."""

    symbol: str = field(default_factory=lambda: _env_str("SYMBOL", "BTC/USDT"))
    timeframe: str = field(default_factory=lambda: _env_str("TIMEFRAME", "1h"))
    exchange: str = field(default_factory=lambda: _env_str("EXCHANGE", "binance"))

    initial_capital: float = field(
        default_factory=lambda: _env_float("INITIAL_CAPITAL", 10_000)
    )
    max_risk_per_trade: float = field(
        default_factory=lambda: _env_float("MAX_RISK_PER_TRADE", 0.005)
    )
    max_daily_loss: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_LOSS", 0.015)
    )
    max_open_positions: int = field(
        default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 1)
    )
    max_consecutive_losses: int = field(
        default_factory=lambda: _env_int("MAX_CONSECUTIVE_LOSSES", 3)
    )

    ai_threshold: float = field(
        default_factory=lambda: _env_float("AI_THRESHOLD", 0.70)
    )
    atr_stop_multiplier: float = field(
        default_factory=lambda: _env_float("ATR_STOP_MULTIPLIER", 1.5)
    )
    risk_reward_ratio: float = field(
        default_factory=lambda: _env_float("RISK_REWARD_RATIO", 2.0)
    )

    taker_fee: float = field(default_factory=lambda: _env_float("TAKER_FEE", 0.001))
    slippage: float = field(default_factory=lambda: _env_float("SLIPPAGE", 0.0005))

    rsi_buy_max: float = field(default_factory=lambda: _env_float("RSI_BUY_MAX", 70))

    live_trading: bool = field(
        default_factory=lambda: _env_bool("LIVE_TRADING", False)
    )


@dataclass(frozen=True)
class MLConfig:
    """Model and training configuration."""

    model_type: str = field(default_factory=lambda: _env_str("MODEL_TYPE", "xgboost"))
    target_horizon: int = field(
        default_factory=lambda: _env_int("TARGET_HORIZON", 4)
    )
    target_return: float = field(
        default_factory=lambda: _env_float("TARGET_RETURN", 0.008)
    )

    # XGBoost hyperparameters
    n_estimators: int = field(default_factory=lambda: _env_int("N_ESTIMATORS", 300))
    max_depth: int = field(default_factory=lambda: _env_int("MAX_DEPTH", 4))
    learning_rate: float = field(
        default_factory=lambda: _env_float("LEARNING_RATE", 0.03)
    )
    subsample: float = field(default_factory=lambda: _env_float("SUBSAMPLE", 0.8))
    colsample_bytree: float = field(
        default_factory=lambda: _env_float("COLSAMPLE_BYTREE", 0.8)
    )
    objective: str = field(
        default_factory=lambda: _env_str("OBJECTIVE", "binary:logistic")
    )
    eval_metric: str = field(
        default_factory=lambda: _env_str("EVAL_METRIC", "logloss")
    )
    random_state: int = field(default_factory=lambda: _env_int("RANDOM_STATE", 42))


@dataclass(frozen=True)
class RulesConfig:
    """Rule-based AL/SAT strategy (demo) configuration.

    Drives a deterministic, explainable strategy per coin:

        AL  — EMA20 > EMA50 (uptrend) AND RSI < rsi_buy_max
        SAT — position open AND (EMA20 < EMA50 OR RSI > rsi_sell_max)
              OR stop/take-profit hit.

    Exit rules are percentage based:
        take_profit_pct : close at +X% from entry.
        stop_loss_pct   : hard stop at -X% from entry.
        trailing_pct    : if enabled, trail the exit up as price rises; a
                          position is closed when it falls trailing_pct below
                          the highest price reached since entry (e.g. rose
                          1.0 -> 2.0, then closes at ~1.5 if trailing=0.25).
    """

    symbols: tuple = field(
        default_factory=lambda: tuple(_env_list("RULES_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT"))
    )
    timeframe: str = field(default_factory=lambda: _env_str("RULES_TIMEFRAME", "4h"))
    exchange: str = field(default_factory=lambda: _env_str("RULES_EXCHANGE", "binance"))

    demo_balance: float = field(
        default_factory=lambda: _env_float("DEMO_BALANCE", 10_000)
    )
    allocation_per_coin: float = field(
        default_factory=lambda: _env_float("ALLOCATION_PER_COIN", 0.25)
    )

    # Signal rules
    ema_fast: int = field(default_factory=lambda: _env_int("RULES_EMA_FAST", 20))
    ema_slow: int = field(default_factory=lambda: _env_int("RULES_EMA_SLOW", 50))
    rsi_buy_max: float = field(
        default_factory=lambda: _env_float("RULES_RSI_BUY_MAX", 45)
    )
    rsi_sell_max: float = field(
        default_factory=lambda: _env_float("RULES_RSI_SELL_MAX", 70)
    )

    # Exit rules (%)
    take_profit_pct: float = field(
        default_factory=lambda: _env_float("RULES_TP_PCT", 0.15)
    )
    stop_loss_pct: float = field(
        default_factory=lambda: _env_float("RULES_SL_PCT", 0.08)
    )
    trailing_pct: float = field(
        default_factory=lambda: _env_float("RULES_TRAILING_PCT", 0.20)
    )
    use_trailing: bool = field(
        default_factory=lambda: _env_bool("RULES_USE_TRAILING", True)
    )

    taker_fee: float = field(default_factory=lambda: _env_float("TAKER_FEE", 0.001))
    slippage: float = field(default_factory=lambda: _env_float("SLIPPAGE", 0.0005))


def _env_list(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class DataConfig:
    """Data fetching and storage configuration."""

    raw_data_dir: Path = field(
        default_factory=lambda: BASE_DIR / "data" / "raw"
    )
    processed_data_dir: Path = field(
        default_factory=lambda: BASE_DIR / "data" / "processed"
    )
    database_dir: Path = field(
        default_factory=lambda: BASE_DIR / "data" / "database"
    )
    database_path: Path = field(
        default_factory=lambda: BASE_DIR / "data" / "database" / "bot.db"
    )
    models_dir: Path = field(default_factory=lambda: BASE_DIR / "models")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")

    # Default date range (auto-fallback based on available data)
    train_start: str = field(default_factory=lambda: _env_str("TRAIN_START", "2021-01-01"))
    train_end: str = field(default_factory=lambda: _env_str("TRAIN_END", "2024-12-31"))
    val_start: str = field(default_factory=lambda: _env_str("VAL_START", "2025-01-01"))
    val_end: str = field(default_factory=lambda: _env_str("VAL_END", "2025-12-31"))
    test_start: str = field(default_factory=lambda: _env_str("TEST_START", "2026-01-01"))
    test_end: str = field(default_factory=lambda: _env_str("TEST_END", "2026-12-31"))

    batch_size: int = field(default_factory=lambda: _env_int("BATCH_SIZE", 1000))


@dataclass(frozen=True)
class Config:
    """Aggregate configuration exposed to all modules."""

    trading: TradingConfig = TradingConfig()
    ml: MLConfig = MLConfig()
    data: DataConfig = DataConfig()
    rules: RulesConfig = RulesConfig()


CONFIG = Config()