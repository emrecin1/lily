"""/pairs/{pair} — mum grafigi + EMA20/EMA50 + trade isaretleri + FreqAI
`up` olasilik alt-paneli. FreqUI'nin yapisal olarak gosteremedigi sey:
modelin "neden" bu kararı verdiği (bkz. docs/ARCHITECTURE.md).

Henuz canli degil (Faz 3'te SSE ile eklenecek) — sayfa yenileme ile."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from webui.auth import require_login
from webui.freqtrade_client import FreqtradeUnavailable, get_client
from webui.templating import templates

logger = logging.getLogger("webui.routes.pairs")

router = APIRouter()


def _to_epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _row_getter(columns: list[str]):
    idx = {c: i for i, c in enumerate(columns)}

    def get(row: list, name: str, default=None):
        i = idx.get(name)
        if i is None or i >= len(row):
            return default
        v = row[i]
        return default if v is None else v

    return get


def _build_chart_payload(raw: dict, trades: dict, status: list[dict], pair: str) -> dict:
    columns = raw.get("columns", [])
    g = _row_getter(columns)

    candles: list[dict] = []
    ema20: list[dict] = []
    ema50: list[dict] = []
    prob: list[dict] = []

    for row in raw.get("data", []):
        t = _to_epoch(g(row, "date"))
        o, h, low, c = g(row, "open"), g(row, "high"), g(row, "low"), g(row, "close")
        if t is None or None in (o, h, low, c):
            continue
        candles.append({"time": t, "open": o, "high": h, "low": low, "close": c})
        e20, e50, up = g(row, "ema20"), g(row, "ema50"), g(row, "up")
        if e20 is not None:
            ema20.append({"time": t, "value": e20})
        if e50 is not None:
            ema50.append({"time": t, "value": e50})
        if up is not None:
            prob.append({"time": t, "value": up})

    latest = None
    rows = raw.get("data", [])
    if rows:
        last = rows[-1]
        e20, e50 = g(last, "ema20"), g(last, "ema50")
        latest = {
            "date": g(last, "date"),
            "do_predict": g(last, "do_predict", 0),
            "up": g(last, "up"),
            "down": g(last, "down"),
            "ema20": e20,
            "ema50": e50,
            "trend_up": (e20 is not None and e50 is not None and e20 > e50),
        }

    markers: list[dict] = []
    for tr in trades.get("trades", []):
        if tr.get("pair") != pair or tr.get("is_open"):
            continue  # acik olanlar asagida /status'tan geliyor (cift olmasin)
        t_open = _to_epoch(tr.get("open_date"))
        if t_open is not None:
            markers.append(
                {
                    "time": t_open, "position": "belowBar", "color": "#2ecc71",
                    "shape": "arrowUp", "text": tr.get("enter_tag") or "giriş",
                }
            )
        t_close = _to_epoch(tr.get("close_date"))
        if t_close is not None:
            profit = tr.get("profit_ratio")
            win = profit is not None and profit > 0
            markers.append(
                {
                    "time": t_close, "position": "aboveBar",
                    "color": "#2ecc71" if win else "#e5484d", "shape": "arrowDown",
                    "text": tr.get("exit_reason") or "çıkış",
                }
            )
    for tr in status:
        if tr.get("pair") != pair:
            continue
        t_open = _to_epoch(tr.get("open_date"))
        if t_open is not None:
            markers.append(
                {
                    "time": t_open, "position": "belowBar", "color": "#2ecc71",
                    "shape": "arrowUp", "text": (tr.get("enter_tag") or "giriş") + " (açık)",
                }
            )
    markers.sort(key=lambda m: m["time"])

    return {
        "candles": candles, "ema20": ema20, "ema50": ema50, "prob": prob,
        "markers": markers, "latest": latest,
    }


@router.get("/pairs", include_in_schema=False)
async def pairs_index(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    client = get_client()
    try:
        wl = await client.whitelist()
        pairs = wl.get("whitelist", [])
    except FreqtradeUnavailable:
        pairs = []
    return RedirectResponse(url=f"/pairs/{pairs[0]}" if pairs else "/overview")


async def _fetch_chart_data(pair: str) -> tuple[dict, list[str], str, str | None]:
    """Donen: (chart_data (latest dahil), whitelist, timeframe, hata)."""
    client = get_client()
    whitelist: list[str] = []
    timeframe = "4h"
    chart_data = {
        "candles": [], "ema20": [], "ema50": [], "prob": [], "markers": [], "latest": None,
    }
    try:
        wl, cfg = await asyncio.gather(client.whitelist(), client.show_config())
        whitelist = wl.get("whitelist", [])
        timeframe = cfg.get("timeframe", timeframe)

        raw, trades, status = await asyncio.gather(
            client.pair_candles(pair, timeframe, limit=500),
            client.trades(limit=500),
            client.status(),
        )
        chart_data = _build_chart_payload(raw, trades, status, pair)
        return chart_data, whitelist, timeframe, None
    except FreqtradeUnavailable as exc:
        logger.warning("chart_data(%s): %s", pair, exc)
        return chart_data, whitelist, timeframe, str(exc)


@router.get("/pairs/{pair:path}/data.json", include_in_schema=False)
async def pair_chart_data(request: Request, pair: str):
    """Faz 3: static/js/live.js SSE'de ilgili paritede olay gorunce bunu
    cekip lightweight-charts'i yeniden besler (tam veri; artimsal update
    yerine — 4h mumda fark edilmez, cok daha az hata payi)."""
    guard = require_login(request)
    if guard:
        return guard
    chart_data, _whitelist, _tf, error = await _fetch_chart_data(pair)
    if error:
        return JSONResponse({"error": error}, status_code=503)
    return JSONResponse(chart_data)


@router.get("/pairs/{pair:path}")
async def pair_chart(request: Request, pair: str):
    guard = require_login(request)
    if guard:
        return guard

    chart_data, whitelist, timeframe, error = await _fetch_chart_data(pair)
    latest = chart_data.pop("latest", None)

    return templates.TemplateResponse(
        request,
        "pair_chart.html",
        {
            "active": "pairs",
            "pair": pair,
            "whitelist": whitelist,
            "timeframe": timeframe,
            "latest": latest,
            "chart_data_json": json.dumps(chart_data),
            "error": error,
        },
    )
