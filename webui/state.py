"""Bellek-ici paylasilan durum:
  - REST connectivity (arka plan poller'i doldurur)
  - WS bridge connectivity
  - basit pub/sub: ws_bridge olay yayinlar, /events (SSE) abonelere dagitir
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from webui.freqtrade_client import FreqtradeClient, FreqtradeUnavailable

logger = logging.getLogger("webui.state")


@dataclass
class AppState:
    connected: bool = False
    last_error: str | None = None

    ws_connected: bool = False
    ws_last_error: str | None = None

    _subscribers: set[asyncio.Queue] = field(default_factory=set)

    def new_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.add(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def broadcast(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # yavas tuketici: bu event atlanir, bir sonraki gelince yakalar
                logger.debug("SSE abonesi kuyrugu dolu, olay atlandi: %s", event)


state = AppState()


async def poll_connectivity(
    client: FreqtradeClient, stop_event: asyncio.Event, interval: float = 5.0
) -> None:
    """Freqtrade'e periyodik ping — her route'un kendi ping atmasi yerine
    tek yerden connectivity banner'ini besler."""
    while not stop_event.is_set():
        try:
            await client.ping()
            if not state.connected:
                logger.info("Freqtrade REST API'ye baglanildi.")
            state.connected = True
            state.last_error = None
        except FreqtradeUnavailable as exc:
            if state.connected:
                logger.warning("Freqtrade REST API'ye ulasilamiyor: %s", exc)
            state.connected = False
            state.last_error = str(exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
