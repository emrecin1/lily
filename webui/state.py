"""Bellek-ici paylasilan durum: baglanti saglamligi (arka plan poller'i doldurur).

Faz 3'te ws_bridge.py burayi pair basina son analyzed_df / trade cache ile
genisletecek. Simdilik (Faz 1) sadece connectivity.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from webui.freqtrade_client import FreqtradeClient, FreqtradeUnavailable

logger = logging.getLogger("webui.state")


@dataclass
class AppState:
    connected: bool = False
    last_error: str | None = None


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
