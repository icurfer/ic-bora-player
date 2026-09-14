"""음성 텍스트 추출 — 자막이 없는 강의를 살린다.

**선택 기능이다.** 설치하지 않아도 플레이어는 그대로 동작하고, 메뉴만 '설치 필요'로 바뀐다
(기획서 v0.3 §2-1). 무거운 의존성(faster-whisper, ctranslate2, 모델 파일)을 앱 본체와 섞지 않으려고
별도 venv(`.venv-stt`)에 두고 **별도 프로세스**로 돌린다.
"""

from .install import STT_VENV, ensure_ready, install_hint, is_installed, venv_python
from .runner import MODELS, Extraction, ExtractRunner

__all__ = [
    "MODELS", "STT_VENV", "ExtractRunner", "Extraction",
    "ensure_ready", "install_hint", "is_installed", "venv_python",
]
