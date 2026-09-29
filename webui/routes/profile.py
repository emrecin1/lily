"""/profile — panel şifresi değiştirme + demo (dry-run) bakiyesi ayarı.

Şifre burada sadece panel girişini (DASHBOARD_PASSWORD, .env) etkiler;
Freqtrade'in kendi API kimlik bilgileriyle ilgisi yok (bkz. webui/config.py).
Şifre değişince DASHBOARD_SESSION_SECRET de döndürülür (rotate) — bu, diğer
tüm açık oturumları (başka tarayıcı/cihaz) anında geçersiz kılar; MEVCUT
oturuma yeni sırla imzalı taze bir çerez yazılır ki kullanıcı kendi kendini
dışarı atmasın.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, Request

from webui import auth, settings_store
from webui.auth import require_login
from webui.config import REPO_ROOT, get_settings
from webui.envfile import set_env_value
from webui.reload import try_reload
from webui.templating import templates

router = APIRouter()

ENV_PATH = REPO_ROOT / ".env"


def _render_context(flash: dict | None = None) -> dict:
    return {
        "active": "profile",
        "dry_run_wallet": settings_store.read_dry_run_wallet(),
        "telegram": settings_store.read_telegram(),
        "flash": flash,
    }


@router.get("/profile")
async def profile_page(request: Request):
    guard = require_login(request)
    if guard:
        return guard
    return templates.TemplateResponse(request, "profile.html", _render_context())


@router.post("/profile/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    guard = require_login(request)
    if guard:
        return guard

    if not auth.check_password(current_password):
        flash = {"level": "warn", "message": "Mevcut şifre yanlış."}
    elif len(new_password) < 8:
        flash = {"level": "warn", "message": "Yeni şifre en az 8 karakter olmalı."}
    elif new_password != new_password2:
        flash = {"level": "warn", "message": "Yeni şifreler birbiriyle eşleşmiyor."}
    elif new_password == current_password:
        flash = {"level": "warn", "message": "Yeni şifre eskisiyle aynı olamaz."}
    else:
        set_env_value(ENV_PATH, "DASHBOARD_PASSWORD", new_password)
        set_env_value(ENV_PATH, "DASHBOARD_SESSION_SECRET", secrets.token_hex(32))
        get_settings.cache_clear()
        flash = {
            "level": "ok",
            "message": "Şifre değiştirildi. Diğer tüm oturumlar (varsa) çıkışa zorlandı.",
        }

    resp = templates.TemplateResponse(request, "profile.html", _render_context(flash))
    if flash["level"] == "ok":
        # Sir (session_secret) az once donduruldu — bu istegin KENDI oturumu
        # disari atilmasin diye yeni sirla imzali taze bir cerez yaziyoruz.
        resp.set_cookie(
            auth.COOKIE_NAME,
            auth.make_session_cookie_value(),
            max_age=auth.MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
        )
    return resp


@router.post("/profile/demo-wallet")
async def change_demo_wallet(request: Request, amount: float = Form(...)):
    guard = require_login(request)
    if guard:
        return guard
    settings_store.apply_dry_run_wallet(amount)
    flash = await try_reload()
    return templates.TemplateResponse(request, "profile.html", _render_context(flash))


@router.post("/profile/telegram")
async def change_telegram(
    request: Request,
    enabled: bool = Form(False),
    token: str = Form(""),
    chat_id: str = Form(""),
):
    guard = require_login(request)
    if guard:
        return guard

    current = settings_store.read_telegram()
    if enabled and not token and not current.has_token:
        flash = {"level": "warn", "message": "Telegram'ı açmak için önce bot token girmelisin."}
    elif enabled and not chat_id.strip():
        flash = {"level": "warn", "message": "Telegram'ı açmak için chat_id girmelisin."}
    else:
        settings_store.apply_telegram(enabled, token, chat_id)
        flash = await try_reload()

    return templates.TemplateResponse(request, "profile.html", _render_context(flash))
