"""설정·캐시·데이터 폴더와 venv 실행 파일 경로.

경로는 **직접 조립하지 않고 GLib 에 맡긴다.** `~/.local/share` 같은 리눅스 관례를 손으로
이어 붙이면 윈도우에서 엉뚱한 곳(`C:\\Users\\x\\.local\\share`)에 쌓인다.
GLib 은 윈도우에서 `%APPDATA%`·`%LOCALAPPDATA%` 를 돌려준다.
"""

from __future__ import annotations

import os
from pathlib import Path

import gi

from gi.repository import GLib  # noqa: E402

from . import IS_WINDOWS

APP = "bora"


def config_dir() -> Path:
    """설정. `XDG_CONFIG_HOME` 을 먼저 보는 것은 **검증이 격리에 쓰기 때문**이다."""
    base = os.environ.get("XDG_CONFIG_HOME") or GLib.get_user_config_dir()
    return Path(base) / APP


def cache_dir() -> Path:
    return Path(GLib.get_user_cache_dir()) / APP


def data_dir() -> Path:
    """선택 기능(STT 모델·AI venv)이 사는 곳. 커도 되는 자리다."""
    return Path(GLib.get_user_data_dir()) / APP


def venv_python(venv: Path) -> Path:
    """venv 안의 파이썬. 윈도우는 `Scripts/python.exe`, 그 밖은 `bin/python`."""
    if IS_WINDOWS:
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_pip(venv: Path) -> Path:
    if IS_WINDOWS:
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"
