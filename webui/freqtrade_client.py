"""Freqtrade REST API'sine ince istemci. Cogunlukla salt-okunur (GET); tek
istisna `reload_config()` — Freqtrade'in KENDI resmi Bot-control ucu, /settings
sayfasindan config/strateji dosyalarini diskte guncelledikten sonra ayni
surec (PID) icinde yeniden yuklemek icin kullanilir (bkz. routes/settings.py).
Baska hicbir yazma/kontrol ucu (start/stop/forceexit) BILINCLI olarak yok —
webui/README.md.

Sunucu-sunucu, HTTP Basic Auth (config.dry.json'dan okunur — bkz. config.py).
JWT/refresh yok: guvenilir, lokal, dusuk-frekansli bir cagiran icin gereksiz
karmasiklik. Her metod tek deneme yapar, hata durumunda FreqtradeUnavailable
firlatir; route'lar bunu yakalayip "bot'a ulasilamiyor" banner'i gosterir.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from webui.config import FreqtradeCreds

logger = logging.getLogger("webui.freqtrade_client")

# uvicorn'un (Freqtrade'in kendi API server'i) varsayilan keep-alive suresi
# TAM 5.0 saniye. httpx'in varsayilan keepalive_expiry'si de 5.0 saniye —
# ikisi ayni oldugu ve poll_connectivity de tam 5.0 sn'de bir pingledigi
# icin (bkz. state.py) araya bir yaris durumu giriyordu: istemci havuzdaki
# baglantiyi TAM sunucunun kapatmaya karar verdigi anda yeniden kullanmaya
# calisiyor, sunucu da "Server disconnected without sending a response" ile
# reddediyordu (Freqtrade calisirken hicbir sey yanlis gitmemis olsa bile,
# ~her birkac dakikada bir tesadufen ortaya cikan zararsiz ama alarm verici
# bir flaky-connection deseni). Istemciyi sunucudan biraz daha erken
# "yaslandirarak" bu yarisi tamamen ortadan kaldiriyoruz.
_KEEPALIVE_EXPIRY = 4.0
# Bu sinifta yakalanan hatalar "baglanti tam o an koptu/yenileniyordu" turu
# gecici hatalar — bir kez sessizce tekrar denemek, reload_config sirasindaki
# kisa API-server yeniden baslatmasini da buyuk olcude gorunmez kilar.
_TRANSIENT_ERRORS = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout)


class FreqtradeUnavailable(Exception):
    """Freqtrade REST API'sine ulasilamadi (down, restart, timeout, auth)."""


class FreqtradeClient:
    def __init__(self, creds: FreqtradeCreds) -> None:
        self._creds = creds
        self._client = httpx.AsyncClient(
            base_url=creds.base_url,
            auth=httpx.BasicAuth(creds.username, creds.password),
            timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
            limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in (1, 2):
            try:
                resp = await self._client.request(method, path, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Freqtrade %s %s -> HTTP %s", method, path, exc.response.status_code
                )
                raise FreqtradeUnavailable(f"{path}: HTTP {exc.response.status_code}") from exc
            except _TRANSIENT_ERRORS as exc:
                if attempt == 1:
                    logger.debug("Freqtrade %s %s -> %s, tekrar deneniyor", method, path, exc)
                    await asyncio.sleep(0.2)
                    continue
                logger.warning("Freqtrade %s %s -> %s (retry sonrasi)", method, path, exc)
                raise FreqtradeUnavailable(f"{path}: {exc}") from exc
            except httpx.HTTPError as exc:
                logger.warning("Freqtrade %s %s -> %s", method, path, exc)
                raise FreqtradeUnavailable(f"{path}: {exc}") from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str) -> Any:
        return await self._request("POST", path)

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

    async def reload_config(self) -> dict:
        """Freqtrade'in resmi Bot-control ucu: config + strateji dosyalarini
        DISKTEN yeniden okuyup ayni surecte (PID degismez) yeniden kurar.
        Acik islemler/DB'ye dokunmaz. Kisa bir an (~saniyeler) API server'i
        yeniden baslattigi icin bu cagriyi izleyen GET'ler gecici olarak
        FreqtradeUnavailable firlatabilir — beklenen davranis."""
        return await self._post("/reload_config")

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
