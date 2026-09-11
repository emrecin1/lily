"""/overview — bakiye, bugun/hafta/ay PnL, acik islem kartlari, gunluk-kayip pili."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from webui.auth import require_login
from webui.config import get_settings
from webui.freqtrade_client import FreqtradeUnavailable, get_client
from webui.templating import templates

logger = logging.getLogger("webui.routes.overview")

router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/overview", status_code=303)


@router.get("/overview")
async def overview(request: Request):
    guard = require_login(request)
    if guard:
        return guard

    client = get_client()
    settings = get_settings()

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

    # ---- gunluk-kayip kapisi (AiCryptoFreqAIStrategy.confirm_trade_entry ile
    # AYNI mantik: /daily zaten Freqtrade'in trades tablosundan bugunku
    # kapali islemlerin close_profit_abs toplami — stratejinin kendi
    # hesabiyla ayni kaynak). Sabit (daily_loss_pct) stratejiyle elle
    # senkron tutulmali; bkz. webui/config.py yorumu.
    guard = None
    if balance and daily:
        starting_capital = balance.get("starting_capital") or 0.0
        today_pnl = (daily.get("data") or [{}])[0].get("abs_profit", 0.0)
        limit = -abs(settings.daily_loss_pct) * starting_capital
        halted = starting_capital > 0 and today_pnl <= limit
        guard = {
            "halted": halted,
            "today_pnl": today_pnl,
            "limit": limit,
            "pct": settings.daily_loss_pct,
        }

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

    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "active": "overview",
            "connected": error is None,
            "last_error": error,
            "stake_currency": stake_currency,
            "balance": balance,
            "profit": profit,
            "today": _period(daily),
            "week": _period(weekly),
            "month": _period(monthly),
            "guard": guard,
            "open_trades": trades_view,
        },
    )


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
        "open_date": (t.get("open_date") or "")[:16].replace("T", " "),
        "stop_loss_ratio": t.get("stop_loss_ratio"),
    }
