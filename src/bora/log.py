"""로깅 — 버그를 눈으로 볼 수 있게 한다.

기본은 조용하고(WARNING), `BORA_DEBUG=1` 이나 `--debug` 를 주면 앱과 **libmpv 로그를 함께** 쏟는다.
자막이 왜 저렇게 나오는지는 libmpv 가 무엇을 열고 무슨 코드페이지를 썼는지 봐야 알 수 있어서,
mpv 로그를 파이썬 로거로 끌어온다.

  PYTHONPATH=src python3 -m bora --debug <파일>
  BORA_DEBUG=1 PYTHONPATH=src python3 -m bora <파일>
  BORA_LOG_FILE=/tmp/bora.log ...      # 파일로도 남긴다

앱 안에서도 바꿀 수 있다(메뉴 → 로그). `set_level()` 은 **즉시** 적용된다 —
버그는 재현되는 그 순간에 등급을 올려야 잡히지, 재시작하면 증상이 사라진다.
명령줄·환경변수는 시작 등급을 정하고, 설정은 그 뒤로 이긴다.
"""

from __future__ import annotations

import logging
import os
import sys

LOGGER_NAME = "bora"
# mpv 의 로그 등급을 파이썬 등급으로 옮긴다
_MPV_LEVEL = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "status": logging.INFO,
    "v": logging.DEBUG,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,
}


def debug_enabled(argv: list[str] | None = None) -> bool:
    argv = sys.argv if argv is None else argv
    if "--debug" in argv:
        return True
    return os.environ.get("BORA_DEBUG", "").lower() not in ("", "0", "no", "false")


def setup(debug: bool | None = None) -> logging.Logger:
    """루트 로거를 한 번만 설정하고 bora 로거를 돌려준다."""
    if debug is None:
        debug = debug_enabled()
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_bora_configured", False):
        return logger

    level = logging.DEBUG if debug else logging.WARNING
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%H:%M:%S")

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    path = os.environ.get("BORA_LOG_FILE")
    if path:
        try:
            fh = logging.FileHandler(path, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError as exc:
            logger.warning("로그 파일을 열지 못했다 %s: %s", path, exc)

    logger.setLevel(level)
    logger.propagate = False
    logger._bora_configured = True          # type: ignore[attr-defined]
    return logger


# 설정에 보여 줄 등급. 값은 state.json 에 문자열로 저장한다.
LEVELS = (
    ("warning", "조용히", "문제가 있을 때만 (기본)"),
    ("info", "보통", "무엇을 열고 무엇을 했는지"),
    ("debug", "자세히", "libmpv 로그까지 — 버그 잡을 때"),
)
_LEVEL_VALUES = {
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def level_name(logger: logging.Logger | None = None) -> str:
    """지금 등급의 설정용 이름."""
    value = (logger or get()).getEffectiveLevel()
    for name, number in _LEVEL_VALUES.items():
        if number == value:
            return name
    return "debug" if value <= logging.DEBUG else "warning"


def set_level(name: str) -> str:
    """등급을 **즉시** 바꾼다. 알 수 없는 이름은 무시하고 현재 등급을 돌려준다."""
    number = _LEVEL_VALUES.get((name or "").lower())
    logger = get()
    if number is None:
        return level_name(logger)
    logger.setLevel(number)
    logger.log(max(number, logging.INFO), "로그 등급: %s", name)
    return name


def log_file_path() -> str:
    """파일로도 남기고 있다면 그 경로. 설정 화면에서 '어디를 보면 되는지' 알려 준다."""
    for handler in get().handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return ""


def add_log_file(path: str) -> str:
    """로그를 파일로도 남기기 시작한다. 실패하면 빈 문자열."""
    logger = get()
    existing = log_file_path()
    if existing == str(path):
        return existing
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s", "%H:%M:%S")
    try:
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        logger.warning("로그 파일을 열지 못했다 %s: %s", path, exc)
        return ""
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.info("로그 파일: %s", path)
    return str(path)


def get(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def mpv_log_handler(level: str, prefix: str, text: str) -> None:
    """python-mpv 가 넘겨주는 libmpv 로그를 파이썬 로거로 옮긴다."""
    get("mpv").log(_MPV_LEVEL.get(level, logging.DEBUG), "[%s] %s", prefix, text.rstrip())
