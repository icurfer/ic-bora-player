"""학습 메모 — 강의를 보며 받아 적는다.

마크다운 파일 하나(`<영상이름>.md`)를 영상 옆에 두고 **그 파일이 정본**이다.
Bora 없이도 읽고 고칠 수 있어야 한다(기획서 v0.3 §3-1).
"""

from .model import NoteDocument, Timestamp, format_stamp, parse_stamps
from .panel import NotePanel

__all__ = ["NoteDocument", "NotePanel", "Timestamp", "format_stamp", "parse_stamps"]
