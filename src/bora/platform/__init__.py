"""플랫폼이 갈리는 지점을 **여기 한 곳에** 모은다 (기획서 v0.6).

본체 코드에 `if windows:` 를 흩으면 유지가 안 된다. 갈림길은 전부 이 패키지 안에 두고,
바깥은 플랫폼을 모르는 채로 함수만 부른다.

지금 갈리는 것은 셋뿐이다 — GL 진입점(`gl`), 경로(`paths`), 데스크톱 연동(`integration`).
나머지 6,900줄은 플랫폼과 무관하다(조사 `docs/research/2026-10-03-windows-port-survey.md`).
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"


def name() -> str:
    """로그·진단에 적을 이름."""
    if IS_WINDOWS:
        return "windows"
    if IS_LINUX:
        return "linux"
    if IS_MAC:
        return "macos"
    return sys.platform


__all__ = ["IS_WINDOWS", "IS_LINUX", "IS_MAC", "name"]
