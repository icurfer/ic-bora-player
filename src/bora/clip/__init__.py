"""클립 — 재생 중 담아 둔 구간을 파일로 꺼낸다 (기획서 v0.4).

`model` 은 순수 데이터, `probe` 는 ffprobe 판정, `runner` 는 ffmpeg 실행,
`dialog` 는 UI. 잘라내기·이어붙이기 자체는 전부 ffmpeg 에 위임한다.
"""

from .dialog import ClipWindow
from .model import Clip, ClipList
from .probe import ffmpeg_available

__all__ = ["Clip", "ClipList", "ClipWindow", "ffmpeg_available"]
