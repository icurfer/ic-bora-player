"""macOS 경로 — GLib 에 맡긴다.

GLib 은 맥에서 `~/Library/Application Support` 계열을 돌려준다. venv 는 posix 와 같다.
**미검증** — 맥에서 확인하지 않았다.
"""

from __future__ import annotations

import os
from pathlib import Path

import gi  # noqa: F401

from gi.repository import GLib  # noqa: E402

from ..base import venv_pip_posix, venv_python_posix

APP = "bora"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or GLib.get_user_config_dir()
    return Path(base) / APP


def cache_dir() -> Path:
    return Path(GLib.get_user_cache_dir()) / APP


def data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / APP


venv_python = venv_python_posix
venv_pip = venv_pip_posix
