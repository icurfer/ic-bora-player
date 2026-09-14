# -*- coding: utf-8 -*-
"""텍스트 추출 회귀 테스트.

**설치돼 있지 않아도 앱이 멀쩡해야 한다**(기획서 v0.3 §2-1 — 선택 기능).
실제 추출은 무겁고 모델이 필요해 여기서 돌리지 않는다. 시간 변환과 상태 판단만 본다.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bora.stt import MODELS, ensure_ready, install_hint, is_installed, venv_python  # noqa: E402
from bora.stt.runner import ExtractRunner, Extraction  # noqa: E402

WORKER = ROOT / "src" / "bora" / "stt" / "worker.py"


def test_models_listed_with_size() -> None:
    names = [m[0] for m in MODELS]
    assert names == ["tiny", "base", "small", "medium", "large-v3"]
    assert all(len(m) == 3 and m[2] for m in MODELS), "용량 안내가 있어야 고를 수 있다"


def test_ensure_ready_returns_hint_when_missing(monkeypatch) -> None:
    """미설치 상태에서 예외가 아니라 안내를 돌려줘야 한다."""
    monkeypatch.setattr("bora.stt.install.is_installed", lambda: False)
    import bora.stt.install as install_mod

    monkeypatch.setattr(install_mod, "is_installed", lambda: False)
    ok, hint = install_mod.ensure_ready()
    assert ok is False
    assert "install-stt" in hint or "ffmpeg" in hint


def test_install_hint_names_the_script() -> None:
    assert "install-stt.sh" in install_hint()


def test_venv_path_is_inside_repo() -> None:
    assert venv_python().name == "python"
    assert ".venv-stt" in str(venv_python())


def test_runner_reports_error_when_worker_missing(tmp_path, monkeypatch) -> None:
    """실행 파일이 없어도 예외로 죽지 않고 오류를 알려야 한다."""
    monkeypatch.setattr("bora.stt.runner.venv_python", lambda: tmp_path / "없는파이썬")
    errors: list[str] = []
    runner = ExtractRunner(on_error=errors.append)
    started = runner.start(Extraction(tmp_path / "a.mp4", tmp_path / "a.srt"))
    assert started is False
    assert errors and "띄우지 못했다" in errors[0]


# ── worker 는 독립 실행이라 직접 호출해 본다 ────────────────────────────
def test_worker_srt_time_format() -> None:
    """SRT 시간 형식이 어긋나면 자막이 통째로 안 붙는다."""
    code = (
        f"import sys; sys.path.insert(0, {str(WORKER.parent)!r});"
        "from worker import to_srt_time;"
        "print(to_srt_time(0), to_srt_time(3723.456), to_srt_time(-5))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["00:00:00,000", "01:02:03,456", "00:00:00,000"]


def test_worker_reports_missing_dependency(tmp_path) -> None:
    """faster-whisper 가 없는 파이썬으로 돌리면 JSON 오류를 뱉어야 한다(죽지 않고)."""
    if is_installed() and sys.executable == str(venv_python()):
        pytest.skip("이 파이썬에는 faster-whisper 가 있다")
    out = subprocess.run(
        [sys.executable, str(WORKER), str(tmp_path / "a.mp4"), str(tmp_path / "a.srt")],
        capture_output=True, text=True, timeout=60,
    )
    assert '"type": "error"' in out.stdout
    assert "faster-whisper" in out.stdout
