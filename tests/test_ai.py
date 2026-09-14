# -*- coding: utf-8 -*-
"""AI 질의 회귀 테스트.

**실제 API 를 부르지 않는다** — 돈이 나가고 키가 필요하다. 대신 두 가지를 고정한다:
1. 맥락 조립이 기획서 §4-4 의 순서(고정 → 가변)를 지키는가 — 캐시가 걸리는 조건이다
2. 설치·키가 없을 때 **예외가 아니라 안내**를 돌려주는가 — 앱이 멀쩡해야 한다
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bora.ai import MODELS, Question, build, to_request  # noqa: E402
from bora.ai import client as client_mod  # noqa: E402
from bora.ai.context import MIN_CACHE_CHARS, SYSTEM, WINDOW_SECONDS  # noqa: E402

WORKER = ROOT / "src" / "bora" / "ai" / "worker.py"

SRT = "".join(
    "%d\n00:%02d:%02d,000 --> 00:%02d:%02d,000\n%d번째 문장입니다. 합의 알고리즘 이야기.\n\n"
    % (i, i // 60, i % 60, (i + 5) // 60, (i + 5) % 60, i)
    for i in range(1, 200)
)


def _subtitle(tmp_path: Path) -> Path:
    path = tmp_path / "lecture.srt"
    path.write_text(SRT, encoding="utf-8")
    return path


# ── 맥락 조립 ────────────────────────────────────────────────────────────
def test_system_tells_model_not_to_guess() -> None:
    assert "추측하지" in SYSTEM and "한국어" in SYSTEM


def test_long_subtitle_is_cached(tmp_path: Path) -> None:
    """긴 자막은 캐시 블록으로 올라가야 반복 질문이 싸진다."""
    q = build(Question(text="질문", position=60, subtitle_path=_subtitle(tmp_path)))
    request = to_request(q)
    assert len(request["system"]) == 2
    assert request["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert len(q.full_subtitle) >= MIN_CACHE_CHARS


def test_short_subtitle_is_not_cached(tmp_path: Path) -> None:
    """짧으면 캐시가 걸리지 않는다 — 괜히 블록만 늘리지 않는다."""
    path = tmp_path / "tiny.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n짧다\n", encoding="utf-8")
    request = to_request(build(Question(text="질문", subtitle_path=path)))
    assert len(request["system"]) == 1


def test_cacheable_part_comes_first(tmp_path: Path) -> None:
    """캐싱은 접두 일치다. 고정 부분이 앞, 바뀌는 부분이 뒤여야 한다."""
    q = build(Question(text="질문", position=60, subtitle_path=_subtitle(tmp_path)))
    request = to_request(q)
    assert request["system"][0]["text"] == SYSTEM        # 가장 고정적인 것이 맨 앞
    assert "cache_control" not in request["system"][0]
    assert "질문" in request["user"]                      # 매번 바뀌는 것은 user 로


def test_nearby_window_is_limited(tmp_path: Path) -> None:
    """자막 전체가 아니라 지금 대목만 user 에 넣는다.

    표본 자막은 약 200초 길이다. 창(앞뒤 300초)보다 짧으면 전체가 들어오므로,
    창이 실제로 잘라내는지 보려면 **창보다 먼 시점**을 골라야 한다.
    """
    q = build(Question(text="질문", position=30, subtitle_path=_subtitle(tmp_path)))
    assert q.nearby_subtitle
    assert WINDOW_SECONDS == 300

    far = build(Question(text="질문", position=5000, subtitle_path=_subtitle(tmp_path)))
    assert far.nearby_subtitle == "", "창 밖 시점에서는 부근 자막이 비어야 한다"
    assert far.full_subtitle, "그래도 전체 자막은 캐시로 간다"


def test_question_still_goes_when_no_nearby_subtitle(tmp_path: Path) -> None:
    """자막 범위 밖에서 물어도 질문 자체는 보내져야 한다."""
    q = build(Question(text="이건 무슨 뜻이지", position=9999,
                       subtitle_path=_subtitle(tmp_path)))
    request = to_request(q)
    assert "이건 무슨 뜻이지" in request["user"]


def test_note_excerpt_follows_cursor() -> None:
    note = "\n".join(f"{i}번째 줄" for i in range(100))
    q = build(Question(text="질문", note_text=note, note_line=50))
    assert "50번째 줄" in q.note_excerpt
    assert "0번째 줄\n1번째" not in q.note_excerpt        # 먼 곳은 안 들어간다


def test_missing_subtitle_is_not_an_error() -> None:
    q = build(Question(text="질문", subtitle_path=Path("/없는/파일.srt")))
    assert q.full_subtitle == ""
    assert "질문" in to_request(q)["user"]


def test_models_have_price_hint() -> None:
    assert MODELS[0][0] == "claude-opus-5"
    assert all("$" in note for _id, note in MODELS)


# ── 설치·키가 없을 때 ────────────────────────────────────────────────────
def test_ensure_ready_reports_missing_sdk(monkeypatch) -> None:
    monkeypatch.setattr(client_mod, "sdk_installed", lambda: False)
    ok, hint = client_mod.ensure_ready()
    assert ok is False and "install-ai.sh" in hint


def test_ensure_ready_reports_missing_key(monkeypatch) -> None:
    monkeypatch.setattr(client_mod, "sdk_installed", lambda: True)
    monkeypatch.setattr(client_mod, "has_credentials", lambda: False)
    ok, hint = client_mod.ensure_ready()
    assert ok is False
    assert "ANTHROPIC_API_KEY" in hint and "저장하지 않는다" in hint


def test_ask_fails_cleanly_without_setup(monkeypatch) -> None:
    """준비가 안 됐을 때 예외로 죽지 않고 안내를 돌려준다."""
    monkeypatch.setattr(client_mod, "sdk_installed", lambda: False)
    errors: list[str] = []
    runner = client_mod.AskRunner(on_error=errors.append)
    assert runner.ask(Question(text="질문")) is False
    assert errors and "install-ai" in errors[0]


def test_app_never_stores_the_key() -> None:
    """키를 설정 파일에 넣는 코드가 있으면 안 된다."""
    from bora.state import Settings

    fields = set(Settings.__dataclass_fields__)
    assert not any("key" in f or "token" in f or "secret" in f for f in fields), fields


# ── worker (독립 실행) ───────────────────────────────────────────────────
def test_worker_reports_bad_request() -> None:
    out = subprocess.run([sys.executable, str(WORKER)], input="이건 JSON 이 아니다",
                         capture_output=True, text=True, timeout=60)
    assert '"type": "error"' in out.stdout


def test_worker_cost_estimate() -> None:
    code = "\n".join([
        f"import sys; sys.path.insert(0, {str(WORKER.parent)!r})",
        "from worker import estimate_cost",
        "class U:",
        "    input_tokens = 1_000_000",
        "    output_tokens = 0",
        "    cache_creation_input_tokens = 0",
        "    cache_read_input_tokens = 0",
        "print(round(estimate_cost('claude-opus-5', U()), 4))",
    ])
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "5.0"          # 입력 100만 토큰 = $5
