"""ai-crypto-bot webui — FreqUI yerine gecen ozel panel. Calistirma:
uvicorn webui.app:app --host 127.0.0.1 --port 8082

Gereken env (.env): DASHBOARD_PASSWORD, DASHBOARD_SESSION_SECRET.
Freqtrade kimlik bilgileri config/config.dry.json'dan okunur (bkz. config.py).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webui import auth
from webui.config import BASE_DIR, get_freqtrade_creds, get_settings
from webui.freqtrade_client import init_client
from webui.routes import events, overview, pairs
from webui.state import poll_connectivity
from webui.ws_bridge import run_ws_bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
logger = logging.getLogger("webui")

_stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # erken dogrulama: DASHBOARD_PASSWORD/SESSION_SECRET yoksa hemen patlasin
    creds = get_freqtrade_creds()
    client = init_client(creds)
    logger.info("Freqtrade API hedefi: %s", creds.base_url)

    poll_task = asyncio.create_task(poll_connectivity(client, _stop_event))
    ws_task = asyncio.create_task(run_ws_bridge(creds, _stop_event))
    try:
        yield
    finally:
        _stop_event.set()
        for t in (poll_task, ws_task):
            t.cancel()
        for t in (poll_task, ws_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await client.aclose()


app = FastAPI(title="ai-crypto-bot webui", lifespan=lifespan, docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(overview.router)
app.include_router(pairs.router)
app.include_router(events.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"status": "ok"}
