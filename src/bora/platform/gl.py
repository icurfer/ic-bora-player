"""OpenGL 진입점 조회 — PyOpenGL 없이 ctypes 만 쓴다.

libmpv 렌더 컨텍스트에 필요한 것은 `get_proc_address` 콜백과 '현재 프레임버퍼 id'
두 가지뿐이고, 둘 다 ctypes 로 충분하다(기획서 v0.1 §8-3 스파이크, research 3).

**플랫폼마다 조회 방법이 다르다.**

| | 조회 |
|---|---|
| 리눅스 | `libEGL.so.1` 의 `eglGetProcAddress` (Wayland·X11 모두) |
| 윈도우 | `opengl32.dll` 의 `wglGetProcAddress` → 실패하면 `GetProcAddress` |

⚠ 윈도우에서 **폴백이 꼭 있어야 한다.** `wglGetProcAddress` 는 OpenGL 1.1 핵심 함수에
NULL 을 돌려준다. 아래 `current_fbo()` 가 쓰는 `glGetIntegerv` 가 바로 그 1.1 함수다 —
폴백이 없으면 화면이 검게 나오고, 원인을 찾기 어렵다.

> GTK4 가 윈도우에서 ANGLE(EGL)을 쓰도록 구성돼 있으면 EGL 쪽이 맞다. 어느 쪽인지
> 실기에서 확정될 때까지 **둘 다 시도한다**.
"""

from __future__ import annotations

import ctypes
import ctypes.util

from . import IS_WINDOWS

GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6


def _load(*names):
    for candidate in names:
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    return None


if IS_WINDOWS:                                              # pragma: no cover - 윈도우 전용
    _gl = _load("opengl32.dll")
    # ANGLE 로 구성된 GTK 빌드도 있다. 있으면 쓰고, 없으면 WGL 만으로 간다.
    _egl = _load("libEGL.dll")

    if _gl is not None:
        _gl.wglGetProcAddress.restype = ctypes.c_void_p
        _gl.wglGetProcAddress.argtypes = [ctypes.c_char_p]
    if _egl is not None:
        _egl.eglGetProcAddress.restype = ctypes.c_void_p
        _egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetProcAddress.restype = ctypes.c_void_p
    _kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    def _lookup(name: bytes) -> int:
        if _gl is not None:
            found = _gl.wglGetProcAddress(name)
            if found:
                return found
            # OpenGL 1.1 핵심 함수는 위에서 NULL 이 나온다 — DLL 에서 직접 찾는다.
            found = _kernel32.GetProcAddress(
                ctypes.c_void_p(_gl._handle), name)
            if found:
                return found
        if _egl is not None:
            return _egl.eglGetProcAddress(name) or 0
        return 0

else:
    _egl = _load("libEGL.so.1", "libEGL.so")
    _gl = _load("libGL.so.1", "libGL.so")
    if _egl is not None:
        _egl.eglGetProcAddress.restype = ctypes.c_void_p
        _egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]

    def _lookup(name: bytes) -> int:
        return (_egl.eglGetProcAddress(name) or 0) if _egl is not None else 0


def available() -> bool:
    """GL 라이브러리를 열었나 — 못 열었으면 렌더를 시도조차 하지 않는다."""
    return _gl is not None or _egl is not None


def get_proc_address(_ctx, name: bytes) -> int:
    """libmpv 가 OpenGL 함수 주소를 물을 때 부르는 콜백."""
    return _lookup(name)


def current_fbo() -> int:
    """지금 바인딩된 그리기 프레임버퍼 id.

    GtkGLArea 는 자기 FBO 에 그리게 하므로, 기본값 0 을 넘기면 화면에 아무것도 안 나온다.
    """
    value = ctypes.c_int()
    if _gl is None:
        return 0
    _gl.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(value))
    return value.value
