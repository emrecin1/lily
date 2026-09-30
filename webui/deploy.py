"""Zip yükleyerek kod güncelleme -- SADECE canlı (ayrı dizin) ortamı için.

Akış (routes/system.py çağırır): validate_zip -> (açık pozisyon kontrolü,
caller yapar) -> git snapshot -> copy_files -> git commit -> trigger_restart.

Güvenlik katmanları:
  1. Zip-slip koruması -- her zip girdisinin cozumlenmis yolu staging
     dizininin İÇİNDE kalmalı.
  2. manifest.json zorunlu -- rastgele bir zip'in kabul edilmesini önler.
  3. SAFE_TARGETS allow-list -- staging'den gerçek dizine kopyalarken SADECE
     bu köklere izin verilir; config/.env/user_data/models/logs/*.sqlite bu
     mekanizmayla ASLA değişmez (zip'in kendisi zaten bunları içermez --
     scripts/package_update.py -- ama sunucu tarafında BAĞIMSIZ ikinci bir
     katman olarak burada da uygulanır).

REPO_ROOT burada webui/config.py'deki ile AYNI degil olabilir kastli: bu
modul, deploy edildigi (canli) dizinin kokune gore calisir.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50MB
SAFE_TARGETS = ("webui", "user_data/strategies", "scripts")

logger = logging.getLogger("webui.deploy")


class DeployError(Exception):
    """Kullaniciya gosterilecek, beklenen bir dogrulama/uygulama hatasi."""


@dataclass
class ApplyResult:
    ok: bool
    message: str
    commit: str | None = None


def _safe_extract(zf: zipfile.ZipFile, staging_dir: Path) -> None:
    """Zip-slip korumali extract: her girdinin cozumlenmis yolu staging_dir
    icinde kalmali. Mutlak yol veya '..' ile disari cikan herhangi bir
    girdi TUM islemi reddettirir (extract hic baslamaz)."""
    staging_resolved = staging_dir.resolve()
    for member in zf.infolist():
        name = member.filename
        if name.startswith("/") or name.startswith("\\"):
            raise DeployError(f"Guvensiz zip girdisi (mutlak yol): {name}")
        target = (staging_dir / name).resolve()
        if target != staging_resolved and staging_resolved not in target.parents:
            raise DeployError(f"Guvensiz zip girdisi (dizin disina cikiyor): {name}")
    zf.extractall(staging_dir)

    # zipfile.extractall() Unix izin bitlerini (ornegin scripts/*.sh +x)
    # OTOMATIK GERI YUKLEMEZ, sadece ZipInfo.external_attr icinde tasir --
    # elle uyguluyoruz (package_update.py bu bitleri zaten dogru yaziyor).
    for member in zf.infolist():
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode:
            (staging_dir / member.filename).chmod(mode)


def validate_zip(data: bytes) -> Path:
    """Zip'i dogrular ve GECICI bir staging dizinine acar. Cagiran, isi
    bittiginde staging dizinini silmekten sorumlu."""
    if len(data) > MAX_ZIP_BYTES:
        raise DeployError(f"Zip cok buyuk ({len(data)} bayt, sinir {MAX_ZIP_BYTES}).")

    staging_dir = Path(tempfile.mkdtemp(prefix="lily-update-"))
    tmp_zip = staging_dir / "_upload.zip"
    tmp_zip.write_bytes(data)

    if not zipfile.is_zipfile(tmp_zip):
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeployError("Yuklenen dosya gecerli bir zip degil.")

    with zipfile.ZipFile(tmp_zip) as zf:
        _safe_extract(zf, staging_dir)
    tmp_zip.unlink()

    manifest_path = staging_dir / "manifest.json"
    if not manifest_path.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeployError(
            "Zip icinde manifest.json yok -- bu scripts/package_update.py ile "
            "paketlenmemis gibi gorunuyor, reddedildi."
        )
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeployError(f"manifest.json bozuk: {exc}") from exc
    if "git_commit" not in manifest or "packaged_at" not in manifest:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeployError("manifest.json beklenen alanlari icermiyor.")

    return staging_dir


def _run_git(repo_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_dir, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise DeployError(f"git {' '.join(args)} basarisiz: {result.stderr.strip()}")
    return result.stdout.strip()


def git_snapshot(repo_dir: Path, message: str) -> str:
    _run_git(repo_dir, "add", "-A")
    _run_git(repo_dir, "commit", "--allow-empty", "-m", message)
    return _run_git(repo_dir, "rev-parse", "--short", "HEAD")


def copy_files(staging_dir: Path, repo_dir: Path) -> list[str]:
    """staging_dir icindeki SAFE_TARGETS koklerini repo_dir uzerine kopyalar.
    Baska hicbir yol kopyalanmaz (manifest.json dahil -- o sadece dogrulama
    icindi)."""
    applied: list[str] = []
    for rel in SAFE_TARGETS:
        src = staging_dir / rel
        if not src.exists():
            continue
        dst = repo_dir / rel
        if src.is_dir():
            for item in src.rglob("*"):
                if "__pycache__" in item.parts:
                    continue
                rel_item = item.relative_to(src)
                dst_item = dst / rel_item
                if item.is_dir():
                    dst_item.mkdir(parents=True, exist_ok=True)
                else:
                    dst_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dst_item)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        applied.append(rel)
    return applied


def trigger_restart(repo_dir: Path) -> None:
    """scripts/live_ctl.sh restart'i AYRI, bagimsiz bir surec olarak baslatir
    -- bu webui surecinin kendisini yeniden baslatan script HTTP yaniti
    donduktan SONRA calisir (start_new_session=True: webui kapatilsa/yeniden
    baslasa bile bu script calismaya devam eder).

    "bash scripts/..." (dogrudan "scripts/..." DEGIL) kasitli: zip'ten gelen
    dosyalar +x izni tasimayabilir (bkz. package_update.py -- korunur ama
    ikinci bir guvenlik katmani olarak burada izne BAGIMLI KALINMAZ)."""
    subprocess.Popen(
        ["bash", "scripts/live_ctl.sh", "restart"],
        cwd=repo_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def apply_update(data: bytes, *, repo_dir: Path = REPO_ROOT) -> ApplyResult:
    """Tum akisi yurutur. Cagiran (routes/system.py) acik pozisyon kontrolunu
    BUNDAN ONCE yapmis olmali -- bu fonksiyon o kontrolu bilmez, sadece
    uygulamayi yapar."""
    staging_dir = validate_zip(data)
    try:
        git_snapshot(repo_dir, "pre-update snapshot")
        applied = copy_files(staging_dir, repo_dir)
        if not applied:
            raise DeployError(
                "Zip'te beklenen hicbir dizin (webui/, user_data/strategies/, "
                "scripts/) bulunamadi -- hicbir sey degistirilmedi."
            )
        commit = git_snapshot(repo_dir, f"update applied: {', '.join(applied)}")
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    trigger_restart(repo_dir)
    return ApplyResult(
        ok=True,
        message=f"Güncelleme uygulandı ({', '.join(applied)}). Sistem yeniden başlatılıyor...",
        commit=commit,
    )


def rollback(commit: str, *, repo_dir: Path = REPO_ROOT) -> ApplyResult:
    _run_git(repo_dir, "reset", "--hard", commit)
    trigger_restart(repo_dir)
    return ApplyResult(ok=True, message=f"{commit} sürümüne dönüldü. Sistem yeniden başlatılıyor...", commit=commit)


def recent_history(repo_dir: Path = REPO_ROOT, limit: int = 10) -> list[dict]:
    try:
        out = _run_git(repo_dir, "log", f"-{limit}", "--format=%h\t%ci\t%s")
    except DeployError:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows.append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
    return rows


def current_version(repo_dir: Path = REPO_ROOT) -> str:
    try:
        return _run_git(repo_dir, "log", "-1", "--format=%h  %ci  %s")
    except DeployError:
        return "—"
