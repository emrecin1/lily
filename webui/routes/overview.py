"""/overview — bakiye, bugun/hafta/ay PnL, acik islem kartlari, gunluk-kayip pili.

/overview/fragment: ayni icerik, sadece ic HTML (base layout yok) — Faz 3'te
canli guncelleme icin static/js/live.js bunu SSE olaylarinda yeniden cekip
#overview-content'i degistirir."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webui.auth import require_login
from webui.config import get_max_daily_loss_pct
from webui.freqtrade_client import FreqtradeUnavailable, get_client
from webui.templating import templates
from webui.timeutil import daily_reset_info, iso_to_local_str

logger = logging.getLogger("webui.routes.overview")

router = APIRouter()

# /pairs/{pair} grafiginde gosterilen FreqAI "up" sutunuyla ayni kaynak
# (pair_candles). Whitelist'teki TUM pariteler icin paralel cekiliyor — 65
# pariteyi tek anda sorgulamak freqtrade_client.py'deki keepalive yarisini
# tetikleme riskini artirir (bkz. o dosyadaki not), bu yuzden eszamanlilik
# bir semaphore ile sinirlandi.
_TOP_UP_CONCURRENCY = 8


def _last_row_value(raw: dict, column: str):
    columns = raw.get("columns", [])
    rows = raw.get("data", [])
    if not rows or column not in columns:
        return None
    idx = columns.index(column)
    last = rows[-1]
    return last[idx] if idx < len(last) else None


async def _fetch_top_up(client, whitelist: list[str], timeframe: str, top_n: int = 10) -> list[dict]:
    """Whitelist'teki pariteleri P(up) degerine gore buyukten kucuge sirala,
    ilk top_n'i (deger + fiyat ile) dondur. Modeli henuz hazir olmayan
    ("No model ready") pariteler up=None dondurur, elenir."""
    sem = asyncio.Semaphore(_TOP_UP_CONCURRENCY)

    async def _one(pair: str) -> dict | None:
        async with sem:
            try:
                raw = await client.pair_candles(pair, timeframe, limit=2)
            except FreqtradeUnavailable:
                return None
        up = _last_row_value(raw, "up")
        if up is None:
            return None
        return {
            "pair": pair,
            "up": up,
            "price": _last_row_value(raw, "close"),
            "do_predict": _last_row_value(raw, "do_predict") == 1,
        }

    rows = [r for r in await asyncio.gather(*(_one(p) for p in whitelist)) if r is not None]
    rows.sort(key=lambda r: r["up"], reverse=True)
    return rows[:top_n]


@router.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    return RedirectResponse(url="/overview", status_code=303)


async def _build_overview_context() -> dict:
    client = get_client()
    daily_loss_pct = get_max_daily_loss_pct()

    balance = profit = daily = weekly = monthly = open_trades = None
    error: str | None = None
    try:
        balance, profit, daily, weekly, monthly, open_trades = await asyncio.gather(
            client.balance(),
            client.profit(),
            client.daily(1),
            client.weekly(1),
            client.monthly(1),
            client.status(),
        )
    except FreqtradeUnavailable as exc:
        error = str(exc)
        logger.warning("overview: %s", exc)

    # ---- P(up) siralamasi — ana istatistiklerden BAGIMSIZ bir try/except:
    # 65 paritelik bu ek sorgu basarisiz olsa da (ör. gecici ag hatasi) bakiye/
    # PnL kartlari gorunmeye devam etsin.
    top_up: list[dict] = []
    try:
        wl, cfg = await asyncio.gather(client.whitelist(), client.show_config())
        top_up = await _fetch_top_up(client, wl.get("whitelist", []), cfg.get("timeframe", "4h"))
    except FreqtradeUnavailable as exc:
        logger.warning("overview top_up: %s", exc)

    # ---- gunluk-kayip kapisi (AiCryptoFreqAIStrategy.confirm_trade_entry ile
    # AYNI mantik: /daily zaten Freqtrade'in trades tablosundan bugunku
    # kapali islemlerin close_profit_abs toplami — stratejinin kendi
    # hesabiyla ayni kaynak). Esik artik config/config.dry.json'dan (/settings
    # sayfasi buradan yazar) okunuyor — tek dogruluk kaynagi.
    guard = None
    if balance and daily:
        starting_capital = balance.get("starting_capital") or 0.0
        today_pnl = (daily.get("data") or [{}])[0].get("abs_profit", 0.0)
        limit = -abs(daily_loss_pct) * starting_capital
        halted = starting_capital > 0 and today_pnl <= limit
        guard = {
            "halted": halted,
            "today_pnl": today_pnl,
            "limit": limit,
            "pct": daily_loss_pct,
        }
        if halted:
            guard["reset_local"], guard["reset_remaining"] = daily_reset_info()

    def _period(d: dict | None) -> dict:
        if not d or not d.get("data"):
            return {"abs_profit": None, "rel_profit": None, "trade_count": None}
        row = d["data"][0]
        return {
            "abs_profit": row.get("abs_profit"),
            "rel_profit": row.get("rel_profit"),
            "trade_count": row.get("trade_count"),
        }

    stake_currency = (daily or weekly or monthly or {}).get("stake_currency", "USDT")
    trades_view = [_normalize_open_trade(t) for t in (open_trades or [])]

    return {
        "active": "overview",
        "stake_currency": stake_currency,
        "balance": balance,
        "profit": profit,
        "today": _period(daily),
        "week": _period(weekly),
        "month": _period(monthly),
        "guard": guard,
        "open_trades": trades_view,
        "top_up": top_up,
        "error": error,
    }


@router.get("/overview")
async def overview(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    ctx = await _build_overview_context()
    return templates.TemplateResponse(request, "overview.html", ctx)


@router.get("/overview/fragment", include_in_schema=False)
async def overview_fragment(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    ctx = await _build_overview_context()
    return templates.TemplateResponse(request, "partials/overview_fragment.html", ctx)


def _normalize_open_trade(t: dict) -> dict:
    """Freqtrade /status kaydini template'in bekledigi sabit sekle indirger
    (surumler arasi alan adi farkliliklarina karsi savunmaci)."""
    profit_ratio = t.get("current_profit")
    if profit_ratio is None:
        profit_ratio = t.get("profit_ratio")
    return {
        "pair": t.get("pair", "?"),
        "amount": t.get("amount"),
        "stake_amount": t.get("stake_amount"),
        "open_rate": t.get("open_rate"),
        "current_rate": t.get("current_rate"),
        "profit_ratio": profit_ratio,
        "profit_abs": t.get("current_profit_abs", t.get("profit_abs")),
        "enter_tag": t.get("enter_tag") or "—",
        "open_date": iso_to_local_str(t.get("open_date")),
        "stop_loss_ratio": t.get("stop_loss_ratio"),
    }
