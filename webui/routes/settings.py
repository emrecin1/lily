"""/settings — giris/cikis kurallari, pozisyon buyuklugu, genel ayarlar.

Kaydet -> dosyalar guncellenir -> acik pozisyon yoksa Freqtrade'in resmi
POST /reload_config'i cagrilir (ayni surec, config+strateji yeniden yuklenir,
bkz. webui/reload.py). Acik pozisyon VARSA dosyalar yine guncellenir ama
reload ERTELENIR; sayfada "Şimdi uygula" butonu belirir.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request

from webui import settings_store
from webui.auth import require_login
from webui.reload import try_reload
from webui.templating import templates

router = APIRouter()


def _render_context(flash: dict | None = None) -> dict:
    return {
        "active": "settings",
        "current": settings_store.read_current(),
        "flash": flash,
    }


@router.get("/settings")
async def settings_page(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    return templates.TemplateResponse(request, "settings.html", _render_context())


@router.post("/settings")
async def settings_save(
    request: Request,
    buy_proba_pct: float = Form(...),
    time_stop_candles: int = Form(...),
    time_stop_loss_pct: float = Form(...),
    roi_pct: float = Form(...),
    stoploss_pct: float = Form(...),
    stake_mode: str = Form(...),
    stake_amount: float = Form(1000),
    stake_percent_pct: float = Form(10),
    tradable_balance_ratio_pct: float = Form(...),
    max_open_trades: int = Form(...),
    max_daily_loss_pct_pct: float = Form(...),
):
    guard = require_login(request)
    if guard:
        return guard

    # Formda her oran YUZDE olarak girilir (kullaniciya daha dogal); dosyalara
    # freqtrade'in bekledigi 0-1 kesir olarak yazilir.
    settings_store.apply(
        {
            "buy_proba": buy_proba_pct / 100,
            "time_stop_candles": time_stop_candles,
            "time_stop_loss": -abs(time_stop_loss_pct) / 100,
            "roi": roi_pct / 100,
            "stoploss": -abs(stoploss_pct) / 100,
            "stake_mode": stake_mode,
            "stake_amount": stake_amount,
            "stake_percent": stake_percent_pct / 100,
            "tradable_balance_ratio": tradable_balance_ratio_pct / 100,
            "max_open_trades": max_open_trades,
            "max_daily_loss_pct": max_daily_loss_pct_pct / 100,
        }
    )

    flash = await try_reload()
    return templates.TemplateResponse(request, "settings.html", _render_context(flash))


@router.post("/settings/apply-now", include_in_schema=False)
async def settings_apply_now(request: Request):
    """Acik pozisyon nedeniyle ertelenmis bir reload'u elle tetikler."""
    guard = require_login(request)
    if guard:
        return guard
    flash = await try_reload()
    return templates.TemplateResponse(request, "settings.html", _render_context(flash))
