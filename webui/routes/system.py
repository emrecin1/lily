"""/system — bot durumu, FreqAI model bilgisi (identifier + son egitim), loglar."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from webui.auth import require_login
from webui.config import get_freqai_info
from webui.freqtrade_client import FreqtradeUnavailable, get_client
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


@router.get("/system")
async def system_page(request: Request):
    guard = require_login(request)
    if guard:
        return guard

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
            ts_local = epoch_to_local_str(ms / 1000, "%Y-%m-%d %H:%M:%S") if ms else "—"
            log_rows.append(
                {"ts": ts_local, "logger": logger_name, "level": level, "message": message}
            )

    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "active": "system",
            "error": error,
            "cfg": cfg,
            "sysinfo": sysinfo,
            "freqai": freqai,
            "log_rows": log_rows,
        },
    )
