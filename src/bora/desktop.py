"""기본 영상 플레이어 설정.

`.desktop` 을 등록하면 데스크톱이 **알아서 기본 프로그램을 가져가는 경우가 있다**
(2026-09-14 실측: `xdg-mime default` 를 부르지 않았는데 Bora 가 기본이 됐다).
그러니 사용자가 앱 안에서 직접 켜고 끌 수 있어야 한다.

끌 때를 위해 **바꾸기 전의 기본값을 기억**해 둔다. 기억이 없으면 다른 후보 중 하나로 되돌린다.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio  # noqa: E402

from .log import get as get_logger

log = get_logger("desktop")

APP_DESKTOP_ID = "com.icurfer.Bora.desktop"

# 기본으로 잡을 영상 형식. `.desktop` 의 MimeType 과 맞춰 둔다.
VIDEO_TYPES = (
    "video/mp4",
    "video/x-matroska",
    "video/x-msvideo",
    "video/quicktime",
    "video/webm",
    "video/mpeg",
    "video/x-flv",
    "video/x-ms-wmv",
)


def app_info() -> Gio.DesktopAppInfo | None:
    """설치된 Bora 의 .desktop. 없으면 None (등록 전이다)."""
    return Gio.DesktopAppInfo.new(APP_DESKTOP_ID)


def current_default(mime: str) -> str:
    info = Gio.AppInfo.get_default_for_type(mime, False)
    return info.get_id() if info else ""


def is_default() -> bool:
    """주요 형식(mp4·mkv)이 Bora 로 잡혀 있는가."""
    return all(current_default(m) == APP_DESKTOP_ID for m in ("video/mp4", "video/x-matroska"))


def snapshot_defaults() -> dict[str, str]:
    """지금 기본값을 기록해 둔다. Bora 로 바꾸기 전에 부른다."""
    return {m: current_default(m) for m in VIDEO_TYPES
            if current_default(m) and current_default(m) != APP_DESKTOP_ID}


def _candidates(mime: str) -> list[Gio.AppInfo]:
    return [a for a in Gio.AppInfo.get_all_for_type(mime) if a.get_id() != APP_DESKTOP_ID]


def set_default(enable: bool, remembered: dict[str, str] | None = None) -> tuple[bool, str]:
    """-> (성공, 사람이 읽을 메시지)

    enable=False 면 `remembered` 에 적힌 앱으로 되돌린다. 기억이 없으면 후보 중 첫 번째로.
    """
    info = app_info()
    if enable and info is None:
        return False, "먼저 앱으로 등록해야 한다: bash scripts/install-desktop.sh"

    remembered = remembered or {}
    changed = 0
    failed: list[str] = []

    for mime in VIDEO_TYPES:
        target: Gio.AppInfo | None
        if enable:
            target = info
        else:
            wanted = remembered.get(mime)
            target = None
            for candidate in _candidates(mime):
                if wanted and candidate.get_id() == wanted:
                    target = candidate
                    break
            if target is None:
                others = _candidates(mime)
                target = others[0] if others else None
        if target is None:
            continue
        try:
            target.set_as_default_for_type(mime)
            changed += 1
        except Exception as exc:            # 형식 하나가 실패해도 나머지는 계속한다
            log.debug("기본 프로그램 설정 실패 %s: %r", mime, exc)
            failed.append(mime)

    if changed == 0:
        return False, "기본 프로그램을 바꾸지 못했다"
    where = "Bora" if enable else "이전 프로그램"
    note = f"영상 {changed}종을 {where} 로 설정했다"
    if failed:
        note += f" ({len(failed)}종 실패)"
    log.info("%s", note)
    return True, note
