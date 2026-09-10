"""Borsa <-> Freqtrade durum mutabakati (STUB — docs/MIGRATION.md Asama 4).

Amac: borsadaki gercek pozisyon/bakiye ile Freqtrade'in `trades` tablosunu
karsilastirmak; fark varsa Telegram/stderr uzerinden alarm vermek. Cron ile
saatlik calistirilir.

Yapilacak (Asama 4):
    1. Freqtrade REST API'den acik trade'leri cek (GET /api/v1/status).
    2. ccxt ile borsadan bakiye + acik emirleri cek (read-only key yeterli).
    3. Karsilastir:
       - Freqtrade "acik" diyor ama borsada karsiligi yok  -> hayalet pozisyon
       - Borsada bakiye var ama Freqtrade bilmiyor          -> yetim varlik
       - Acik emir sayisi / miktar uyusmuyor
    4. Fark -> exit code 1 + Telegram mesaji.

Simdilik sadece iskelet; canli/testnet oncesi doldurulacak.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("reconcile.py: STUB — Asama 4'te implemente edilecek.", file=sys.stderr)
    print("Bkz. docs/MIGRATION.md ve docs/ARCHITECTURE.md §7.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
