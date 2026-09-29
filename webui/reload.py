"""Config/strateji dosyalari diskte guncellendikten sonra, acik pozisyon
yoksa Freqtrade'in resmi POST /reload_config ucunu tetikleyen ortak mantik.
routes/settings.py VE routes/profile.py (demo bakiyesi) tarafindan paylasilir.
"""

from __future__ import annotations

import logging

from webui.freqtrade_client import FreqtradeUnavailable, get_client

logger = logging.getLogger("webui.reload")


async def open_trade_count() -> int | None:
    """None = bot'a ulasilamadi (bilinmiyor), aksi halde acik islem sayisi."""
    try:
        status = await get_client().status()
        return len(status)
    except FreqtradeUnavailable:
        return None


async def try_reload() -> dict:
    """Acik pozisyon yoksa reload_config'i dener. Donen sozluk:
    {"level": "ok"|"warn", "message": str, "pending": bool}"""
    open_count = await open_trade_count()
    if open_count is None:
        return {
            "level": "warn",
            "pending": True,
            "message": (
                "Kaydedildi. Bot şu an yanıt vermiyor, otomatik uygulanamadı — "
                "bot'a ulaşılabildiğinde 'Şimdi uygula' ile yeniden deneyin."
            ),
        }
    if open_count > 0:
        return {
            "level": "warn",
            "pending": True,
            "message": (
                f"Kaydedildi. {open_count} açık pozisyon olduğu için bot henüz "
                "yeniden yüklenmedi — pozisyon(lar) kapanınca 'Şimdi uygula'ya basın."
            ),
        }
    try:
        await get_client().reload_config()
        return {"level": "ok", "pending": False, "message": "Kaydedildi ve bot'a hemen uygulandı."}
    except FreqtradeUnavailable as exc:
        logger.warning("reload_config basarisiz: %s", exc)
        return {
            "level": "warn",
            "pending": True,
            "message": (
                "Kaydedildi ama bot'a uygulanamadı (bağlantı hatası). "
                "Az sonra 'Şimdi uygula' ile tekrar deneyin."
            ),
        }
