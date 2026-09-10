"""Signal service: persists signal results and supports auto-generation.

At its core `generate_all` fetches fresh OHLCV+features for each selected coin
and produces a SignalResultSet (records + accuracy). Results are persisted to
`data/processed/rules_signals.json` so the dashboard can show the latest view
even after server restart.

Auto-generation ("4h kapanışında") is driven by the dashboard lifespan task:
on debug it recomputes immediately; in production the service recomputes when
it detects a new 4h candle close. The detection loop is in this module and
invoked by the FastAPI lifespan.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from src.config import Config
from src.logging_config import get_logger
from src.rules.data import fetch_coin_features
from src.rules.settings import SignalSettings, load_settings, settings_path
from src.rules.signal_engine import SignalResultSet, evaluate_accuracy

logger = get_logger("rules.service")


def signals_path(cfg: Config) -> Path:
    return cfg.data.processed_data_dir / "rules_signals.json"


def generate_all(
    cfg: Config,
    settings: SignalSettings,
    on_new: Callable[[list[SignalResultSet]], None] | None = None,
    fetch=fetch_coin_features,
) -> list[SignalResultSet]:
    """Generate + evaluate signals for every selected coin. Returns results."""
    results: list[SignalResultSet] = []
    for symbol in settings.symbols:
        try:
            df = fetch(cfg, symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch features for %s: %s", symbol, exc)
            results.append(
                SignalResultSet(
                    symbol=symbol,
                    timeframe=settings.timeframe,
                    records=[],
                )
            )
            continue
        result = evaluate_accuracy(
            cfg,
            df,
            symbol,
            horizon=settings.accuracy_horizon,
            min_move_pct=settings.accuracy_min_move_pct,
        )
        results.append(result)
    persist(cfg, results)
    if on_new:
        on_new(results)
    return results


def persist(cfg: Config, results: list[SignalResultSet]) -> Path:
    path = signals_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": str(__import__("datetime").datetime.now().isoformat(timespec="seconds")),
        "settings": load_settings(cfg).to_dict(),
        "coins": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def load_signals(cfg: Config) -> dict:
    path = signals_path(cfg)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _last_close_key(df) -> str | None:
    """The key (timestamp) of the newest candle close in a feature frame."""
    if df is None or df.empty:
        return None
    return str(df["timestamp"].iloc[-1])


def run_auto_loop(
    cfg: Config,
    settings_loader: Callable[[], SignalSettings],
    on_new: Callable[[list[SignalResultSet]], None],
    poll_seconds: float = 60.0,
    debug: bool = True,
    fetch=fetch_coin_features,
    stop_event=None,
) -> None:
    """Blocking loop that regenerates signals when a new 4h candle appears.

    On debug=True it generates once at startup (so the dashboard is populated
    immediately) and then waits for a *new* close timestamp. In production the
    wait is the main behaviour.

    Args:
        cfg: Config.
        settings_loader: returns the current SignalSettings (re-read each tick
            so edits on the settings page take effect automatically).
        on_new: callback invoked with fresh results whenever they change.
        poll_seconds: how often to check for a new candle close.
        debug: if True, generate immediately at startup.
        fetch: dependency-injected fetch (for tests).
        stop_event: optional threading.Event to stop the loop.
    """
    settings = settings_loader()
    if debug:
        try:
            on_new(generate_all(cfg, settings, fetch=fetch))
        except Exception as exc:  # noqa: BLE001
            logger.error("Initial auto-generate failed: %s", exc)

    last_keys: dict[str, str] = {}
    import time

    import pandas as pd

    frames: dict[str, pd.DataFrame] = {}
    for sym in settings.symbols:
        try:
            df = fetch(cfg, sym)
            frames[sym] = df
            k = _last_close_key(df)
            if k:
                last_keys[sym] = k
        except Exception as exc:  # noqa: BLE001
            logger.error("init fetch %s failed: %s", sym, exc)

    while stop_event is None or not stop_event.is_set():
        time.sleep(poll_seconds)
        # re-read settings each tick to pick up coin/param edits
        settings = settings_loader()
        changed = False
        for sym in settings.symbols:
            try:
                if sym not in frames:
                    frames[sym] = fetch(cfg, sym)
                    changed = True
                df = fetch(cfg, sym)
                frames[sym] = df
                k = _last_close_key(df)
                if k and k != last_keys.get(sym):
                    changed = True
                if k:
                    last_keys[sym] = k
            except Exception as exc:  # noqa: BLE001
                logger.error("poll fetch %s failed: %s", sym, exc)
        if changed:
            try:
                on_new(generate_all(cfg, settings, fetch=fetch))
            except Exception as exc:  # noqa: BLE001
                logger.error("auto-regenerate failed: %s", exc)
