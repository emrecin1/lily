"""FastAPI dashboard backend for the AI Crypto Trading Bot.

Read-only API that serves the outputs produced by the CLI pipeline
(equity curve, trades, paper predictions, model evaluation, settings)
plus a WebSocket endpoint that reports paper-trading session state.

This backend is **read-only with respect to the exchange**: it never
fetches live data or places orders itself.  It reads persisted CSVs/JSON
written by ``main.py`` commands, and exposes a single POST endpoint to
trigger a paper-trading run (which itself, by design, never sends real
orders).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Event, Thread

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.config import CONFIG
from src.paper.trader import PaperTrader
from src.rules import service as rules_service
from src.rules.settings import load_settings, save_settings

_signal_connections: list[WebSocket] = []
_signal_lock = Lock()
_auto_stop = Event()


def _broadcast_signal(payload: dict) -> None:
    """Send a payload to every connected /ws/signals client (best-effort)."""
    stale = []
    import asyncio

    for ws in list(_signal_connections):
        try:
            asyncio.run(ws.send_json(payload))
        except Exception:  # noqa: BLE001
            stale.append(ws)
    for ws in stale:
        if ws in _signal_connections:
            _signal_connections.remove(ws)


def _on_new_signals(results) -> None:
    """Persisted by generate_all; broadcast to connected clients."""
    payload = {"type": "signals_updated", "time": rules_service.load_signals(CONFIG).get("generated_at")}
    _broadcast_signal(payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the auto signal-generation loop (regenerates on new 4h close)."""
    def _settings_loader():
        return load_settings(CONFIG)

    thread = Thread(
        target=rules_service.run_auto_loop,
        kwargs={
            "cfg": CONFIG,
            "settings_loader": _settings_loader,
            "on_new": _on_new_signals,
            "poll_seconds": 60.0,
            "debug": True,  # populate dashboard immediately at startup
            "stop_event": _auto_stop,
        },
        daemon=True,
        name="signal-auto-loop",
    )
    thread.start()
    try:
        yield
    finally:
        _auto_stop.set()
        thread.join(timeout=3.0)


app = FastAPI(title="AI Crypto Trading Bot", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only; tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_processed = CONFIG.data.processed_data_dir
_models = CONFIG.data.models_dir
_paper_lock = Lock()
_connections: list[WebSocket] = []


def _read_csv(name: str) -> pd.DataFrame:
    path = _processed / name
    if not path.exists():
        return pd.DataFrame()
    # A file with only whitespace/newlines (e.g. a header-less empty export)
    # should be treated as empty to avoid EmptyDataError.
    if path.stat().st_size == 0 or not path.read_text().strip():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(name: str) -> dict:
    """Read a JSON file from the models dir (empty dict if missing)."""
    return _load_json_file(_models / name)


def _read_processed_json(name: str) -> dict:
    """Read a JSON file from the processed dir (empty dict if missing)."""
    return _load_json_file(_processed / name)


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    if df.empty:
        return []
    data = df.replace({float("nan"): None})
    data = data.to_dict(orient="records")
    if limit is not None:
        data = data[-limit:]
    return data


# --------------------------------------------------------------------------- #
# REST endpoints
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/summary")
def summary() -> dict:
    """High-level dashboard summary pulled from persisted outputs."""
    std = CONFIG.trading
    ev = _read_json("evaluation.json")
    test = ev.get("test_summary", {})
    trades = _read_csv("trades.csv")
    paper_trades = _read_csv("paper_trades.csv")
    equity = _read_csv("equity_curve.csv")

    by_reason = trades["exit_reason"].value_counts().to_dict() if not trades.empty else {}

    return {
        "settings": {
            "symbol": std.symbol,
            "timeframe": std.timeframe,
            "exchange": std.exchange,
            "initial_capital": std.initial_capital,
            "live_trading": std.live_trading,
            "ai_threshold": std.ai_threshold,
            "max_risk_per_trade": std.max_risk_per_trade,
            "max_daily_loss": std.max_daily_loss,
        },
        "model": {
            "roc_auc_test": test.get("roc_auc"),
            "accuracy": test.get("accuracy"),
            "n_samples": test.get("n_samples"),
        },
        "backtest": {
            "num_trades": len(trades),
            "win_rate": round((trades["pnl"] > 0).mean(), 4) if not trades.empty else 0.0,
            "total_fees": round(float(trades["fees"].sum()), 2) if not trades.empty else 0.0,
            "exit_reasons": by_reason,
            "last_equity": float(equity["equity"].iloc[-1]) if not equity.empty else None,
        },
        "paper": {
            "num_trades": len(paper_trades),
            "init_capital": std.initial_capital,
        },
    }


@app.get("/api/equity")
def equity() -> dict:
    df = _read_csv("equity_curve.csv")
    return {"points": _records(df, limit=10_000)}


@app.get("/api/backtest/trades")
def backtest_trades() -> dict:
    df = _read_csv("trades.csv")
    return {"trades": _records(df)}


@app.get("/api/paper/predictions")
def paper_predictions() -> dict:
    df = _read_csv("paper_predictions.csv")
    return {"predictions": _records(df, limit=5_000)}


@app.get("/api/paper/trades")
def paper_trades() -> dict:
    df = _read_csv("paper_trades.csv")
    return {"trades": _records(df)}


@app.get("/api/evaluation")
def evaluation() -> dict:
    return _read_json("evaluation.json")


@app.post("/api/paper/run")
def paper_run() -> dict:
    """Trigger one paper-trading session over recent public market data.

    Safe by construction: ``PaperTrader`` has no ability to place real orders.
    """
    with _paper_lock:
        trader = PaperTrader(CONFIG)
        stats = trader.run()
    return {
        "num_trades": stats.num_trades,
        "total_return": stats.total_return,
        "win_rate": stats.win_rate,
        "total_fees": stats.total_fees,
        "real_orders_sent": trader._live_orders_placed,
    }


@app.post("/api/backtest/run")
def backtest_run() -> dict:
    """Trigger a backtest over the persisted feature set.

    Re-runs the same pipeline as ``python main.py backtest`` so the dashboard
    GET endpoints immediately reflect fresh results.
    """
    from src.backtest.engine import run_backtest

    with _paper_lock:
        run_backtest(CONFIG)
    trades = _read_csv("trades.csv")
    return {
        "num_trades": len(trades),
        "win_rate": round((trades["pnl"] > 0).mean(), 4) if not trades.empty else 0.0,
        "total_fees": round(float(trades["fees"].sum()), 2) if not trades.empty else 0.0,
    }


# --------------------------------------------------------------------------- #
# Rule-based demo strategy (Phase 10)
# --------------------------------------------------------------------------- #

@app.get("/api/rules/demo")
def rules_demo() -> dict:
    """Return the persisted rule-based demo portfolio (empty if not run yet)."""
    return _read_processed_json("rules_demo.json")


@app.post("/api/rules/demo/run")
def rules_demo_run() -> dict:
    """Run the rule-based AL/SAT demo across the configured coins.

    Fetches live (public) 4h data, computes signals and simulates the demo
    portfolio. Never sends real orders.
    """
    from src.rules.demo import run_demo, save_demo

    with _paper_lock:
        portfolio = run_demo(CONFIG)
        save_demo(CONFIG, portfolio)
    return {
        "starting_balance": portfolio.starting_balance,
        "total_return": portfolio.total_return(),
        "total_trades": portfolio.total_trades(),
        "num_coins": len(portfolio.coins),
    }


# --------------------------------------------------------------------------- #
# Rule-based signal system (settings + auto signals + accuracy)
# --------------------------------------------------------------------------- #

@app.get("/api/settings")
def get_settings() -> dict:
    """Return the editable signal-system settings (coins + rule params)."""
    return load_settings(CONFIG).to_dict()


@app.put("/api/settings")
def put_settings(payload: dict) -> dict:
    """Persist new signal-system settings (coin selection + rule params)."""
    with _signal_lock:
        current = load_settings(CONFIG)
        symbols = [s for s in payload.get("symbols", current.symbols) if s]
        if not symbols:
            raise ValueError("En az bir coin seçilmelidir")
        from src.rules.settings import SignalSettings

        updated = SignalSettings(
            symbols=symbols,
            timeframe=payload.get("timeframe", current.timeframe),
            ema_fast=int(payload.get("ema_fast", current.ema_fast)),
            ema_slow=int(payload.get("ema_slow", current.ema_slow)),
            rsi_buy_max=float(payload.get("rsi_buy_max", current.rsi_buy_max)),
            rsi_sell_max=float(payload.get("rsi_sell_max", current.rsi_sell_max)),
            accuracy_horizon=int(payload.get("accuracy_horizon", current.accuracy_horizon)),
            accuracy_min_move_pct=float(
                payload.get("accuracy_min_move_pct", current.accuracy_min_move_pct)
            ),
        )
        save_settings(CONFIG, updated)
    return updated.to_dict()


@app.get("/api/signals")
def get_signals() -> dict:
    """Return the latest persisted signal results (records + accuracy per coin)."""
    return rules_service.load_signals(CONFIG)


@app.post("/api/signals/run")
def run_signals_now() -> dict:
    """Manually regenerate signals across all selected coins right now."""
    with _signal_lock:
        settings = load_settings(CONFIG)
        results = rules_service.generate_all(CONFIG, settings, on_new=_on_new_signals)
    return {
        "coins": [r.symbol for r in results],
        "total_signals": sum(len(r.records) for r in results),
        "total_al": sum(len(r.al_signals()) for r in results),
        "time": rules_service.load_signals(CONFIG).get("generated_at"),
    }


# --------------------------------------------------------------------------- #
# WebSocket (live-ish paper state)
# --------------------------------------------------------------------------- #

@app.websocket("/ws/paper")
async def ws_paper(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.append(websocket)
    try:
        # Send a snapshot of the current paper state on connect.
        await websocket.send_json(
            {"type": "paper_state", "trades": _records(_read_csv("paper_trades.csv"))}
        )
        while True:
            _ = await websocket.receive_text()  # keepalive / ignore client msgs
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _connections:
            _connections.remove(websocket)


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket) -> None:
    """Push signal updates to the dashboard when auto-generation runs."""
    await websocket.accept()
    _signal_connections.append(websocket)
    try:
        # Send current snapshot on connect.
        await websocket.send_json(
            {"type": "signals_snapshot", "data": rules_service.load_signals(CONFIG)}
        )
        while True:
            _ = await websocket.receive_text()  # keepalive
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _signal_connections:
            _signal_connections.remove(websocket)
