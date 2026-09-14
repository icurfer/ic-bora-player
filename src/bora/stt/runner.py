"""추출 실행 — 별도 프로세스를 띄우고 진행률을 받는다.

모델 로딩과 추출이 무거워 앱 안에서 돌리면 창이 멈춘다(기획서 v0.3 §2-1).
`.venv-stt` 의 파이썬으로 `worker.py` 를 띄우고, stdout 의 JSON 을 읽어 진행률을 올린다.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from ..log import get as get_logger
from .install import venv_python

log = get_logger("stt.runner")

# (이름, 설명, 대략 용량). 기본은 small — 1시간 강의를 CPU 로 감당할 만하다.
MODELS = (
    ("tiny", "가장 빠름 · 정확도 낮음", "75 MB"),
    ("base", "빠름", "145 MB"),
    ("small", "권장 — 속도와 정확도 절충", "480 MB"),
    ("medium", "정확 · 느림", "1.5 GB"),
    ("large-v3", "가장 정확 · 매우 느림", "3 GB"),
)


@dataclass
class Extraction:
    video: Path
    output: Path
    model: str = "small"
    language: str = "ko"


class ExtractRunner:
    """한 번에 하나만 돌린다. 취소할 수 있다."""

    def __init__(self, on_progress=None, on_done=None, on_error=None) -> None:
        self.on_progress = on_progress      # (초, 전체초, 큐수)
        self.on_done = on_done              # (출력 경로, 큐 수)
        self.on_error = on_error            # (메시지)
        self._proc: subprocess.Popen | None = None
        self._cancelled = False
        self.duration = 0.0

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, job: Extraction) -> bool:
        if self.running:
            return False
        worker = Path(__file__).with_name("worker.py")
        command = [
            str(venv_python()), str(worker), str(job.video), str(job.output),
            "--model", job.model,
        ]
        if job.language:
            command += ["--lang", job.language]
        log.info("추출 시작: %s (%s)", job.video.name, job.model)
        try:
            self._proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except OSError as exc:
            self._fail(f"추출 프로세스를 띄우지 못했다: {exc}")
            return False
        self._cancelled = False
        threading.Thread(target=self._pump, daemon=True).start()
        return True

    def cancel(self) -> None:
        if self.running:
            self._cancelled = True
            log.info("추출 취소")
            self._proc.terminate()

    # ── 내부 ─────────────────────────────────────────────────────────────
    def _pump(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            self._handle(event)
        code = proc.wait()
        if self._cancelled:
            self._fail("취소됨")
        elif code != 0:
            tail = (proc.stderr.read() or "").strip()[-400:] if proc.stderr else ""
            self._fail(f"추출 실패 (코드 {code}) {tail}")

    def _handle(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "start":
            self.duration = float(event.get("duration") or 0.0)
            log.info("길이 %.0f초, 언어 %s", self.duration, event.get("language"))
        elif kind == "progress" and self.on_progress:
            self.on_progress(float(event.get("seconds") or 0.0), self.duration,
                             int(event.get("cues") or 0))
        elif kind == "done" and self.on_done:
            self.on_done(Path(event["path"]), int(event.get("cues") or 0))
        elif kind == "error":
            self._fail(str(event.get("message") or "알 수 없는 오류"))

    def _fail(self, message: str) -> None:
        log.warning("추출: %s", message)
        if self.on_error:
            self.on_error(message)
