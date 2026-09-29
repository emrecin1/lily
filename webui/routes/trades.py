"""/trades — sayfalanmis islem gecmisi, giris/cikis tag chip'leri."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from fastapi import APIRouter, Request

from webui.auth import require_login
from webui.freqtrade_client import FreqtradeClient, FreqtradeUnavailable, get_client
from webui.templating import templates
from webui.timeutil import iso_to_local_str, parse_iso

logger = logging.getLogger("webui.routes.trades")

router = APIRouter()

PAGE_SIZE = 25
# Freqtrade'in /trades'i tarih araligi/siralama desteklemiyor -- tek seferde
# genis bir parti cekip (buyume payi birakan bir tavan) siralama/filtre/
# sayfalamayi burada kendimiz yapiyoruz. Islem hacmi bu projenin olcegi icin
# (gunde birkac islem) yillarca bu sinira yaklasmaz bile.
FETCH_LIMIT = 2000


def _normalize_open_trade(t: dict) -> dict:
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
        "quote_currency": t.get("quote_currency") or "USDT",
        "enter_tag": t.get("enter_tag") or "—",
        "open_date": iso_to_local_str(t.get("open_date")),
    }


def _normalize_trade(t: dict) -> dict:
    profit_ratio = t.get("profit_ratio")
    if profit_ratio is None:
        profit_ratio = t.get("close_profit")
    profit_abs = t.get("profit_abs")
    if profit_abs is None:
        profit_abs = t.get("close_profit_abs")
    is_open = bool(t.get("is_open"))
    stake_amount = t.get("stake_amount")
    total_after_sale = (
        stake_amount + profit_abs
        if stake_amount is not None and profit_abs is not None and not is_open
        else None
    )
    return {
        "pair": t.get("pair", "?"),
        "open_date": iso_to_local_str(t.get("open_date")),
        "close_date": iso_to_local_str(t.get("close_date")),
        "open_rate": t.get("open_rate"),
        "close_rate": t.get("close_rate"),
        "amount": t.get("amount"),
        "stake_amount": stake_amount,
        "total_after_sale": total_after_sale,
        "profit_ratio": profit_ratio,
        "profit_abs": profit_abs,
        "quote_currency": t.get("quote_currency") or "USDT",
        "enter_tag": t.get("enter_tag") or "—",
        "exit_reason": ("açık pozisyon" if is_open else (t.get("exit_reason") or "—")),
        "exit_reason_class": "open" if is_open else (t.get("exit_reason") or ""),
        "is_open": is_open,
        # asagida _attach_hold_pnl ile doldurulur (kapali islemler icin)
        "hold_current_rate": None,
        "hold_profit_ratio": None,
        "hold_profit_abs": None,
    }


async def _current_prices(
    client: FreqtradeClient, pairs: set[str], timeframe: str
) -> dict[str, float]:
    """Verilen paritelerin en son (guncel) kapanis fiyati — /pair_candles limit=1."""

    async def fetch_one(pair: str) -> tuple[str, float | None]:
        try:
            data = await client.pair_candles(pair, timeframe, limit=1)
        except FreqtradeUnavailable:
            return pair, None
        cols = data.get("columns") or []
        candle_rows = data.get("data") or []
        if not candle_rows or "close" not in cols:
            return pair, None
        close_idx = cols.index("close")
        return pair, float(candle_rows[-1][close_idx])

    results = await asyncio.gather(*(fetch_one(p) for p in pairs))
    return {pair: price for pair, price in results if price is not None}


async def _attach_hold_pnl(client: FreqtradeClient, rows: list[dict], timeframe: str) -> None:
    """Kapali islemler icin 'satilmasaydi su an ne olurdu' — giris fiyatindan
    su anki fiyata gore hipotetik K/Z (ucret/slippage haric, yaklasik; tek anlik
    goruntu, piyasa hareket ettikce degisir)."""
    pairs = {r["pair"] for r in rows if not r["is_open"] and r.get("open_rate")}
    if not pairs:
        return
    prices = await _current_prices(client, pairs, timeframe)
    for r in rows:
        if r["is_open"]:
            continue
        current = prices.get(r["pair"])
        open_rate = r.get("open_rate")
        stake = r.get("stake_amount")
        if current is None or not open_rate:
            continue
        ratio = current / open_rate - 1
        r["hold_current_rate"] = current
        r["hold_profit_ratio"] = ratio
        r["hold_profit_abs"] = stake * ratio if stake is not None else None


def _local_close_date(t: dict) -> datetime | None:
    dt = parse_iso(t.get("close_date"))
    return dt.astimezone() if dt else None


def _parse_date_param(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


async def _build_trades_context(
    page: int, date_from: str | None = None, date_to: str | None = None
) -> dict:
    page = max(page, 1)
    from_d = _parse_date_param(date_from)
    to_d = _parse_date_param(date_to)

    client = get_client()
    error: str | None = None
    resp: dict | None = None
    open_trades: list[dict] | None = None
    timeframe = "4h"
    try:
        resp, open_trades, cfg = await asyncio.gather(
            client.trades(limit=FETCH_LIMIT, offset=0),
            client.status(),
            client.show_config(),
        )
        timeframe = cfg.get("timeframe", timeframe)
    except FreqtradeUnavailable as exc:
        error = str(exc)
        logger.warning("trades: %s", exc)

    all_trades = (resp or {}).get("trades", [])

    # En yeni kapanan en ustte (aciklarin close_date'i yok -> en sona duser,
    # onlar zaten ayri "Acik Pozisyonlar" tablosunda gosteriliyor).
    all_trades.sort(key=lambda t: t.get("close_date") or "", reverse=True)

    if from_d or to_d:
        filtered = []
        for t in all_trades:
            local_close = _local_close_date(t)
            if local_close is None:
                continue  # tarih filtresi aciksa kapanmamis islemler listelenmez
            d = local_close.date()
            if from_d and d < from_d:
                continue
            if to_d and d > to_d:
                continue
            filtered.append(t)
        all_trades = filtered

    total = len(all_trades)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE
    page_trades = all_trades[offset : offset + PAGE_SIZE]

    rows = [_normalize_trade(t) for t in page_trades]
    open_rows = [_normalize_open_trade(t) for t in (open_trades or [])]

    if not error and rows:
        try:
            await _attach_hold_pnl(client, rows, timeframe)
        except FreqtradeUnavailable as exc:
            logger.warning("trades: hold-pnl alinamadi: %s", exc)

    return {
        "active": "trades",
        "error": error,
        "rows": rows,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "open_rows": open_rows,
        "date_from": date_from or "",
        "date_to": date_to or "",
    }


@router.get("/trades")
async def trades_page(
    request: Request, page: int = 1, date_from: str | None = None, date_to: str | None = None
):
    guard = require_login(request)
    if guard:
        return guard
    ctx = await _build_trades_context(page, date_from, date_to)
    return templates.TemplateResponse(request, "trades.html", ctx)


@router.get("/trades/fragment", include_in_schema=False)
async def trades_fragment(
    request: Request, page: int = 1, date_from: str | None = None, date_to: str | None = None
):
    guard = require_login(request)
    if guard:
        return guard
    ctx = await _build_trades_context(page, date_from, date_to)
    return templates.TemplateResponse(request, "partials/trades_fragment.html", ctx)
