"""`.venv-stt` 준비 — 텍스트 추출용 별도 환경.

시스템 파이썬에는 넣을 수 없다(PEP 668). 그리고 넣어서도 안 된다 — faster-whisper 는
ctranslate2 를 끌고 오고 모델 파일이 수백 MB 다. 쓰지 않는 사람에게 그 부담을 지우지 않는다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from ..log import get as get_logger

log = get_logger("stt.install")

STT_VENV = ".venv-stt"


def repo_root() -> Path:
    """저장소 뿌리. 설치본에서는 사용자 데이터 폴더로 떨어진다."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.home() / ".local" / "share" / "bora"


def venv_dir() -> Path:
    return repo_root() / STT_VENV


def venv_python() -> Path:
    return venv_dir() / "bin" / "python"


def is_installed() -> bool:
    """faster-whisper 가 실제로 import 되는지까지 본다. 폴더만 있는 경우가 있다."""
    python = venv_python()
    if not python.is_file():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", "import faster_whisper"],
            capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_hint() -> str:
    return f"bash scripts/install-stt.sh   ({STT_VENV} 에 faster-whisper 를 넣는다)"


def ensure_ready() -> tuple[bool, str]:
    """-> (쓸 수 있나, 사람이 읽을 안내)"""
    if is_installed():
        return True, "준비됨"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg 가 필요하다: sudo apt install ffmpeg"
    return False, f"음성 추출이 설치되지 않았다.\n{install_hint()}"


def install(model: str = "", on_line=None) -> bool:
    """venv 를 만들고 faster-whisper 를 넣는다. 오래 걸리므로 UI 에서 직접 부르지 않는다."""
    target = venv_dir()
    steps = [
        [sys.executable, "-m", "venv", str(target)],
        [str(target / "bin" / "pip"), "install", "--upgrade", "pip"],
        [str(target / "bin" / "pip"), "install", "faster-whisper"],
    ]
    for step in steps:
        log.info("설치: %s", " ".join(step[:3]))
        proc = subprocess.Popen(step, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        for line in proc.stdout or []:
            if on_line:
                on_line(line.rstrip())
        if proc.wait() != 0:
            return False
    return True
