"""Android GL — **미구현.** GTK 가 안드로이드에서 돌지 않으므로 이 층이 의미가 없다.

안드로이드에서 libmpv 를 쓴다면 `SurfaceView` + EGL 로 가고, 그건 Kotlin 쪽 일이다.
"""

from __future__ import annotations


def available() -> bool:
    return False


def get_proc_address(_ctx, _name: bytes) -> int:
    return 0


def current_fbo() -> int:
    return 0
