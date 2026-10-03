"""Android 경로 — **미구현.**

안드로이드는 앱 전용 저장소(`getFilesDir()`·`getCacheDir()`)를 쓰고, 사용자 파일은
경로가 아니라 **SAF URI** 로 다룬다. 파이썬에서 임의 경로를 여는 지금 구조가
그대로 통하지 않는다.

일단 앱 내부 폴더를 쓰는 모양으로 둔다. 실제로 쓰게 되면 호스트(Kotlin)가 넘겨준
경로를 환경변수로 받는 쪽이 맞다.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..base import venv_pip_posix, venv_python_posix

APP = "bora"


def _root() -> Path:
    # 호스트 앱이 넘겨주는 것을 먼저 본다. 없으면 홈 아래.
    base = os.environ.get("BORA_ANDROID_FILES_DIR")
    return Path(base) if base else Path.home() / ".bora"


def config_dir() -> Path:
    return _root() / "config"


def cache_dir() -> Path:
    return _root() / "cache"


def data_dir() -> Path:
    return _root() / "data"


venv_python = venv_python_posix
venv_pip = venv_pip_posix
