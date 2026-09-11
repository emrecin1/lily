"""BFF -> Freqtrade WS koprusu.

Freqtrade'in /api/v1/message/ws'ine baglanir, olay topic'lerine abone olur,
her olayi state.broadcast() ile /events (SSE) abonelerine dagitir. Tarayiciya
HAM Freqtrade mesajini basmiyoruz — sadece "ne oldu + hangi parite" (BFF
sayfalari bunu gorunce ilgili veriyi REST'ten TAZE cekiyor; bkz. static/js/live.js).

new_candle mesaji sadece dataframe.tail(1)'i tasiyan analyzed_df'in aksine
sadece [pair, timeframe, candle_type] tasir (freqtrade/data/dataprovider.py
_emit_df) — biz de analyzed_df'in DataFrame-uzerinden-WS serilestirme
formatini cozmeye ugrasmak yerine, degisikligi REST ile tazeliyoruz. Daha az
hareketli parca, daha az kirilma noktasi.

Reconnect: exponential backoff (1s -> 30s, jitter'li).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random

import websockets

from webui.config import FreqtradeCreds
from webui.state import state

logger = logging.getLogger("webui.ws_bridge")

SUBSCRIBE_TOPICS = [
    "status",
    "entry", "entry_fill", "entry_cancel",
    "exit", "exit_fill", "exit_cancel",
    "protection_trigger", "protection_trigger_global",
    "warning", "exception",
    "whitelist",
    "new_candle",
]

_MAX_BACKOFF = 30.0


def _ws_url(creds: FreqtradeCreds) -> str:
    base = creds.base_url.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/message/ws?token={creds.ws_token}"


async def _handle_message(msg: dict) -> None:
    mtype = msg.get("type")
    data = msg.get("data")

    if mtype == "new_candle":
        # data = [pair, timeframe, candle_type]
        pair = data[0] if isinstance(data, list) and data else None
        await state.broadcast({"type": "new_candle", "pair": pair})
    elif mtype in {
        "entry", "entry_fill", "entry_cancel", "exit", "exit_fill", "exit_cancel",
    }:
        pair = data.get("pair") if isinstance(data, dict) else None
        await state.broadcast({"type": mtype, "pair": pair})
    elif mtype in {
        "protection_trigger", "protection_trigger_global", "warning", "exception",
        "status", "whitelist",
    }:
        await state.broadcast({"type": mtype})
    # digerleri (analyzed_df vb.) bilerek yayinlanmiyor.


async def run_ws_bridge(creds: FreqtradeCreds, stop_event: asyncio.Event) -> None:
    url = _ws_url(creds)
    backoff = 1.0

    while not stop_event.is_set():
        try:
            async with websockets.connect(
                url, open_timeout=5, ping_interval=20, ping_timeout=10
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "data": SUBSCRIBE_TOPICS}))
                state.ws_connected = True
                state.ws_last_error = None
                backoff = 1.0
                logger.info("Freqtrade WS'ine bağlanıldı (%s topic).", len(SUBSCRIBE_TOPICS))

                async for raw in ws:
                    if stop_event.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await _handle_message(msg)

        except asyncio.CancelledError:
            state.ws_connected = False
            raise
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            state.ws_connected = False
            state.ws_last_error = str(exc)
            logger.warning(
                "Freqtrade WS bağlantısı koptu/kurulamadı: %s (yeniden deneme %.0fs sonra)",
                exc, backoff,
            )

        if stop_event.is_set():
            break
        await asyncio.sleep(backoff + random.uniform(0, backoff * 0.3))
        backoff = min(backoff * 2, _MAX_BACKOFF)

    state.ws_connected = False
