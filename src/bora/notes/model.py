"""메모 문서 — 마크다운 평문 + 타임스탬프.

원칙(기획서 v0.3 §3-1):
- `<영상이름>.md` 가 정본이다. 우리 앱 밖에서도 그냥 읽히는 평문이어야 한다.
- 원자적으로 쓴다. 쓰다 죽어도 반쪽 파일이 남지 않는다.
- 앱이 파일을 함부로 덮지 않는다 — 밖에서 고친 흔적이 있으면 먼저 알린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..log import get as get_logger

log = get_logger("notes")

# `[00:12:34]` 또는 `[12:34]`. 대괄호까지 포함해 잡는다(클릭 영역이 되어야 하므로).
STAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")


@dataclass(frozen=True)
class Timestamp:
    start: int          # 문서 안 문자 오프셋 (대괄호 포함)
    end: int
    seconds: float

    @property
    def length(self) -> int:
        return self.end - self.start


def format_stamp(seconds: float | None) -> str:
    """`[00:12:34]`. 한 시간이 안 되어도 시를 적는다 — 나중에 정렬·검색이 쉽다."""
    total = int(max(0.0, seconds or 0.0))
    return "[%02d:%02d:%02d]" % (total // 3600, total // 60 % 60, total % 60)


def parse_stamps(text: str) -> list[Timestamp]:
    """본문에서 타임스탬프를 모두 찾는다. 클릭·강조에 쓴다."""
    found: list[Timestamp] = []
    for m in STAMP_RE.finditer(text):
        hh, mm, ss = m.group(1), m.group(2), m.group(3)
        if ss is None:          # `[12:34]` 는 분:초로 읽는다
            seconds = int(hh) * 60 + int(mm)
        else:
            seconds = int(hh) * 3600 + int(mm) * 60 + int(ss)
        found.append(Timestamp(m.start(), m.end(), float(seconds)))
    return found


class NoteDocument:
    """영상 하나에 딸린 메모 파일."""

    SUFFIX = ".md"

    def __init__(self, path: Path, text: str = "", mtime: float | None = None) -> None:
        self.path = Path(path)
        self.text = text
        self.saved_text = text
        self._mtime = mtime

    # ── 경로 ─────────────────────────────────────────────────────────────
    @staticmethod
    def path_for(video: Path) -> Path:
        return Path(video).with_suffix(NoteDocument.SUFFIX)

    @staticmethod
    def assets_dir_for(video: Path) -> Path:
        """스크린샷 같은 첨부를 두는 곳. 메모와 같은 이름의 폴더."""
        return Path(video).with_suffix(".assets")

    # ── 입출력 ───────────────────────────────────────────────────────────
    @classmethod
    def load_for(cls, video: Path, title: str = "") -> "NoteDocument":
        path = cls.path_for(video)
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
                doc = cls(path, text, path.stat().st_mtime)
                log.debug("메모 읽기: %s (%d자)", path.name, len(text))
                return doc
            except OSError as exc:
                log.warning("메모를 읽지 못했다 %s: %s", path, exc)
        # 처음 여는 영상이면 제목 한 줄로 시작한다. 빈 화면보다 쓰기 시작하기 쉽다.
        heading = f"# {title or Path(video).stem}\n\n"
        return cls(path, heading)

    @property
    def dirty(self) -> bool:
        return self.text != self.saved_text

    def changed_outside(self) -> bool:
        """우리가 저장한 뒤 밖에서 고쳐졌나. 덮어쓰기 전에 확인한다."""
        if self._mtime is None or not self.path.is_file():
            return False
        try:
            return self.path.stat().st_mtime > self._mtime + 0.001
        except OSError:
            return False

    def save(self) -> bool:
        """원자적으로 쓴다. 바뀐 게 없으면 아무 것도 하지 않는다."""
        if not self.dirty:
            return False
        body = self.text
        if body and not body.endswith("\n"):
            body += "\n"            # 평문 파일의 예의
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        self.saved_text = self.text
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = None
        log.info("메모 저장: %s (%d자)", self.path.name, len(body))
        return True

    # ── 편집 도우미 ──────────────────────────────────────────────────────
    def heading_for(self, seconds: float | None, title: str = "") -> str:
        """`## [00:12:34] ` — 삽입할 문자열. 뒤에 커서를 둔다."""
        stamp = format_stamp(seconds)
        return f"## {stamp} {title}".rstrip() + (" " if not title else "\n")
