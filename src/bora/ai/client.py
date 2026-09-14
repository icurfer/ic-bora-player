"""AI 질의 — 별도 프로세스를 띄우고 답을 스트리밍으로 받는다."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from ..log import get as get_logger
from .context import Question, build, to_request

log = get_logger("ai.client")

MODELS = (
    ("claude-opus-5", "가장 똑똑함 · $5/$25 per 1M"),
    ("claude-sonnet-5", "빠르고 저렴 · $2/$10 per 1M"),
)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.home() / ".local" / "share" / "bora"


def venv_python() -> Path:
    return repo_root() / ".venv" / "bin" / "python"


def sdk_installed() -> bool:
    python = venv_python()
    if not python.is_file():
        return False
    try:
        return subprocess.run([str(python), "-c", "import anthropic"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def has_credentials() -> bool:
    """앱은 키를 저장하지 않는다. 환경변수나 `ant` 프로필이 있는지만 본다."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    if (Path.home() / ".config" / "anthropic").is_dir():
        return True
    return bool(shutil.which("ant"))


def ensure_ready() -> tuple[bool, str]:
    if not sdk_installed():
        return False, "AI 질의가 설치되지 않았다.\nbash scripts/install-ai.sh"
    if not has_credentials():
        return False, ("API 키가 없다. 앱은 키를 저장하지 않는다 — 둘 중 하나를 쓴다:\n"
                       "  export ANTHROPIC_API_KEY=sk-ant-...\n"
                       "  ant auth login")
    return True, "준비됨"


class AskRunner:
    """질문 하나를 던지고 답을 조각으로 받는다. 한 번에 하나만 돈다."""

    def __init__(self, on_delta=None, on_done=None, on_error=None) -> None:
        self.on_delta = on_delta        # (텍스트 조각)
        self.on_done = on_done          # (비용, usage dict)
        self.on_error = on_error        # (메시지)
        self._proc: subprocess.Popen | None = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ask(self, question: Question) -> bool:
        if self.running:
            return False
        ready, hint = ensure_ready()
        if not ready:
            self._fail(hint)
            return False

        payload = json.dumps(to_request(build(question)), ensure_ascii=False)
        worker = Path(__file__).with_name("worker.py")
        try:
            self._proc = subprocess.Popen(
                [str(venv_python()), str(worker)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except OSError as exc:
            self._fail(f"AI 프로세스를 띄우지 못했다: {exc}")
            return False

        self._cancelled = False
        threading.Thread(target=self._pump, args=(payload,), daemon=True).start()
        log.info("질문: %s (%s)", question.text[:40], question.model)
        return True

    def cancel(self) -> None:
        if self.running:
            self._cancelled = True
            self._proc.terminate()

    def _pump(self, payload: str) -> None:
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
        except OSError:
            pass
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "delta" and self.on_delta:
                self.on_delta(event.get("text") or "")
            elif kind == "done" and self.on_done:
                self.on_done(float(event.get("cost") or 0.0), event.get("usage") or {})
            elif kind == "error":
                self._fail(str(event.get("message") or "알 수 없는 오류"))
        code = proc.wait()
        if self._cancelled:
            self._fail("취소됨")
        elif code != 0:
            tail = (proc.stderr.read() or "").strip()[-300:] if proc.stderr else ""
            if tail:
                self._fail(f"AI 실패 (코드 {code}) {tail}")

    def _fail(self, message: str) -> None:
        log.warning("AI: %s", message)
        if self.on_error:
            self.on_error(message)
