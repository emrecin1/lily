"""Phase 9 tests: FastAPI dashboard backend."""

from fastapi.testclient import TestClient

import src.dashboard.app as app_module
from src.dashboard.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_summary_shape():
    r = client.get("/api/summary")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"settings", "model", "backtest", "paper"}
    assert "symbol" in data["settings"]
    assert "live_trading" in data["settings"]
    assert "roc_auc_test" in data["model"]


def test_equity_returns_points():
    r = client.get("/api/equity")
    assert r.status_code == 200
    body = r.json()
    assert "points" in body
    if body["points"]:
        assert "timestamp" in body["points"][0]
        assert "equity" in body["points"][0]


def test_paper_predictions_schema():
    r = client.get("/api/paper/predictions")
    assert r.status_code == 200
    preds = r.json()["predictions"]
    if preds:
        required = [
            "timestamp", "symbol", "price", "model_probability", "signal",
            "RSI", "EMA20", "EMA50", "ATR",
        ]
        for k in required:
            assert k in preds[0]


def test_does_not_require_live_data():
    """The dashboard must never touch the exchange or live trading."""
    assert app_module._paper_lock is not None
    # The backend serves persisted files only; no ccxt import here.
    assert "ccxt" not in dir(app_module)


def test_dashboard_cli_imports():
    """The `dashboard` CLI command must be registered on the click group."""
    from main import cli

    names = {c.name for c in cli.commands.values()}
    assert "dashboard" in names


def test_backtest_run_endpoint():
    """POST /api/backtest/run must return a structured result and never
    touch the exchange (Live trading off by default)."""
    r = client.post("/api/backtest/run")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"num_trades", "win_rate", "total_fees"}


def test_run_endpoints_registered_in_openapi():
    """Both run endpoints must be exposed; the paper one is the only one that
    depends on live (public) data, so we assert its schema (not execution)."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/backtest/run" in paths
    assert "/api/paper/run" in paths
    # WebSocket route exists (not part of OpenAPI, so check app.routes).
    ws_paths = {r.path for r in app.routes if hasattr(r, "path") and "ws" in r.path}
    assert any(p == "/ws/paper" for p in ws_paths)


def test_rules_demo_endpoint():
    """GET /api/rules/demo returns the persisted demo portfolio (or {})."""
    r = client.get("/api/rules/demo")
    assert r.status_code == 200
    data = r.json()
    # It may be empty if never run, otherwise must have expected keys.
    if data:
        assert "starting_balance" in data
        assert "total_return" in data
        assert "coins" in data


def test_rules_demo_run_is_registered():
    """The interactive demo run endpoint must be exposed."""
    schema = client.get("/openapi.json").json()
    assert "/api/rules/demo/run" in schema["paths"]