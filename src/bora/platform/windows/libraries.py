"""Windows DLL 이름과 위치. 자막 판정 로직은 공통 모듈에 유지한다."""
import ctypes.util


def uchardet_library() -> str:
    return (ctypes.util.find_library("uchardet")
            or ctypes.util.find_library("libuchardet")
            or ctypes.util.find_library("libuchardet-0")
            or "libuchardet.dll")
