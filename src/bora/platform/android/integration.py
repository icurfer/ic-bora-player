"""Android 데스크톱 연동 — 해당 없음.

안드로이드의 '기본 앱'은 매니페스트의 인텐트 필터로 선언하고 사용자가 고른다.
앱 안에서 바꾸는 개념이 아니다.
"""

from __future__ import annotations

from ..base import can_set_default, is_default, set_default, snapshot_defaults  # noqa: F401


def unsupported_reason() -> str:
    return "안드로이드는 기본 앱을 시스템 설정에서 고른다"

from ..base import launch_terminal  # noqa: F401
