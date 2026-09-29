"""/system — bot durumu, FreqAI model bilgisi (identifier + son egitim), loglar."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request, UploadFile

from webui import deploy
from webui.auth import require_login
from webui.config import get_freqai_info, get_settings
from webui.freqtrade_client import FreqtradeUnavailable, get_client
from webui.reload import open_trade_count
from webui.templating import templates
from webui.timeutil import epoch_to_local_str

logger = logging.getLogger("webui.routes.system")

router = APIRouter()


def _relative(epoch: float | None) -> str:
    if epoch is None:
        return "—"
    delta = datetime.now(UTC).timestamp() - epoch
    if delta < 60:
        return "az önce"
    if delta < 3600:
        return f"{int(delta // 60)} dk önce"
    if delta < 86400:
        return f"{int(delta // 3600)} sa önce"
    return f"{int(delta // 86400)} gün önce"


async def _build_system_context(flash: dict | None = None) -> dict:
    client = get_client()
    cfg = sysinfo = logs = None
    error: str | None = None
    try:
        cfg, sysinfo, logs = await asyncio.gather(
            client.show_config(), client.sysinfo(), client.logs(limit=150)
        )
    except FreqtradeUnavailable as exc:
        error = str(exc)
        logger.warning("system: %s", exc)

    freqai = get_freqai_info()
    freqai["last_trained_rel"] = _relative(freqai.get("last_trained"))
    # Yerel saat (bkz. webui/timeutil.py) — Freqtrade/FreqAI dahili olarak UTC
    # kullanir; ham UTC gostermek "az once" ile saat degeri arasinda
    # (UTC+ofset kadar) yaniltici bir tutarsizlik izlenimi veriyordu.
    freqai["last_trained_abs"] = epoch_to_local_str(freqai.get("last_trained"))

    log_rows = []
    if logs and logs.get("logs"):
        for row in reversed(logs["logs"]):  # en yeni en ustte
            # [timestamp_str(UTC), timestamp_ms, logger_name, level, message]
            _ts_utc, ms, logger_name, level, message = (row + [None] * 5)[:5]
            ts_local = epoch_to_local_str(ms / 1000, "%d.%m.%Y %H:%M:%S") if ms else "—"
            log_rows.append(
                {"ts": ts_local, "logger": logger_name, "level": level, "message": message}
            )

    return {
        "active": "system",
        "error": error,
        "cfg": cfg,
        "sysinfo": sysinfo,
        "freqai": freqai,
        "log_rows": log_rows,
        "deploy_enabled": get_settings().live_deploy_enabled,
        "deploy_version": deploy.current_version(),
        "deploy_history": deploy.recent_history(),
        "flash": flash,
    }


@router.get("/system")
async def system_page(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    return templates.TemplateResponse(request, "system.html", await _build_system_context())


@router.post("/system/update", include_in_schema=False)
async def system_update(
    request: Request,
    update_file: UploadFile,
    force_with_open_trades: bool = Form(False),
):
    """Zip yukleyerek kod guncelleme -- SADECE ayri canli dizininde
    anlamlidir (bkz. webui/deploy.py, docs/MIGRATION.md). Acik pozisyon
    kontrolu, webui/reload.py'deki ayni deseni kullanir: acik pozisyon
    varsa force_with_open_trades isaretlenmeden devam edilmez."""
    guard = require_login(request)
    if guard:
        return guard
    if not get_settings().live_deploy_enabled:
        return templates.TemplateResponse(
            request,
            "system.html",
            await _build_system_context(
                flash={"level": "warn", "message": "Güncelleme bu ortamda kapalı (LIVE_DEPLOY_ENABLED)."}
            ),
        )

    try:
        open_count = await open_trade_count()
        if open_count is None:
            flash = {
                "level": "warn",
                "message": "Bot şu an yanıt vermiyor, açık pozisyon durumu bilinmediği "
                "için güncelleme uygulanmadı. Bot'a ulaşılabildiğinde tekrar deneyin.",
            }
        elif open_count > 0 and not force_with_open_trades:
            flash = {
                "level": "warn",
                "message": f"{open_count} açık pozisyon var. Kod güncellemesi süreci "
                "yeniden başlatacağı için riskli olabilir — devam etmek için "
                '"açık pozisyona rağmen uygula" kutusunu işaretleyip tekrar yükleyin.',
            }
        else:
            data = await update_file.read()
            result = deploy.apply_update(data)
            flash = {"level": "ok", "message": result.message}
    except deploy.DeployError as exc:
        flash = {"level": "warn", "message": f"Güncelleme reddedildi: {exc}"}

    return templates.TemplateResponse(
        request, "system.html", await _build_system_context(flash=flash)
    )


@router.post("/system/rollback", include_in_schema=False)
async def system_rollback(request: Request, commit: str = Form(...)):
    guard = require_login(request)
    if guard:
        return guard
    if not get_settings().live_deploy_enabled:
        return templates.TemplateResponse(
            request,
            "system.html",
            await _build_system_context(
                flash={"level": "warn", "message": "Güncelleme bu ortamda kapalı (LIVE_DEPLOY_ENABLED)."}
            ),
        )
    try:
        result = deploy.rollback(commit)
        flash = {"level": "ok", "message": result.message}
    except deploy.DeployError as exc:
        flash = {"level": "warn", "message": f"Geri dönüş başarısız: {exc}"}
    return templates.TemplateResponse(
        request, "system.html", await _build_system_context(flash=flash)
    )
