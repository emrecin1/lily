"""GET /events — BFF'nin ws_bridge'den topladigi olaylari tarayiciya Server-
Sent Events ile dagitir. Cift yonlu gerek yok (panel salt-okunur); EventSource
tarayicida otomatik reconnect eder."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from webui.auth import require_login
from webui.state import state

router = APIRouter()


@router.get("/events")
async def events(request: Request):
    guard = require_login(request)
    if guard:
        return guard

    async def gen():
        q = state.new_subscriber()
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(ev)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.remove_subscriber(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
