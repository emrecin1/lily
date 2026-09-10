"""Asama 2 parity kontrolu — V1 feature'lari <-> Freqtrade stratejisi.

Calistir:  .venv-rt/bin/python scripts/parity_check.py

Kontroller:
  1. OHLCV kaynak parity : Freqtrade feather  vs  V1 features_rules_*.csv
  2. Indikator parity    : add_indicators(feather)  vs  V1 csv onceden hesaplanmis
                           feature kolonlari (ayni timestamp'lerde)
  3. talib <-> ta        : AiCryptoRuleStrategy (talib) ile AiCryptoFeatureStrategy
                           (V1 `ta`) EMA/RSI farkinin buyuklugu
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.features.indicators import add_indicators  # noqa: E402
from src.ml.dataset import feature_columns  # noqa: E402

PAIR = "BTC/USDT"
FEATHER = REPO / "user_data/data/binance/BTC_USDT-4h.feather"
V1_CSV = REPO / "data/processed/features_rules_BTC_USDT.csv"


def _load_feather() -> pd.DataFrame:
    df = pd.read_feather(FEATHER)
    df = df.rename(columns={"date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _load_v1() -> pd.DataFrame:
    df = pd.read_csv(V1_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _cmp(a: pd.Series, b: pd.Series, name: str, rtol=1e-6, atol=1e-8) -> dict:
    m = a.notna() & b.notna()
    if m.sum() == 0:
        return {"col": name, "n": 0, "max_abs": np.nan, "max_rel": np.nan, "ok": False}
    d = (a[m] - b[m]).abs()
    rel = d / b[m].abs().replace(0, np.nan)
    ok = bool(np.allclose(a[m], b[m], rtol=rtol, atol=atol, equal_nan=True))
    return {
        "col": name,
        "n": int(m.sum()),
        "max_abs": float(d.max()),
        "max_rel": float(rel.max(skipna=True)),
        "ok": ok,
    }


def main() -> int:
    ft = _load_feather()
    v1 = _load_v1()

    lo = max(ft["timestamp"].min(), v1["timestamp"].min())
    hi = min(ft["timestamp"].max(), v1["timestamp"].max())
    ft = ft[(ft["timestamp"] >= lo) & (ft["timestamp"] <= hi)].reset_index(drop=True)
    v1 = v1[(v1["timestamp"] >= lo) & (v1["timestamp"] <= hi)].reset_index(drop=True)
    print(f"Ortak aralik: {lo} -> {hi}   feather={len(ft)} satir  v1={len(v1)} satir")

    merged = ft.merge(v1, on="timestamp", suffixes=("_ft", "_v1"), how="inner")
    print(f"Eslessen timestamp: {len(merged)}")
    print()

    # ---- 1. OHLCV kaynak parity ---------------------------------------------
    print("=" * 70)
    print("1) OHLCV KAYNAK PARITY  (Freqtrade feather vs V1 csv, ayni timestamp)")
    print("=" * 70)
    rows = [_cmp(merged[f"{c}_ft"], merged[f"{c}_v1"], c, rtol=1e-4, atol=1e-2)
            for c in ["open", "high", "low", "close", "volume"]]
    print(pd.DataFrame(rows).to_string(index=False))
    ohlcv_ok = all(r["ok"] for r in rows)
    print(f"\n  -> OHLCV kaynaklari {'AYNI (tolerans icinde)' if ohlcv_ok else 'FARKLI'}")
    print()

    # ---- 2. Indikator parity ----------------------------------------------
    print("=" * 70)
    print("2) INDIKATOR PARITY  (add_indicators(feather) vs V1 csv feature kolonlari)")
    print("=" * 70)
    feat = add_indicators(ft.rename(columns={"timestamp": "timestamp"}))
    feat["timestamp"] = ft["timestamp"]
    fm = feat.merge(v1, on="timestamp", suffixes=("_calc", "_v1"), how="inner")

    cols = feature_columns()
    rows = []
    for c in cols:
        if f"{c}_calc" in fm and f"{c}_v1" in fm:
            rows.append(_cmp(fm[f"{c}_calc"], fm[f"{c}_v1"], c, rtol=1e-5, atol=1e-6))
    rep = pd.DataFrame(rows)
    print(rep.to_string(index=False))
    ind_ok = bool(rep["ok"].all())
    n_bad = int((~rep["ok"]).sum())
    print(f"\n  -> {len(rep)} feature'dan {len(rep) - n_bad} tam parity, {n_bad} sapmali")
    if n_bad:
        print("     Sapmali (max_abs / max_rel):")
        print(rep[~rep["ok"]][["col", "max_abs", "max_rel"]].to_string(index=False))
    print()

    # ---- 3. talib <-> ta (EMA/RSI) --------------------------------------
    print("=" * 70)
    print("3) talib (AiCryptoRuleStrategy) <-> ta (V1 / AiCryptoFeatureStrategy)")
    print("=" * 70)
    try:
        import talib.abstract as taABS

        o = ft.copy()
        tal = pd.DataFrame({
            "ema20": taABS.EMA(o, timeperiod=20),
            "ema50": taABS.EMA(o, timeperiod=50),
            "rsi": taABS.RSI(o, timeperiod=14),
        })
        rows = [_cmp(tal[c].reset_index(drop=True), feat[c].reset_index(drop=True),
                     f"{c} (talib vs ta)", rtol=1e-3, atol=1e-2)
                for c in ["ema20", "ema50", "rsi"]]
        print(pd.DataFrame(rows).to_string(index=False))
        print("\n  -> talib ve ta EMA/RSI SEED yontemi farkli; ilk ~100 mumda sapar,")
        print("     sonra yakinsar. Parity icin iki taraf da `ta` kullanmali")
        print("     (AiCryptoFeatureStrategy -> V1 ile ozdes).")
    except Exception as exc:  # noqa: BLE001
        print(f"  talib yok / hata: {exc}")
    print()

    print("=" * 70)
    print(f"SONUC: OHLCV_parity={ohlcv_ok}  INDIKATOR_parity={ind_ok}")
    print("=" * 70)
    return 0 if (ohlcv_ok and ind_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
