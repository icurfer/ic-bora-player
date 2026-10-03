"""윈도우 데스크톱 연동 — **아직 지원하지 않는다.**

기본 재생기 설정은 윈도우에서 레지스트리(`HKCU\\Software\\Classes`)와
`SetUserFTA` 수준의 해시 검증까지 걸려 있어, 리눅스의 `xdg-mime` 처럼 간단하지 않다.
윈도우 10 부터는 **기본 앱을 프로그램이 임의로 바꾸는 것을 막는다** — 설정 앱에서
사용자가 직접 고르게 하는 것이 정석이다.

기획 v0.6 범위 밖이다(§2-2). 메뉴는 끄고 아래 이유를 화면에 적는다.
"""

from __future__ import annotations

from ..base import can_set_default, is_default, set_default, snapshot_defaults  # noqa: F401


def unsupported_reason() -> str:
    return ("윈도우는 기본 앱을 설정 앱에서 직접 고르게 한다 — "
            "설정 → 앱 → 기본 앱에서 Bora 를 고르면 된다")
