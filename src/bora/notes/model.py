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
    range_end: float | None = None      # `[A] ~ [B]` 의 B. 구간 표기일 때만 채워진다

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def is_range(self) -> bool:
        return self.range_end is not None and self.range_end > self.seconds


def format_stamp(seconds: float | None) -> str:
    """`[00:12:34]`. 한 시간이 안 되어도 시를 적는다 — 나중에 정렬·검색이 쉽다."""
    total = int(max(0.0, seconds or 0.0))
    return "[%02d:%02d:%02d]" % (total // 3600, total // 60 % 60, total % 60)


def _seconds_of(match: re.Match) -> float:
    hh, mm, ss = match.group(1), match.group(2), match.group(3)
    if ss is None:              # `[12:34]` 는 분:초로 읽는다
        return float(int(hh) * 60 + int(mm))
    return float(int(hh) * 3600 + int(mm) * 60 + int(ss))


def parse_stamps(text: str) -> list[Timestamp]:
    """본문에서 타임스탬프를 모두 찾는다. 클릭·강조에 쓴다.

    `[A] ~ [B]` 처럼 이어진 두 개는 **구간**으로 읽는다 — 핀에서 넣은 구간 표시다.
    그 줄의 어느 쪽을 눌러도 구간 반복이 걸리게 하려고 둘 다 range_end 를 갖는다.
    """
    matches = list(STAMP_RE.finditer(text))
    found: list[Timestamp] = []
    i = 0
    while i < len(matches):
        m = matches[i]
        seconds = _seconds_of(m)
        range_end = None
        if i + 1 < len(matches):
            nxt = matches[i + 1]
            between = text[m.end():nxt.start()]
            # 사이에 구분 기호만 있으면 한 구간으로 본다
            if between.strip() in ("~", "-", "–", "—", "->", "→"):
                range_end = _seconds_of(nxt)
        if range_end is not None:
            nxt = matches[i + 1]
            found.append(Timestamp(m.start(), m.end(), seconds, range_end))
            found.append(Timestamp(nxt.start(), nxt.end(), _seconds_of(nxt), None))
            # 뒤쪽 스탬프를 눌러도 같은 구간이 걸리도록 시작 시각을 기억시킨다
            found[-1] = Timestamp(nxt.start(), nxt.end(), seconds, range_end)
            i += 2
            continue
        found.append(Timestamp(m.start(), m.end(), seconds))
        i += 1
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
    def pin_heading(self, start: float, end: float | None = None, label: str = "") -> str:
        """핀을 메모 한 줄로. 구간이면 `## [A] ~ [B]`, 시점이면 `## [A]`.

        제목(`##`)으로 넣는 이유: 나중에 목차처럼 훑어보기 좋고, 라이브 프리뷰에서 크게 보인다.
        """
        stamp = format_stamp(start)
        if end is not None and end > start:
            stamp = f"{stamp} ~ {format_stamp(end)}"
        return f"## {stamp} {label}".rstrip() + ("\n" if label else " ")

    def heading_for(self, seconds: float | None, title: str = "") -> str:
        """`## [00:12:34] ` — 삽입할 문자열. 뒤에 커서를 둔다."""
        stamp = format_stamp(seconds)
        return f"## {stamp} {title}".rstrip() + (" " if not title else "\n")
