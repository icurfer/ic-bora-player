"""로깅 — 버그를 눈으로 볼 수 있게 한다.

기본은 조용하고(WARNING), `BORA_DEBUG=1` 이나 `--debug` 를 주면 앱과 **libmpv 로그를 함께** 쏟는다.
자막이 왜 저렇게 나오는지는 libmpv 가 무엇을 열고 무슨 코드페이지를 썼는지 봐야 알 수 있어서,
mpv 로그를 파이썬 로거로 끌어온다.

  PYTHONPATH=src python3 -m bora --debug <파일>
  BORA_DEBUG=1 PYTHONPATH=src python3 -m bora <파일>
  BORA_LOG_FILE=/tmp/bora.log ...      # 파일로도 남긴다
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


def get(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def mpv_log_handler(level: str, prefix: str, text: str) -> None:
    """python-mpv 가 넘겨주는 libmpv 로그를 파이썬 로거로 옮긴다."""
    get("mpv").log(_MPV_LEVEL.get(level, logging.DEBUG), "[%s] %s", prefix, text.rstrip())
