"""Panel girisi: tek DASHBOARD_PASSWORD + imzali session cookie.

Freqtrade kimlik bilgileriyle ILISKILI DEGIL — tarayici Freqtrade sifresini
hicbir zaman gormez (bkz. webui/config.py, freqtrade_client.py). Bu sadece
paneli localhost disina cikarsa diye savunma katmani.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from webui.config import get_settings
from webui.templating import templates

COOKIE_NAME = "webui_session"
MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 gun


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="webui-auth")


def check_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate, get_settings().dashboard_password)


def make_session_cookie_value() -> str:
    return _serializer().dumps({"ok": True})


def is_valid_session(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("ok"))


def require_login(request: Request) -> RedirectResponse | None:
    """Her route'un basinda cagrilir: giris yoksa /login'e yonlendirir,
    aksi halde None dondurur (route calismaya devam eder)."""
    if not is_valid_session(request):
        nxt = request.url.path
        return RedirectResponse(url=f"/login?next={nxt}", status_code=303)
    return None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter()


@router.get("/login")
async def login_form(request: Request, next: str = "/overview"):
    if is_valid_session(request):
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@router.post("/login")
async def login_submit(
    request: Request, password: str = Form(...), next: str = Form("/overview")
):
    if not check_password(password):
        return templates.TemplateResponse(
            request, "login.html", {"next": next, "error": "Yanlış şifre."}, status_code=401
        )
    resp = RedirectResponse(url=next or "/overview", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        make_session_cookie_value(),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp
