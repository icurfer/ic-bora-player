"""ffprobe 로 읽고 대조한다 — 이어붙여도 되는지 미리 판정한다.

**왜 필요한가**(실측 `docs/research/2026-09-19-video-cut-concat-tests.md` E):
코덱이 다른 조각을 `concat -c copy` 로 이어붙이면 ffmpeg 이 **오류 없이** 파일을 만든다.
길이도 그럴듯하고 코덱도 표기되는데, 막상 디코딩하면 `Invalid NAL unit size` 로 깨진다.
사용자는 내보내기가 성공했다고 믿고 나중에 발견한다 — 자막 인코딩 문제와 같은 조용한 실패다.
그래서 **ffmpeg 에 맡기기 전에 우리가 대조한다.**
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..log import get as get_logger

log = get_logger("clip.probe")

PROBE_TIMEOUT = 20      # 초. 로컬 파일 헤더만 읽으므로 넉넉하다


@dataclass(frozen=True)
class StreamInfo:
    """이어붙이기 가능 여부를 가르는 값만 담는다."""
    video_codec: str = ""
    width: int = 0
    height: int = 0
    audio_codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration: float = 0.0

    def signature(self) -> tuple:
        """이 값들이 모두 같아야 무손실로 이어붙는다."""
        return (self.video_codec, self.width, self.height,
                self.audio_codec, self.sample_rate, self.channels)

    def describe(self) -> str:
        return (f"{self.video_codec} {self.width}x{self.height} · "
                f"{self.audio_codec} {self.sample_rate}Hz {self.channels}ch")


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe(path: Path) -> StreamInfo | None:
    """실패하면 None — 호출 쪽이 '판정 못 했다'와 '다르다'를 구분할 수 있어야 한다."""
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json", str(path),
    ]
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("ffprobe 실행 실패: %s", exc)
        return None
    if done.returncode != 0:
        log.warning("ffprobe 오류 (%s): %s", done.returncode, done.stderr.strip()[:200])
        return None
    try:
        data = json.loads(done.stdout)
    except ValueError:
        log.warning("ffprobe 출력을 읽지 못했다")
        return None

    info: dict = {"duration": _float(data.get("format", {}).get("duration"))}
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        # 첫 번째 트랙만 본다 — 우리가 내보낼 때도 트랙 하나씩만 매핑한다
        if kind == "video" and "video_codec" not in info:
            info["video_codec"] = stream.get("codec_name") or ""
            info["width"] = int(stream.get("width") or 0)
            info["height"] = int(stream.get("height") or 0)
        elif kind == "audio" and "audio_codec" not in info:
            info["audio_codec"] = stream.get("codec_name") or ""
            info["sample_rate"] = int(stream.get("sample_rate") or 0)
            info["channels"] = int(stream.get("channels") or 0)
    return StreamInfo(**info)


def duration(path: Path) -> float:
    got = probe(path)
    return got.duration if got else 0.0


def can_stream_copy(infos: list[StreamInfo | None]) -> str | None:
    """무손실로 이어붙여도 되면 None, 안 되면 **사람이 읽을 이유**를 돌려준다.

    이유 문자열을 그대로 화면에 띄운다 — 막기만 하고 까닭을 감추면 사용자가
    앱을 탓하게 된다.
    """
    if len(infos) < 2:
        return None                     # 한 조각이면 이어붙일 일이 없다
    if any(i is None for i in infos):
        return "조각의 형식을 읽지 못했다"
    first = infos[0]
    assert first is not None
    for index, other in enumerate(infos[1:], start=2):
        assert other is not None
        if other.signature() != first.signature():
            return (f"{index}번째 조각의 형식이 다르다 "
                    f"({first.describe()} ↔ {other.describe()})")
    return None
