"""내보내기 — ffmpeg 를 별도 프로세스로 돌리고 진행률을 받는다.

`stt/runner.py` 와 같은 구조다. 다만 STT 와 달리 **별도 venv 가 필요 없다** —
ffmpeg 는 libmpv 의 동반 의존이라 항상 있다(없으면 `probe.ffmpeg_available()` 이 걸러낸다).

흐름(기획서 v0.4 §3-4):
  1. 클립마다 임시 조각으로 자른다
  2. 조각이 둘 이상이고 합치기면 — **형식을 대조한 뒤** concat 으로 잇는다
  3. 조각별 저장이면 각 조각을 목적지 이름으로 옮긴다
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..log import get as get_logger
from .model import Clip
from .probe import can_stream_copy, probe

log = get_logger("clip.runner")

# 재인코딩 설정. veryfast/crf 20 은 실측에서 실시간의 약 5배속이 나왔고
# 눈으로 열화가 보이지 않는 선이다.
ENCODE_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac"]
# 실측 기준(30초에 5.68초). 남은 시간을 어림잡는 데만 쓴다.
ENCODE_SPEED = 5.0
# 여유 공간을 이 배수만큼 요구한다 — 임시 조각과 결과가 같이 존재하는 순간이 있다.
SPACE_MARGIN = 2.2

_OUT_TIME = re.compile(r"^out_time_us=(\d+)", re.MULTILINE)


@dataclass
class ExportJob:
    source: Path
    clips: list[Clip]
    output: Path            # 합치기면 파일, 조각별이면 첫 조각의 이름(뒤에 번호가 붙는다)
    mode: str = "copy"      # "copy"(빠르게) | "encode"(정확히)
    join: bool = True
    audio_track: int | None = None      # mpv 트랙 번호가 아니라 ffmpeg 의 0-기반 순번

    @property
    def total_duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def estimated_seconds(self) -> float:
        """얼마나 걸릴지. 취소할 기회를 주려면 미리 말해 줘야 한다."""
        if self.mode == "encode":
            return self.total_duration / ENCODE_SPEED
        return max(1.0, self.total_duration / 300.0)    # 무손실은 사실상 I/O 시간


@dataclass
class ExportResult:
    paths: list[Path] = field(default_factory=list)
    downgraded: str = ""    # 빠른 모드를 포기한 이유(있으면 화면에 띄운다)


class ExportRunner:
    """한 번에 하나만 돌린다. 취소하면 부분 파일을 남기지 않는다."""

    def __init__(self, on_progress=None, on_done=None, on_error=None) -> None:
        self.on_progress = on_progress      # (끝낸 초, 전체 초, 단계 설명)
        self.on_done = on_done              # (ExportResult)
        self.on_error = on_error            # (메시지)
        self._proc: subprocess.Popen | None = None
        self._cancelled = False
        self._temps: list[Path] = []
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, job: ExportJob) -> bool:
        if self.running:
            return False
        if not job.clips:
            self._fail("담은 클립이 없다")
            return False
        problem = self._check_space(job)
        if problem:
            self._fail(problem)
            return False
        self._cancelled = False
        self._temps = []
        self._thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            log.info("내보내기 취소")
            proc.terminate()

    # ── 내부 ─────────────────────────────────────────────────────────────
    def _check_space(self, job: ExportJob) -> str | None:
        """원본 비트레이트로 결과 크기를 어림잡아 디스크를 확인한다."""
        try:
            source_size = job.source.stat().st_size
            source_length = max(1.0, probe(job.source).duration if probe(job.source) else 1.0)
            need = source_size / source_length * job.total_duration * SPACE_MARGIN
            free = shutil.disk_usage(job.output.parent).free
        except (OSError, AttributeError) as exc:
            log.warning("여유 공간을 확인하지 못했다: %s", exc)
            return None                 # 확인 실패로 막지는 않는다
        if free < need:
            return (f"디스크 여유가 모자란다 — 약 {need / 2**30:.1f} GB 가 필요한데 "
                    f"{free / 2**30:.1f} GB 남았다")
        return None

    def _run(self, job: ExportJob) -> None:
        try:
            pieces = self._cut_all(job)
            if pieces is None:
                return                  # 취소되었거나 이미 실패를 알렸다
            result = (self._join(job, pieces) if job.join and len(pieces) > 1
                      else self._place(job, pieces))
            if result is None:
                return
            if self.on_done:
                self.on_done(result)
        except Exception as exc:                    # noqa: BLE001 — 스레드를 조용히 죽이지 않는다
            log.exception("내보내기 중 예외")
            self._fail(f"내보내기 실패: {exc}")
        finally:
            self._cleanup()

    def _cut_all(self, job: ExportJob) -> list[Path] | None:
        pieces: list[Path] = []
        done_seconds = 0.0
        suffix = job.output.suffix or ".mkv"
        for index, clip in enumerate(job.clips, start=1):
            if self._cancelled:
                self._fail("취소됨")
                return None
            temp = job.output.with_name(
                f".bora-clip-{os.getpid()}-{index}{suffix}")
            self._temps.append(temp)
            step = f"{index}/{len(job.clips)} 잘라내는 중"
            ok = self._ffmpeg(
                self._cut_command(job, clip, temp),
                base=done_seconds, total=job.total_duration, step=step)
            if not ok:
                return None
            pieces.append(temp)
            done_seconds += clip.duration
        return pieces

    def _cut_command(self, job: ExportJob, clip: Clip, out: Path) -> list[str]:
        # `-ss` 를 `-i` 앞에 둔다 — 키프레임으로 탐색해 빠르다.
        # 뒤에 두면 정확해지지만 그 지점까지 디코딩하느라 느려진다(실측 §2).
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{clip.start:.3f}", "-to", f"{clip.end:.3f}",
            "-i", str(job.source),
            "-map", "0:v:0",
            "-map", f"0:a:{job.audio_track if job.audio_track is not None else 0}?",
        ]
        command += ["-c", "copy"] if job.mode == "copy" else ENCODE_ARGS
        command += ["-progress", "pipe:1", str(out)]
        return command

    def _join(self, job: ExportJob, pieces: list[Path]) -> ExportResult | None:
        """이어붙이기 — **형식을 먼저 대조한다**(실측 E 의 조용한 실패 방어)."""
        reason = can_stream_copy([probe(p) for p in pieces])
        if reason:
            # 여기까지 왔는데 형식이 다르다는 것은 같은 소스에서 잘랐는데도 갈렸다는 뜻이다.
            # 깨진 파일을 내놓느니 멈추고 까닭을 말한다.
            self._fail(f"조각을 이어붙일 수 없다 — {reason}. "
                       f"'정확히' 모드로 다시 내보내면 형식이 통일된다")
            return None
        listing = job.output.with_name(f".bora-clip-{os.getpid()}.txt")
        self._temps.append(listing)
        listing.write_text(
            "".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
        ok = self._ffmpeg(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-progress", "pipe:1", str(job.output)],
            base=0.0, total=job.total_duration, step="이어붙이는 중")
        if not ok:
            return None
        return ExportResult(paths=[job.output])

    def _place(self, job: ExportJob, pieces: list[Path]) -> ExportResult | None:
        """조각별 저장 — 임시 조각을 목적지 이름으로 옮긴다."""
        stem, suffix = job.output.stem, job.output.suffix or ".mkv"
        out: list[Path] = []
        for index, piece in enumerate(pieces, start=1):
            name = f"{stem}{suffix}" if len(pieces) == 1 else f"{stem}-{index}{suffix}"
            target = job.output.with_name(name)
            target.unlink(missing_ok=True)
            piece.replace(target)                   # 같은 디렉터리라 rename 으로 끝난다
            out.append(target)
        self._temps = [t for t in self._temps if t.exists()]
        return ExportResult(paths=out)

    def _ffmpeg(self, command: list[str], *, base: float, total: float,
                step: str) -> bool:
        log.info("%s: %s", step, " ".join(command[:9]))
        try:
            self._proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1)
        except OSError as exc:
            self._fail(f"ffmpeg 를 띄우지 못했다: {exc}")
            return False
        proc = self._proc
        assert proc.stdout is not None
        for line in proc.stdout:
            found = _OUT_TIME.match(line.strip())
            if found and self.on_progress:
                seconds = int(found.group(1)) / 1_000_000
                self.on_progress(min(base + seconds, total), total, step)
        code = proc.wait()
        if self._cancelled:
            self._fail("취소됨")
            return False
        if code != 0:
            tail = (proc.stderr.read() or "").strip()[-300:] if proc.stderr else ""
            self._fail(f"ffmpeg 실패 (코드 {code}) {tail}")
            return False
        if self.on_progress:
            self.on_progress(min(base + total, total), total, step)
        return True

    def _cleanup(self) -> None:
        for temp in self._temps:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        self._temps = []
        self._proc = None

    def _fail(self, message: str) -> None:
        log.warning("내보내기: %s", message)
        if self.on_error:
            self.on_error(message)
