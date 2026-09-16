"""Bora — libmpv 를 엔진으로 쓰는 GTK 미디어 플레이어."""

from pathlib import Path

APP_ID = "com.icurfer.Bora"


# 빌드가 이 줄을 실제 버전으로 바꿔 넣는다(scripts/build-deb.sh).
# 저장소에서 바로 돌릴 때는 루트의 `version` 파일이 이긴다.
_BUILD_VERSION = "0.0.0-dev"


def _read_version() -> str:
    """저장소에서 돌리면 `version` 파일, 설치본에서는 빌드가 심은 값."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "version"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    if not _BUILD_VERSION.endswith("-dev"):
        return _BUILD_VERSION
    try:
        from importlib.metadata import version as _v

        return _v("bora")
    except Exception:
        return _BUILD_VERSION


__version__ = _read_version()
