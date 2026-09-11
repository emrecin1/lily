"""Zaman formatlama — TUM zaman gosterimleri YEREL saate (sunucunun sistem
saat dilimine) cevrilir.

Neden: Freqtrade REST API'si (open_date/close_date) ve loglari UTC dondurur/
yazar; bunlari oldugu gibi gostermek kullaniciyi yaniltiyordu (ör. "az once"
egitilen bir model "09:49" gosterirken kullanicinin saati "12:51" idi — ikisi
de dogruydu, UTC+3 fark vardi, ama UI bunu belli etmiyordu). Kisisel/tek
kullanicili bir arac icin en az kafa karistiran secim: her yerde yerel saat,
gerekirse tek bir "(yerel saat)" ipucu."""

from __future__ import annotations

from datetime import datetime

DEFAULT_FMT = "%Y-%m-%d %H:%M"


def parse_iso(s: str | None) -> datetime | None:
    """Freqtrade'in ISO8601 (...Z veya +00:00) zaman damgasini parse eder."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_to_local_str(s: str | None, fmt: str = DEFAULT_FMT) -> str:
    """Freqtrade'in (UTC) ISO zaman damgasini sistemin yerel saatine cevirip
    formatlar."""
    dt = parse_iso(s)
    if dt is None:
        return "—"
    return dt.astimezone().strftime(fmt)


def epoch_to_local_str(epoch_s: float | None, fmt: str = DEFAULT_FMT) -> str:
    """Unix epoch (saniye) -> yerel saat string'i. datetime.fromtimestamp()
    argumansiz zaten sistemin yerel saat dilimini kullanir."""
    if epoch_s is None:
        return "—"
    return datetime.fromtimestamp(epoch_s).strftime(fmt)
