"""OpenGL 진입점 조회 — PyOpenGL 없이 ctypes 만 쓴다.

기획서 §8-3 스파이크에서 확인했다(research 3): libmpv 렌더 컨텍스트에 필요한 것은
`get_proc_address` 콜백과 '현재 프레임버퍼 id' 두 가지뿐이고, 둘 다 ctypes 로 충분하다.
의존성을 하나 줄이려고 PyOpenGL 을 쓰지 않는다.
"""

import ctypes

# GTK4 는 Wayland 에서 EGL 을 쓴다. X11 폴백에서도 libEGL 이 주소를 돌려준다.
_egl = ctypes.CDLL("libEGL.so.1")
_egl.eglGetProcAddress.restype = ctypes.c_void_p
_egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]

_gl = ctypes.CDLL("libGL.so.1")

GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6


def get_proc_address(_ctx, name: bytes) -> int:
    """libmpv 가 OpenGL 함수 주소를 물을 때 부르는 콜백."""
    return _egl.eglGetProcAddress(name)


def current_fbo() -> int:
    """지금 바인딩된 그리기 프레임버퍼 id.

    GtkGLArea 는 자기 FBO 에 그리게 하므로, 기본값 0 을 넘기면 화면에 아무것도 안 나온다.
    """
    value = ctypes.c_int()
    _gl.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(value))
    return value.value
