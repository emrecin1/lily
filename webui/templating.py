"""Paylasilan Jinja2Templates ornegi + ortak filtreler."""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

from webui.config import BASE_DIR
from webui.state import state

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# base.html'deki baglanti banner'i buradan okur — her route'un kendi
# connected/last_error hesaplamasina gerek kalmaz (bkz. state.py'deki poller).
templates.env.globals["live"] = state


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.{decimals}f}%"


def fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


# /pairs sol menudeki "ikon" — gercek logo CDN'i YOK (webui/templates/
# base.html'den htmx'i, pair_chart.html'den lightweight-charts'i disariya
# bagimli olmasin diye yerellestirdik; bir ucuncu dis kaynagi — coin logo
# CDN'i — burada eklemek ayni sorunu geri getirir). Bunun yerine sembolden
# turetilen sabit (deterministik) renkli, 2 harfli bir rozet.
_COIN_PALETTE = [
    "#f5a623", "#5b8def", "#2ecc71", "#e5484d", "#a855f7",
    "#06b6d4", "#f472b6", "#84cc16", "#f97316", "#818cf8",
]


def coin_badge_color(pair: str) -> str:
    base = pair.split("/")[0] if pair else pair
    return _COIN_PALETTE[sum(ord(c) for c in base) % len(_COIN_PALETTE)]


def coin_initials(pair: str) -> str:
    base = pair.split("/")[0] if pair else pair
    return base[:2].upper()


templates.env.filters["pct"] = fmt_pct
templates.env.filters["num"] = fmt_num
templates.env.filters["coincolor"] = coin_badge_color
templates.env.filters["coininitials"] = coin_initials
