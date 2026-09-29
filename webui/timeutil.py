"""Zaman formatlama — TUM zaman gosterimleri YEREL saate (sunucunun sistem
saat dilimine) cevrilir.

Neden: Freqtrade REST API'si (open_date/close_date) ve loglari UTC dondurur/
yazar; bunlari oldugu gibi gostermek kullaniciyi yaniltiyordu (ör. "az once"
egitilen bir model "09:49" gosterirken kullanicinin saati "12:51" idi — ikisi
de dogruydu, UTC+3 fark vardi, ama UI bunu belli etmiyordu). Kisisel/tek
kullanicili bir arac icin en az kafa karistiran secim: her yerde yerel saat,
gerekirse tek bir "(yerel saat)" ipucu."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_FMT = "%d.%m.%Y %H:%M"


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


def daily_reset_info() -> tuple[str, str]:
    """Gunluk kayip kapisi (AiCryptoFreqAIStrategy.confirm_trade_entry) UTC
    takvim-gunune gore calisir, yani UTC gece yarisinda sifirlanir. Donen:
    (sifirlanma ani - yerel saat "HH:MM", kalan sure - "Xsa Ydk" gibi)."""
    now_utc = datetime.now(timezone.utc)
    next_reset_utc = (now_utc + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    remaining = next_reset_utc - now_utc
    local_str = next_reset_utc.astimezone().strftime("%H:%M")
    total_minutes = max(int(remaining.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    remaining_str = f"{hours} sa {minutes} dk" if hours else f"{minutes} dk"
    return local_str, remaining_str


def timeframe_to_seconds(timeframe: str) -> int:
    """'4h' -> 14400 gibi. Freqtrade'in candle "date" alani mumun
    BASLANGIC zamanini verir (OHLCV standardi) — kullanicilar bunu "hala
    guncellenmiyor" saniyor cunku 07:00 gorup "ama simdi 11:00" diyor; oysa
    07:00-11:00 araligindaki mum henuz KAPANMADI. Bu yuzden /pairs sayfasi
    baslangic+bitis araligini birlikte gosteriyor (bkz. routes/pairs.py)."""
    units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    unit = timeframe[-1]
    amount = int(timeframe[:-1])
    return amount * units.get(unit, 3600)
