"""Freqtrade REST API'sine ince, salt-okunur (GET-only) istemci.

Sunucu-sunucu, HTTP Basic Auth (config.dry.json'dan okunur — bkz. config.py).
JWT/refresh yok: guvenilir, lokal, dusuk-frekansli bir cagiran icin gereksiz
karmasiklik. Her metod tek deneme yapar, hata durumunda FreqtradeUnavailable
firlatir; route'lar bunu yakalayip "bot'a ulasilamiyor" banner'i gosterir.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from webui.config import FreqtradeCreds

logger = logging.getLogger("webui.freqtrade_client")


class FreqtradeUnavailable(Exception):
    """Freqtrade REST API'sine ulasilamadi (down, restart, timeout, auth)."""


class FreqtradeClient:
    def __init__(self, creds: FreqtradeCreds) -> None:
        self._creds = creds
        self._client = httpx.AsyncClient(
            base_url=creds.base_url,
            auth=httpx.BasicAuth(creds.username, creds.password),
            timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Freqtrade %s -> HTTP %s", path, exc.response.status_code)
            raise FreqtradeUnavailable(f"{path}: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.warning("Freqtrade %s -> %s", path, exc)
            raise FreqtradeUnavailable(f"{path}: {exc}") from exc

    # ---- genel -----------------------------------------------------------
    async def ping(self) -> dict:
        return await self._get("/ping")

    async def health(self) -> dict:
        return await self._get("/health")

    async def show_config(self) -> dict:
        return await self._get("/show_config")

    async def sysinfo(self) -> dict:
        return await self._get("/sysinfo")

    async def logs(self, limit: int = 100) -> dict:
        return await self._get("/logs", {"limit": limit})

    async def whitelist(self) -> dict:
        return await self._get("/whitelist")

    # ---- trading / istatistik ---------------------------------------------
    async def status(self) -> list[dict]:
        return await self._get("/status")

    async def trades(self, limit: int = 500, offset: int = 0) -> dict:
        return await self._get("/trades", {"limit": limit, "offset": offset})

    async def balance(self) -> dict:
        return await self._get("/balance")

    async def profit(self) -> dict:
        return await self._get("/profit")

    async def daily(self, days: int = 7) -> dict:
        return await self._get("/daily", {"timescale": days})

    async def weekly(self, weeks: int = 8) -> dict:
        return await self._get("/weekly", {"timescale": weeks})

    async def monthly(self, months: int = 6) -> dict:
        return await self._get("/monthly", {"timescale": months})

    # ---- mum / gosterge verisi --------------------------------------------
    async def pair_candles(self, pair: str, timeframe: str, limit: int = 500) -> dict:
        return await self._get(
            "/pair_candles", {"pair": pair, "timeframe": timeframe, "limit": limit}
        )


_client: FreqtradeClient | None = None


def init_client(creds: FreqtradeCreds) -> FreqtradeClient:
    global _client
    _client = FreqtradeClient(creds)
    return _client


def get_client() -> FreqtradeClient:
    if _client is None:
        raise RuntimeError("FreqtradeClient henuz baslatilmadi (lifespan calismadi mi?)")
    return _client
