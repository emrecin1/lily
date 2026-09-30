"""Borsa <-> Freqtrade durum mutabakati (docs/ARCHITECTURE.md §7, MIGRATION Asama 4).

Freqtrade'in `trades` tablosu (REST API) ile borsadaki GERCEK bakiye + acik
emirleri karsilastirir. Fark bulursa exit code 1 + (opsiyonel) Telegram mesaji.
Cron ile saatlik calistirilir:

    0 * * * *  cd /path/to/lily && .venv-rt/bin/python scripts/reconcile.py --config config/config.testnet.json

Read-only calisir: ccxt sadece bakiye/emir OKUR, emir gondermez. API key
(sadece-okuma yeterli) .env veya config exchange blogundan alinir.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_config(paths: list[str]) -> dict:
    """Freqtrade gibi sirayla birlestir; ic sozlukleri (exchange, telegram...)
    derin-birlestir."""
    cfg: dict = {}
    for p in paths:
        with open(p) as f:
            part = json.load(f)
        for k, v in part.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


def _freqtrade_status(cfg: dict) -> tuple[list[dict], dict]:
    """REST API'den acik trade'ler + bakiye. requests freqtrade ile gelir."""
    import requests

    api = cfg.get("api_server", {})
    base = f"http://{api.get('listen_ip_address', '127.0.0.1')}:{api.get('listen_port', 8080)}/api/v1"
    auth = (api.get("username", ""), api.get("password", ""))
    s = requests.Session()
    s.auth = auth
    # Once gercekten Freqtrade mi? (port cakismasina karsi)
    ping = s.get(f"{base}/ping", timeout=10)
    if ping.status_code != 200 or ping.json().get("status") != "pong":
        raise RuntimeError(f"{base} Freqtrade REST API degil (ping != pong)")
    status = s.get(f"{base}/status", timeout=10).json()
    balance = s.get(f"{base}/balance", timeout=10).json()
    return (status if isinstance(status, list) else []), balance


def _exchange_state(cfg: dict) -> tuple[dict, list[dict]]:
    """ccxt ile GERCEK borsa bakiyesi (non-zero) + acik emirler."""
    import ccxt

    exc_cfg = cfg.get("exchange", {})
    name = exc_cfg.get("name", "binance")
    key = exc_cfg.get("key") or os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_TESTNET_API_KEY", "")
    secret = exc_cfg.get("secret") or os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_TESTNET_API_SECRET", "")
    klass = getattr(ccxt, name)
    # Freqtrade'in yerlesik bir "sandbox" anahtari YOK (docs/MIGRATION.md Asama 5,
    # 22 Eylul notu) -- testnet baglantisi tamamen exchange.ccxt_config'teki
    # url/option override'lariyla calisiyor. Freqtrade'in kendi baglandigi
    # AYNI ccxt_config'i burada da uygulamazsak reconcile testnet'te
    # "Invalid Api-Key ID" ile patlar (mainnet'e baglanmaya calisir).
    ex_config: dict = {"apiKey": key, "secret": secret, "enableRateLimit": True}
    ex_config.update(exc_cfg.get("ccxt_config", {}))
    ex = klass(ex_config)

    bal = ex.fetch_balance()
    nonzero = {
        a: float(v) for a, v in bal.get("total", {}).items() if v and float(v) > 0
    }
    try:
        open_orders = ex.fetch_open_orders()
    except Exception:  # noqa: BLE001 - bazi borsalarda sembolsuz cagri kisitli
        open_orders = []
    return nonzero, open_orders


def _notify_telegram(cfg: dict, text: str) -> None:
    tg = cfg.get("telegram", {})
    token = tg.get("token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = tg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        return
    import requests

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"telegram gonderilemedi: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", action="append", default=["config/config.dry.json"],
                    help="tekrarlanabilir; sirayla birlestirilir")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = _load_config(args.config)

    problems: list[str] = []
    try:
        ft_trades, ft_balance = _freqtrade_status(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"Freqtrade REST API'ye ulasilamadi: {exc}", file=sys.stderr)
        return 2

    if cfg.get("dry_run", True):
        print("dry_run=true — borsa mutabakati atlaniyor (gercek pozisyon yok).")
        print(f"Freqtrade acik trade: {len(ft_trades)}")
        return 0

    try:
        ex_bal, ex_orders = _exchange_state(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"Borsa durumu alinamadi: {exc}", file=sys.stderr)
        return 2

    stake = cfg.get("stake_currency", "USDT")
    ft_open_pairs = {t["pair"].split("/")[0] for t in ft_trades}
    ft_amounts = {t["pair"].split("/")[0]: float(t.get("amount", 0)) for t in ft_trades}

    # 1) Freqtrade "acik" diyor ama borsada karsiligi (o coin bakiyesi) yok
    for base in ft_open_pairs:
        have = ex_bal.get(base, 0.0)
        want = ft_amounts.get(base, 0.0)
        if have < want * 0.9:
            problems.append(
                f"HAYALET POZISYON: Freqtrade {base} {want:.6f} acik diyor, "
                f"borsada {have:.6f} var"
            )

    # 2) Borsada stake-disi bakiye var ama Freqtrade bilmiyor
    for asset, amt in ex_bal.items():
        if asset == stake:
            continue
        if asset not in ft_open_pairs:
            problems.append(
                f"YETIM VARLIK: borsada {asset} {amt:.6f} var, Freqtrade acik "
                f"trade'i yok"
            )

    # 3) Acik emir sayisi
    if ex_orders:
        problems.append(f"BORSADA {len(ex_orders)} ACIK EMIR var (Freqtrade disi olabilir)")

    ok = not problems
    header = "OK: mutabakat temiz" if ok else f"UYUSMAZLIK ({len(problems)})"
    lines = [header, f"  Freqtrade acik trade: {len(ft_trades)}",
             f"  Borsa non-zero varlik: {ex_bal}"]
    lines += [f"  - {p}" for p in problems]
    report = "\n".join(lines)
    if not args.quiet or not ok:
        print(report)

    if not ok:
        _notify_telegram(cfg, "🔴 reconcile\n" + report)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
