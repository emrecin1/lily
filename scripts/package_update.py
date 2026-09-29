"""Dev deposundan canli (ayri dizin) ortama zip ile yuklenecek bir guncelleme
paketi hazirlar. SADECE kod: webui/, user_data/strategies/*.py, scripts/.
config/, .env, user_data/models|logs|*.sqlite ASLA dahil edilmez -- webui/
deploy.py sunucu tarafinda da bagimsiz olarak bunu zorunlu kilar (SAFE_TARGETS),
burada zaten paketlenmiyor.

Kullanim:
    .venv/bin/python3 scripts/package_update.py

Cikti: dist/update-<YYYYmmdd-HHMMSS>.zip (dist/ .gitignore'da).
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"

INCLUDE_DIRS = ["webui", "user_data/strategies", "scripts"]
EXCLUDE_NAMES = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc"}
# user_data/strategies icinde SADECE kod (.py) -- .json parametre dosyasi
# her ortamin KENDI tuned degerleri, koddan AYRI, ASLA guncelleme ile ezilmez.
STRATEGIES_ALLOWED_SUFFIX = {".py"}


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _iter_files(rel_dir: str):
    src = REPO_ROOT / rel_dir
    if not src.exists():
        return
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDE_NAMES for part in path.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        if rel_dir == "user_data/strategies" and path.suffix not in STRATEGIES_ALLOWED_SUFFIX:
            continue
        yield path


def build_package(out_path: Path | None = None) -> Path:
    DIST_DIR.mkdir(exist_ok=True)
    if out_path is None:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_path = DIST_DIR / f"update-{ts}.zip"

    manifest = {
        "git_commit": _git_commit(),
        "packaged_at": datetime.now(UTC).isoformat(),
        "included": INCLUDE_DIRS,
    }

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        file_count = 0
        for rel_dir in INCLUDE_DIRS:
            for path in _iter_files(rel_dir):
                arcname = path.relative_to(REPO_ROOT).as_posix()
                # zf.write() varsayilan olarak Unix izin bitlerini (ornegin
                # +x) KORUMAZ -- ZipInfo.external_attr'i elle set ediyoruz,
                # aksi halde scripts/*.sh calistirilabilirligini kaybeder.
                info = zipfile.ZipInfo.from_file(path, arcname)
                info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
                with path.open("rb") as f:
                    zf.writestr(info, f.read(), zipfile.ZIP_DEFLATED)
                file_count += 1

    print(f"Paketlendi: {out_path} ({file_count} dosya, commit {manifest['git_commit'][:8]})")
    return out_path


if __name__ == "__main__":
    build_package()
