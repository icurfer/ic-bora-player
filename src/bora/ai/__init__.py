"""AI 질의 — 메모에 적은 것을 그 자리에서 물어본다.

**선택 기능이다.** 설치·키가 없어도 재생·메모·자막은 그대로 동작하고 이 기능만 비활성이다.
**자동으로 부르지 않는다** — 돈이 나가는 기능은 사용자가 누를 때만 나간다(기획서 v0.3 §4-5).
"""

from .client import MODELS, AskRunner, ensure_ready, has_credentials, sdk_installed
from .context import Question, build, to_request

__all__ = [
    "MODELS", "AskRunner", "Question", "build", "ensure_ready",
    "has_credentials", "sdk_installed", "to_request",
]
