"""macOS GL 진입점 — **미구현.**

애플은 OpenGL 을 deprecated 로 두었고 GTK4 의 Quartz 백엔드가 GL 컨텍스트를 어떻게
주는지 확인하지 않았다. 후보는 `/System/Library/Frameworks/OpenGL.framework` 를
`ctypes.CDLL` 로 열고 `dlsym` 으로 찾는 방식이다.

**지금은 `available()` 이 False 를 돌려 렌더를 시도하지 않게 한다.**
추측으로 짠 코드를 넣어 두면 나중에 "되는 줄 알았는데 안 되는" 상태가 된다.
"""

from __future__ import annotations


def available() -> bool:
    return False


def get_proc_address(_ctx, _name: bytes) -> int:
    return 0


def current_fbo() -> int:
    return 0
