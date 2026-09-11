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


templates.env.filters["pct"] = fmt_pct
templates.env.filters["num"] = fmt_num
