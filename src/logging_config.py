"""Central logging configuration for the AI Crypto Trading Bot.

Provides structured logging to both stdout (console) and a rotating
file handler in the `logs/` directory.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import CONFIG


def _build_formatter() -> logging.Formatter:
    """Return a structured log formatter."""
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logging(
    name: str = "lily",
    level: int = logging.INFO,
    log_dir: Path | None = None,
) -> logging.Logger:
    """Configure the root logger with console and file handlers.

    Args:
        name: Logger name.
        level: Minimum log level.
        log_dir: Directory for log files. Defaults to CONFIG value.

    Returns:
        The configured logger.
    """
    log_dir = log_dir or CONFIG.data.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup is called multiple times.
    if logger.handlers:
        return logger

    formatter = _build_formatter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger rooted at the configured base logger."""
    return logging.getLogger(f"lily.{name}")