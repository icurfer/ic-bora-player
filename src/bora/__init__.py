"""Bora — libmpv 를 엔진으로 쓰는 GTK 미디어 플레이어."""

from pathlib import Path

APP_ID = "com.icurfer.Bora"


def _read_version() -> str:
    """저장소 루트의 version 파일을 읽는다. 설치본에서는 패키지 메타데이터를 쓴다."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "version"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    try:
        from importlib.metadata import version as _v

        return _v("bora")
    except Exception:
        return "0.0.0"


__version__ = _read_version()
