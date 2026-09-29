"""`.env` dosyasinda tek bir anahtari, dosyanin geri kalanina dokunmadan
okuyup yazmak icin kucuk yardimci. python-dotenv sadece OKUMA sagliyor;
panelden sifre degistirme gibi YAZMA islemleri icin bu modul kullanilir.

Atomik yazim: once `.env.tmp`'ye yazilir, sonra os.replace ile degistirilir —
yazma sirasinda kesinti olursa orijinal dosya bozulmaz.
"""

from __future__ import annotations

import os
from pathlib import Path


def set_env_value(path: Path, key: str, value: str) -> None:
    """`.env` dosyasinda KEY=... satirini gunceller (yoksa sona ekler) VE
    `os.environ`'u da ayni degerle gunceller.

    Ikincisi olmazsa degisiklik SESSIZCE etkisiz kalir: config.py `_env()`
    ile `os.getenv()` okuyor, o da python-dotenv'in surec baslarken BIR KEZ
    doldurdugu `os.environ`'dan okuyor — sadece dosyayi degistirmek calisan
    surecin gordugu degeri guncellemez (bir sonraki restart'a kadar dosya ve
    gercekte-gecerli-olan deger birbirinden SAPAR, cok tehlikeli bir durum)."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text().splitlines()

    prefix = f"{key}="
    found = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text("\n".join(lines) + "\n")
    os.replace(tmp_path, path)

    os.environ[key] = value
