"""Basic configuration and logging smoke tests (Phase 1)."""

import logging

import pytest

from src.config import CONFIG, Config


def test_config_default_values() -> None:
    """Verify default configuration values are sensible."""
    assert CONFIG.trading.symbol == "BTC/USDT"
    assert CONFIG.trading.timeframe == "1h"
    assert CONFIG.trading.exchange == "binance"
    assert CONFIG.trading.initial_capital == 10_000
    assert CONFIG.trading.max_risk_per_trade == 0.005
    assert CONFIG.trading.max_daily_loss == 0.015
    assert CONFIG.trading.max_open_positions == 1
    assert CONFIG.trading.ai_threshold == 0.70
    assert CONFIG.trading.atr_stop_multiplier == 1.5
    assert CONFIG.trading.risk_reward_ratio == 2.0
    assert CONFIG.trading.taker_fee == 0.001
    assert CONFIG.trading.slippage == 0.0005
    assert CONFIG.trading.live_trading is False


def test_ml_config_defaults() -> None:
    """Verify ML-related configuration defaults."""
    assert CONFIG.ml.model_type == "xgboost"
    assert CONFIG.ml.target_horizon == 4
    assert CONFIG.ml.target_return == 0.008
    assert CONFIG.ml.n_estimators == 300
    assert CONFIG.ml.max_depth == 4
    assert CONFIG.ml.learning_rate == 0.03


def test_data_directories_exist() -> None:
    """Verify project data directories exist on disk."""
    assert CONFIG.data.raw_data_dir.is_dir()
    assert CONFIG.data.processed_data_dir.is_dir()
    assert CONFIG.data.database_dir.is_dir()
    assert CONFIG.data.models_dir.is_dir()
    assert CONFIG.data.logs_dir.is_dir()


def test_live_trading_default_disabled() -> None:
    """LIVE_TRADING must be disabled by default in V1."""
    assert CONFIG.trading.live_trading is False


def test_config_is_frozen_dataclass() -> None:
    """Config should be an immutable dataclass."""
    with pytest.raises(Exception):
        CONFIG.trading.initial_capital = 99999  # type: ignore[misc]


def test_logging_setup() -> None:
    """Logging setup should not raise and should return a logger."""
    from src.logging_config import setup_logging

    logger = setup_logging(level=logging.DEBUG)
    assert logger is not None
    logger.debug("Smoke test log message - OK.")