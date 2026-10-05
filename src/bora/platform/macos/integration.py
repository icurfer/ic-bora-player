"""macOS 데스크톱 연동 — **미구현.**

Launch Services (`LSSetDefaultRoleHandlerForContentType`) 를 쓰면 되지만 파이썬에서
부르려면 PyObjC 의존이 는다. 지금은 끄고 이유를 적는다.
"""

from __future__ import annotations

from ..base import can_set_default, is_default, set_default, snapshot_defaults  # noqa: F401


def unsupported_reason() -> str:
    return "macOS 기본 재생기 설정은 아직 지원하지 않는다 — Finder 에서 정보 가져오기로 바꿀 수 있다"

from ..base import launch_terminal  # noqa: F401
