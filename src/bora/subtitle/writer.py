"""자막 저장 — 원본을 함부로 덮지 않는다.

기획서 v0.2 §2-3 · §6:
1. 저장 전 원본을 `<이름>.bak` 으로 **복사**한다(같은 이름이 있으면 번호를 붙인다).
2. SAMI(.smi) 원본은 **SRT 로 저장**한다. 원본 .smi 는 그대로 남는다.
3. 쓰기는 원자적으로 — 임시 파일에 쓰고 rename. 쓰다 죽어도 반쪽 파일이 남지 않는다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..log import get as get_logger

log = get_logger("writer")

SAMI_SUFFIXES = {".smi", ".sami"}


def backup_path(path: Path) -> Path:
    """`movie.srt` → `movie.srt.bak`, 이미 있으면 `movie.srt.bak2` …"""
    candidate = path.with_suffix(path.suffix + ".bak")
    n = 2
    while candidate.exists():
        candidate = path.with_suffix(f"{path.suffix}.bak{n}")
        n += 1
    return candidate


def target_path(source: Path) -> Path:
    """저장할 곳. SAMI 는 같은 이름의 .srt 로 간다(형식 왕복 손실을 피한다)."""
    source = Path(source)
    if source.suffix.lower() in SAMI_SUFFIXES:
        return source.with_suffix(".srt")
    return source


def save_srt(body: str, source: Path, target: Path | None = None) -> tuple[Path, Path | None]:
    """-> (쓴 파일, 백업 파일 또는 None)

    백업은 **덮어쓸 파일이 이미 있을 때만** 만든다. SAMI → SRT 처럼 새 파일을 만드는
    경우에는 원본이 그대로 남으므로 백업이 필요 없다.
    """
    source = Path(source)
    dest = Path(target) if target else target_path(source)
    dest.parent.mkdir(parents=True, exist_ok=True)

    backup: Path | None = None
    if dest.exists():
        backup = backup_path(dest)
        shutil.copy2(dest, backup)          # 복사다. 옮기지 않는다 — 원본을 잃으면 안 된다
        log.info("백업: %s", backup.name)

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(dest)                   # 원자적 교체
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    log.info("자막 저장: %s (%d 바이트)", dest.name, len(body.encode("utf-8")))
    return dest, backup
