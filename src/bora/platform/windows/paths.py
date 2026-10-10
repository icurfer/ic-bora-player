"""윈도우 경로 — `%APPDATA%` · `%LOCALAPPDATA%`.

GLib 이 알아서 올바른 자리를 돌려준다. 직접 조립하지 않는다.
venv 레이아웃만 posix 와 다르다 — `Scripts/python.exe`.
"""

from __future__ import annotations

import os
import sysconfig
from pathlib import Path

import gi  # noqa: F401

from gi.repository import GLib  # noqa: E402

APP = "bora"


def config_dir() -> Path:
    # 검증이 격리에 쓰므로 XDG_CONFIG_HOME 을 윈도우에서도 존중한다.
    base = os.environ.get("XDG_CONFIG_HOME") or GLib.get_user_config_dir()
    return Path(base) / APP


def cache_dir() -> Path:
    return Path(GLib.get_user_cache_dir()) / APP


def data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / APP


def _scripts_dir(venv: Path) -> Path:
    for folder in ("Scripts", "bin"):
        if (venv / folder / "python.exe").is_file():
            return venv / folder
    # MSYS2도 Windows 네이티브 Python이지만 venv에는 bin을 사용한다.
    folder = "bin" if sysconfig.get_platform().startswith("mingw") else "Scripts"
    return venv / folder


def venv_python(venv: Path) -> Path:
    return _scripts_dir(venv) / "python.exe"


def venv_pip(venv: Path) -> Path:
    return _scripts_dir(venv) / "pip.exe"
