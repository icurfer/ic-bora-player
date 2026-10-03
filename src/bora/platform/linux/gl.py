"""리눅스 GL 진입점 — EGL.

GTK4 는 Wayland 에서 EGL 을 쓰고, X11 폴백에서도 libEGL 이 주소를 돌려준다.
`libGL.so.1` 은 `glGetIntegerv` 같은 핵심 함수를 직접 부르는 데 쓴다.
"""

from __future__ import annotations

import ctypes

GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6


def _load(*names):
    for candidate in names:
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    return None


_egl = _load("libEGL.so.1", "libEGL.so")
_gl = _load("libGL.so.1", "libGL.so")

if _egl is not None:
    _egl.eglGetProcAddress.restype = ctypes.c_void_p
    _egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]


def available() -> bool:
    return _gl is not None and _egl is not None


def get_proc_address(_ctx, name: bytes) -> int:
    return (_egl.eglGetProcAddress(name) or 0) if _egl is not None else 0


def current_fbo() -> int:
    """GtkGLArea 는 자기 FBO 에 그리게 한다 — 0 을 넘기면 화면에 아무것도 안 나온다."""
    if _gl is None:
        return 0
    value = ctypes.c_int()
    _gl.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(value))
    return value.value
