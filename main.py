"""AI Crypto Trading Bot — Command Line Interface.

V1 scope: scaffolding, data pipeline, feature engineering, ML training,
backtesting, and paper trading. Live trading is disabled.

Usage:
    python main.py download-data
    python main.py build-features
    python main.py train
    python main.py evaluate
    python main.py backtest
    python main.py paper
    python main.py demo
    python main.py signals
    python main.py dashboard
"""

import sys

import click

from src import logging_config
from src.config import CONFIG


@click.group()
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable debug-level logging output.",
)
def cli(verbose: bool) -> None:
    """AI Crypto Trading Bot V1."""
    level = logging_config.logging.DEBUG if verbose else logging_config.logging.INFO
    logging_config.setup_logging(level=level)


@cli.command()
def download_data() -> None:
    """Download OHLCV market data and store it locally (Phase 2)."""
    from src.data.downloader import Downloader

    logger = logging_config.get_logger("cli.download")
    logger.info("Downloading %s %s data from %s",
                CONFIG.trading.symbol, CONFIG.trading.timeframe, CONFIG.trading.exchange)

    downloader = Downloader(CONFIG)
    df = downloader.download()
    logger.info("Download complete: %d candles.", len(df))


@cli.command()
def build_features() -> None:
    """Compute technical indicator features (Phase 3)."""
    from src.features.indicators import build_feature_frame

    logger = logging_config.get_logger("cli.features")
    logger.info("Building features...")

    frame = build_feature_frame(CONFIG)
    logger.info("Feature generation complete: %d rows, %d columns.", *frame.shape)


@cli.command()
def train() -> None:
    """Train the XGBoost model (Phase 5)."""
    from src.ml.train import train_model

    logger = logging_config.get_logger("cli.train")
    logger.info("Training model...")

    model, metadata, _ = train_model(CONFIG)
    logger.info("Training complete. Validation ROC-AUC=%.4f",
                metadata["validation_metrics"].get("roc_auc"))


@cli.command()
def evaluate() -> None:
    """Evaluate the trained model (Phase 5)."""
    from src.ml.evaluate import evaluate_model

    logger = logging_config.get_logger("cli.evaluate")
    logger.info("Evaluating model...")

    evaluate_model(CONFIG)
    logger.info("Evaluation complete.")


@cli.command()
def backtest() -> None:
    """Run a backtest simulation (Phase 6)."""
    from src.backtest.engine import run_backtest

    logger = logging_config.get_logger("cli.backtest")
    logger.info("Running backtest...")

    run_backtest(CONFIG)
    logger.info("Backtest complete.")


@cli.command()
def paper() -> None:
    """Run a paper trading session (Phase 8)."""
    from src.paper.trader import PaperTrader

    logger = logging_config.get_logger("cli.paper")
    logger.info("Starting paper trading session...")

    trader = PaperTrader(CONFIG)
    stats = trader.run()
    logger.info(
        "Paper trading session ended: %d trades, total return %.2f%%.",
        stats.num_trades, stats.total_return * 100,
    )


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev).")
def dashboard(host: str, port: int, reload: bool) -> None:
    """Start the FastAPI web dashboard (Phase 9 UI)."""
    import uvicorn

    logger = logging_config.get_logger("cli.dashboard")
    logger.info("Starting dashboard on http://%s:%d ...", host, port)
    uvicorn.run("src.dashboard.app:app", host=host, port=port, reload=reload)


@cli.command()
def demo() -> None:
    """Run the rule-based AL/SAT demo strategy across configured coins."""
    from src.rules.demo import run_demo, save_demo

    logger = logging_config.get_logger("cli.rules")
    logger.info(
        "Running demo rules strategy on %s (%s)...", CONFIG.rules.symbols, CONFIG.rules.timeframe
    )
    portfolio = run_demo(CONFIG)
    save_demo(CONFIG, portfolio)
    print(f"\n=== DEMO PORTFOLIO ===")
    for c in portfolio.coins:
        print(
            f"  {c.symbol:10s} {c.num_trades:3d} trades | return {c.total_return*100:7.2f}% | "
            f"balance {c.ending_balance:>10.2f}"
        )
    print(f"  TOTAL      return {portfolio.total_return()*100:7.2f}%   trades {portfolio.total_trades()}")
    print("=== END ===")


@cli.command()
def signals() -> None:
    """Generate rule-based AL/SAT signals + accuracy for the selected coins.

    This does NOT trade. It only produces signals over the full recent 4h
    history and reports the historical accuracy (did price rise after each AL?).
    """
    from src.rules.service import generate_all, load_signals
    from src.rules.settings import load_settings

    logger = logging_config.get_logger("cli.signals")
    settings = load_settings(CONFIG)
    logger.info("Generating signals on %s (%s)...", settings.symbols, settings.timeframe)
    generate_all(CONFIG, settings)
    payload = load_signals(CONFIG)
    print(f"\n=== SIGNALS ===")
    for c in payload.get("coins", []):
        acc = c.get("accuracy")
        acc_s = f"{acc*100:.1f}%" if acc is not None else "n/a"
        print(
            f"  {c['symbol']:10s} {c['num_signals']:4d} sinyal ({c['num_al']:3d} AL) | "
            f"doğruluk {acc_s} ({c.get('evaluated', 0)} değerlendirildi)"
        )
    print(f"Üretildi: {payload.get('generated_at')}")
    print("=== END ===")


def main() -> None:
    """Entry point."""
    try:
        cli()
    except Exception as exc:  # pragma: no cover - defensive
        logger = logging_config.get_logger("cli")
        logger.exception("Unhandled error during command execution")
        sys.exit(1)


if __name__ == "__main__":
    main()