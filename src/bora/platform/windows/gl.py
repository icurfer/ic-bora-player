"""윈도우 GL 진입점 — WGL (+ ANGLE 폴백).

⚠ **두 단계가 필요하다.** `wglGetProcAddress` 는 확장 함수만 돌려주고 **OpenGL 1.1 핵심
함수에는 NULL 을 준다.** `current_fbo()` 가 쓰는 `glGetIntegerv` 가 바로 그 1.1 함수다 —
폴백이 없으면 FBO 를 못 읽어 **화면이 검게 나온다.** 리눅스에서 겪었던 증상과 같은
모양이라 원인을 알아보기 어렵다.

GTK4 빌드가 ANGLE(EGL) 로 구성돼 있을 수도 있어 `libEGL.dll` 도 시도한다.
실기에서 `GDK_DEBUG=opengl` 로 어느 쪽인지 확인할 것.

**재생 미검증** — Windows DLL 로드와 함수 단위 검사는 했으나 GTK 렌더는 확인하지 못했다.
"""

from __future__ import annotations

import ctypes

GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6


def _load(*names):
    for candidate in names:
        try:
            loader = getattr(ctypes, "WinDLL", ctypes.CDLL)
            return loader(candidate)
        except OSError:
            continue
    return None


_gl = _load("opengl32.dll")
_egl = _load("libEGL.dll")          # ANGLE 구성일 때만 있다
_gles = _load("libGLESv2.dll")

if _gl is not None:
    _gl.wglGetProcAddress.restype = ctypes.c_void_p
    _gl.wglGetProcAddress.argtypes = [ctypes.c_char_p]
    _gl.wglGetCurrentContext.restype = ctypes.c_void_p
    _gl.wglGetCurrentContext.argtypes = []
if _egl is not None:
    _egl.eglGetProcAddress.restype = ctypes.c_void_p
    _egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
    _egl.eglGetCurrentContext.restype = ctypes.c_void_p
    _egl.eglGetCurrentContext.argtypes = []

try:                                            # pragma: no cover - 윈도우 전용
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetProcAddress.restype = ctypes.c_void_p
    _kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
except (AttributeError, OSError):               # 윈도우가 아니면 WinDLL 이 없다
    _kernel32 = None


def available() -> bool:
    return _gl is not None or _egl is not None


def _backend():
    # DLL 존재와 현재 컨텍스트는 다르다. ANGLE 사용 시 opengl32도 설치되어 있다.
    if _egl is not None and _egl.eglGetCurrentContext():
        return "egl"
    if _gl is not None and _gl.wglGetCurrentContext():
        return "wgl"
    return None


def _export(library, name):
    if library is not None and _kernel32 is not None:
        return _kernel32.GetProcAddress(ctypes.c_void_p(library._handle), name) or 0
    return 0


def get_proc_address(_ctx, name: bytes) -> int:
    backend = _backend()
    if backend == "wgl":
        found = _gl.wglGetProcAddress(name)
        # 일부 드라이버는 NULL 외에도 이 값을 실패 표시로 반환한다.
        if found not in (None, 0, 1, 2, 3, -1, ctypes.c_void_p(-1).value):
            return found
        # ↓ OpenGL 1.1 핵심 함수는 위에서 NULL 이다. DLL 에서 직접 찾는다.
        return _export(_gl, name)
    if backend == "egl":
        return _egl.eglGetProcAddress(name) or _export(_gles, name)
    return 0


def current_fbo() -> int:
    address = get_proc_address(None, b"glGetIntegerv")
    if not address:
        return 0
    factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
    query = factory(None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))(address)
    value = ctypes.c_int()
    query(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(value))
    return value.value
