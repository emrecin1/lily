"""Demo portfolio across the configured coins.

Fetches per-coin features, runs the rule strategy on each, and aggregates
results into a single demo-portfolio view persisted to
data/processed/rules_demo.json for the dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.config import Config
from src.logging_config import get_logger
from src.rules.data import fetch_coin_features, save_features
from src.rules.engine import CoinResult, run_coin

logger = get_logger("rules.demo")


@dataclass
class DemoPortfolio:
    starting_balance: float
    coins: list[CoinResult] = field(default_factory=list)

    def total_return(self) -> float:
        if not self.starting_balance:
            return 0.0
        tot = 0.0
        for c in self.coins:
            tot += c.ending_balance
        return (tot / self.starting_balance) - 1.0

    def total_trades(self) -> int:
        return sum(c.num_trades for c in self.coins)

    def to_dict(self) -> dict:
        return {
            "starting_balance": round(self.starting_balance, 2),
            "total_return": round(self.total_return(), 6),
            "total_trades": self.total_trades(),
            "coins": [c.to_dict() for c in self.coins],
        }


def run_demo(
    cfg: Config,
    injected_frames: dict[str, object] | None = None,
) -> DemoPortfolio:
    """Run the demo strategy across all configured coins.

    Args:
        cfg: application config (uses cfg.rules.*).
        injected_frames: optional {symbol: feature_frame} to bypass live
            fetching (for tests). Frames are NOT copied/saved to disk.
    """
    per_coin_balance = cfg.rules.demo_balance
    portfolio = DemoPortfolio(starting_balance=cfg.rules.demo_balance)

    for symbol in cfg.rules.symbols:
        if injected_frames is not None and symbol in injected_frames:
            df = injected_frames[symbol]
        else:
            df = fetch_coin_features(cfg, symbol)
            save_features(cfg, df, symbol)

        result = run_coin(cfg, df, symbol, starting_balance=per_coin_balance)
        portfolio.coins.append(result)
        logger.info(
            "[%s] done — %d trades, return %.2f%%",
            symbol, result.num_trades, result.total_return * 100,
        )
        save_equity(cfg, result)

    return portfolio


def save_equity(cfg: Config, result: CoinResult) -> Path:
    safe = result.symbol.replace("/", "_")
    path = cfg.data.processed_data_dir / f"rules_equity_{safe}.csv"
    if result.equity_curve:
        import pandas as pd

        pd.DataFrame(result.equity_curve).to_csv(path, index=False)
    return path


def save_demo(cfg: Config, portfolio: DemoPortfolio) -> Path:
    out_dir = cfg.data.processed_data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "rules_demo.json"
    with open(path, "w") as f:
        json.dump(portfolio.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Demo portfolio -> %s", path)
    return path
