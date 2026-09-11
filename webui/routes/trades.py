"""/trades — sayfalanmis islem gecmisi, giris/cikis tag chip'leri."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from webui.auth import require_login
from webui.freqtrade_client import FreqtradeUnavailable, get_client
from webui.templating import templates

logger = logging.getLogger("webui.routes.trades")

router = APIRouter()

PAGE_SIZE = 25


def _normalize_trade(t: dict) -> dict:
    profit_ratio = t.get("profit_ratio")
    if profit_ratio is None:
        profit_ratio = t.get("close_profit")
    profit_abs = t.get("profit_abs")
    if profit_abs is None:
        profit_abs = t.get("close_profit_abs")
    is_open = bool(t.get("is_open"))
    return {
        "pair": t.get("pair", "?"),
        "open_date": (t.get("open_date") or "")[:16].replace("T", " "),
        "close_date": (t.get("close_date") or "")[:16].replace("T", " ") if t.get("close_date") else "—",
        "open_rate": t.get("open_rate"),
        "close_rate": t.get("close_rate"),
        "amount": t.get("amount"),
        "profit_ratio": profit_ratio,
        "profit_abs": profit_abs,
        "enter_tag": t.get("enter_tag") or "—",
        "exit_reason": ("açık pozisyon" if is_open else (t.get("exit_reason") or "—")),
        "exit_reason_class": "open" if is_open else (t.get("exit_reason") or ""),
        "is_open": is_open,
    }


@router.get("/trades")
async def trades_page(request: Request, page: int = 1):
    guard = require_login(request)
    if guard:
        return guard

    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE

    client = get_client()
    error: str | None = None
    resp: dict | None = None
    try:
        resp = await client.trades(limit=PAGE_SIZE, offset=offset)
    except FreqtradeUnavailable as exc:
        error = str(exc)
        logger.warning("trades: %s", exc)

    rows = [_normalize_trade(t) for t in (resp or {}).get("trades", [])]
    total = (resp or {}).get("total_trades", 0)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    return templates.TemplateResponse(
        request,
        "trades.html",
        {
            "active": "trades",
            "error": error,
            "rows": rows,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )
