"""Asama 2 — backtest seviyesi parity: V1 kural motoru <-> Freqtrade.

Calistir:  .venv-rt/bin/python scripts/parity_backtest.py

V1 tarafi : src/rules/engine.run_coin() ayni feather OHLCV'sinde
FT  tarafi: en son backtest-result (AiCryptoFeatureStrategy, BTC/USDT)

Karsilastirma: giris/cikis MUM zaman damgalari (absolut PnL degil — pozisyon
boyutu, fill modeli, fee muhasebesi iki motorda farkli; onemli olan strateji
mantiginin ayni mumlarda tetiklenmesi).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from freqtrade.data.btanalysis import load_backtest_data  # noqa: E402

from src.config import CONFIG  # noqa: E402
from src.features.indicators import add_indicators  # noqa: E402
from src.rules.engine import run_coin  # noqa: E402

PAIR = "BTC/USDT"
FEATHER = REPO / "user_data/data/binance/BTC_USDT-4h.feather"
BT_DIR = REPO / "user_data/backtest_results"
TR_LO, TR_HI = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")


def v1_trades() -> pd.DataFrame:
    df = pd.read_feather(FEATHER).rename(columns={"date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = add_indicators(df)
    # V1 run_coin, tam gecmisi warmup icin kullanip pencereyi backtest araligina kirpar.
    warm = df[df["timestamp"] < TR_HI].copy()
    res = run_coin(CONFIG, warm, PAIR, starting_balance=CONFIG.rules.demo_balance)
    t = pd.DataFrame([tr.to_dict() for tr in res.trades])
    if t.empty:
        return t
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True)
    return t[t["entry_time"] >= TR_LO].reset_index(drop=True)


def ft_trades() -> pd.DataFrame:
    latest = max(BT_DIR.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    print(f"FT backtest dosyasi: {latest.name}")
    df = load_backtest_data(latest, strategy="AiCryptoFeatureStrategy")
    df = df[df["pair"] == PAIR].copy()
    df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    return df.reset_index(drop=True)


def main() -> int:
    v1 = v1_trades()
    ft = ft_trades()
    print(f"\nV1 kural motoru : {len(v1)} islem")
    print(f"Freqtrade       : {len(ft)} islem\n")

    v1e = set(v1["entry_time"]) if not v1.empty else set()
    fte = set(ft["open_date"]) if not ft.empty else set()
    common = sorted(v1e & fte)
    only_v1 = sorted(v1e - fte)
    only_ft = sorted(fte - v1e)

    print(f"Ayni giris mumu : {len(common)}")
    print(f"Sadece V1       : {len(only_v1)}  {only_v1[:5]}")
    print(f"Sadece Freqtrade: {len(only_ft)}  {only_ft[:5]}")

    if not v1.empty and not ft.empty:
        j = pd.merge(
            v1[["entry_time", "exit_time", "exit_reason"]],
            ft[["open_date", "close_date", "exit_reason"]],
            left_on="entry_time", right_on="open_date", how="inner",
            suffixes=("_v1", "_ft"),
        )
        j["exit_ayni"] = j["exit_time"] == j["close_date"]
        j["exit_fark_mum"] = (j["close_date"] - j["exit_time"]).dt.total_seconds() / 3600 / 4
        print(f"\nEslesen {len(j)} islemde cikis mumu ayni: {int(j['exit_ayni'].sum())}")
        print("Cikis farki (mum) dagilimi:")
        print(j["exit_fark_mum"].describe().to_string())
        print("\nOrnek (ilk 10):")
        print(j.head(10).to_string(index=False))

    print("\nNOT: absolut PnL kiyaslanmiyor — pozisyon boyutu (V1 alloc %25 vs")
    print("FT stake_amount), fill fiyati ve fee muhasebesi iki motorda farkli.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
