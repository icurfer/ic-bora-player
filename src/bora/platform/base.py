"""플랫폼 구현이 지켜야 할 모양.

각 플랫폼 폴더(`linux/` `windows/` `macos/` `android/`)는 아래 이름을 같은 뜻으로 제공한다.
추상 클래스를 쓰지 않는 이유는 모듈 단위로 갈라지는 편이 읽기 쉽고, 플랫폼마다 "없는 기능"을
빈 함수로 두기 쉬워서다.

## gl — OpenGL 진입점
| 이름 | 뜻 |
|---|---|
| `available() -> bool` | GL 라이브러리를 열었나. False 면 렌더를 시도하지 않는다 |
| `get_proc_address(ctx, name: bytes) -> int` | libmpv 가 함수 주소를 물을 때의 콜백 |
| `current_fbo() -> int` | 지금 바인딩된 그리기 프레임버퍼 id |

## paths — 사용자 폴더
| 이름 | 뜻 |
|---|---|
| `config_dir()` | 설정(`state.json`) |
| `cache_dir()` | 지워도 되는 것(썸네일) |
| `data_dir()` | 선택 기능(STT 모델·AI venv) — 커도 되는 자리 |
| `venv_python(venv)` / `venv_pip(venv)` | venv 안의 실행 파일 |

## integration — 데스크톱 연동
| 이름 | 뜻 |
|---|---|
| `can_set_default() -> bool` | 기본 재생기 설정을 지원하나 |
| `is_default() -> bool` | 지금 기본인가 |
| `snapshot_defaults() -> dict[str, str]` | 바꾸기 전 기본값 — 끌 때 정확히 되돌리려고 |
| `set_default(enable, remembered=None) -> tuple[bool, str]` | 바꾼다. (성공, 사람이 읽을 말) |
| `unsupported_reason() -> str` | 지원하지 않을 때 **화면에 적을 이유** |

시그니처는 **리눅스 구현(동작하는 코드)에 맞췄다.** 명세를 먼저 쓰고 구현을 맞추면
이미 도는 것을 건드리게 된다.

마지막 항목이 중요하다. 이 저장소의 규칙은 **조용한 실패를 만들지 않는 것**이다 —
못 하는 기능은 끄되 왜 못 하는지 사람이 읽을 말로 남긴다.
"""

from __future__ import annotations

from pathlib import Path


# ── integration 의 기본값 — 지원하지 않는 플랫폼은 이것을 그대로 쓴다 ──────────
def can_set_default() -> bool:
    return False


def is_default() -> bool:
    return False


def snapshot_defaults() -> dict:
    return {}


def set_default(enable: bool, remembered: dict | None = None):   # noqa: ARG001
    return False, unsupported_reason()


def unsupported_reason() -> str:
    return "이 플랫폼에서는 기본 재생기 설정을 지원하지 않는다"


# ── paths 의 공통부 — venv 레이아웃은 윈도우만 다르다 ──────────────────────────
def venv_python_posix(venv: Path) -> Path:
    return venv / "bin" / "python"


def venv_pip_posix(venv: Path) -> Path:
    return venv / "bin" / "pip"
