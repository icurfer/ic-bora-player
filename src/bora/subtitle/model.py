"""편집 가능한 자막 모델.

파일에서 읽어 큐 목록으로 들고 있다가, 고친 뒤 다시 SRT 로 쓴다.
**원본 파일은 저장할 때까지 건드리지 않는다**(기획서 v0.2 §6 — 가장 큰 위험).

지원 입력: SRT, SAMI(.smi). ASS/VTT 는 v0.2 범위 밖이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..log import get as get_logger
from .detect import detect
from .sami import looks_like_sami, parse as parse_sami

log = get_logger("model")

_SRT_BLOCK = re.compile(
    r"(?:^|\n)\s*\d+\s*\n"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})[^\n]*\n"
    r"(.*?)(?=\n\s*\n|\n\s*\d+\s*\n\d{1,2}:|\Z)",
    re.S,
)
# 줄 전체가 엔티티·공백뿐이면 내용이 없는 큐다(research 5).
_EMPTY_LINE = re.compile(r"^(&nbsp;|&#160;|&#xa0;|\s)*$", re.I)


def ms_to_srt(ms: int) -> str:
    ms = max(0, int(ms))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def srt_to_ms(text: str) -> int:
    """'00:01:02,345' · '1:30' · '2' 를 밀리초로. 형식이 틀리면 ValueError.

    ⚠ 옵션 그룹이 둘인 정규식으로 h/m/s 를 가르면 '1:30' 이 30초로 읽힌다(탐욕 매칭 탓).
       콜론으로 잘라 **뒤에서부터** 초·분·시로 채운다.
    """
    text = text.strip().replace(".", ",")
    if not re.fullmatch(r"\d{1,3}(?::\d{1,2}){0,2}(?:,\d{1,3})?", text):
        raise ValueError(f"시각 형식이 아니다: {text!r}")
    time_part, _, frac = text.partition(",")
    bits = [int(b) for b in time_part.split(":")]
    while len(bits) < 3:
        bits.insert(0, 0)                    # 뒤에서부터 초·분·시
    h, mnt, sec = bits
    millis = int((frac or "0").ljust(3, "0"))
    return ((h * 60 + mnt) * 60 + sec) * 1000 + millis


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def shifted(self, delta_ms: int) -> "Cue":
        return replace(self, start_ms=max(0, self.start_ms + delta_ms),
                       end_ms=max(0, self.end_ms + delta_ms))


class SubtitleDocument:
    """큐 목록 + 되돌리기. 편집은 전부 여기서 일어난다."""

    UNDO_LIMIT = 50
    MIN_DURATION_MS = 200

    def __init__(self, cues: list[Cue], source: Path | None = None,
                 encoding: str = "utf-8") -> None:
        self.cues = cues
        self.source = Path(source) if source else None
        self.encoding = encoding
        self.dirty = False
        self._undo: list[list[Cue]] = []

    # ── 읽기 ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path) -> "SubtitleDocument":
        path = Path(path)
        raw = path.read_bytes()
        result = detect(raw)
        text = raw.decode(result.encoding, errors="replace")
        if text.startswith("﻿"):
            text = text[1:]                     # BOM 은 파싱을 방해한다

        if looks_like_sami(raw):
            cues = cls._from_sami(text)
        else:
            cues = cls._from_srt(text)
        log.info("자막 읽기: %s (%s, 큐 %d개)", path.name, result.encoding, len(cues))
        return cls(cues, path, result.encoding)

    @staticmethod
    def _from_srt(text: str) -> list[Cue]:
        cues: list[Cue] = []
        for m in _SRT_BLOCK.finditer(text):
            g = m.groups()
            start = ((int(g[0]) * 60 + int(g[1])) * 60 + int(g[2])) * 1000 + int(g[3].ljust(3, "0"))
            end = ((int(g[4]) * 60 + int(g[5])) * 60 + int(g[6])) * 1000 + int(g[7].ljust(3, "0"))
            body = "\n".join(line.strip() for line in g[8].strip().splitlines())
            if _EMPTY_LINE.fullmatch(body):
                continue                        # 빈 큐는 들고 있을 이유가 없다
            cues.append(Cue(start, end, body))
        return cues

    @staticmethod
    def _from_sami(text: str) -> list[Cue]:
        """SAMI 는 클래스가 여럿일 수 있다. 큐가 가장 많은 클래스를 편집 대상으로 삼는다
        (한·영 통합 자막이면 보통 한국어 쪽이다)."""
        by_class, _langs = parse_sami(text)
        if not by_class:
            return []
        best = max(by_class.values(), key=lambda lst: sum(1 for c in lst if not c.is_terminator))
        cues: list[Cue] = []
        for i, cue in enumerate(best):
            if cue.is_terminator:
                continue
            end = best[i + 1].start_ms if i + 1 < len(best) else cue.start_ms + 4000
            if end <= cue.start_ms:
                end = cue.start_ms + 2000
            cues.append(Cue(cue.start_ms, end, cue.text))
        return cues

    # ── 조회 ─────────────────────────────────────────────────────────────
    def cue_at(self, ms: int) -> int | None:
        """그 시각에 걸린 큐의 인덱스. 없으면 **직전 큐**를 돌려준다.

        자막이 늦게 뜨는 경우가 흔한데, 그때 사용자는 '지금 나와야 할 줄'을 고치고 싶어 한다.
        빈손으로 돌려주면 목록을 뒤지게 되어 감상 흐름이 끊긴다(기획서 §2-1).
        """
        if not self.cues:
            return None
        for i, cue in enumerate(self.cues):
            if cue.start_ms <= ms <= cue.end_ms:
                return i
            if cue.start_ms > ms:
                return max(0, i - 1)
        return len(self.cues) - 1

    # ── 편집 ─────────────────────────────────────────────────────────────
    def _snapshot(self) -> None:
        self._undo.append([replace(c) for c in self.cues])
        del self._undo[:-self.UNDO_LIMIT]
        self.dirty = True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.cues = self._undo.pop()
        return True

    def set_start(self, index: int, ms: int) -> None:
        """시작 시각을 박는다. 남은 길이가 너무 짧으면 끝을 밀어 최소 길이를 확보한다.

        ⚠ `end <= start` 만 보면 1밀리초짜리 큐가 남는다 — 화면에 스치지도 않는다.
           '겹쳤는가'가 아니라 '충분히 긴가'로 판단해야 한다.
        """
        self._snapshot()
        cue = self.cues[index]
        cue.start_ms = max(0, int(ms))
        if cue.duration_ms < self.MIN_DURATION_MS:
            cue.end_ms = cue.start_ms + self.MIN_DURATION_MS

    def set_end(self, index: int, ms: int) -> None:
        self._snapshot()
        cue = self.cues[index]
        cue.end_ms = max(0, int(ms))
        if cue.duration_ms < self.MIN_DURATION_MS:
            cue.start_ms = max(0, cue.end_ms - self.MIN_DURATION_MS)

    def set_text(self, index: int, text: str) -> None:
        self._snapshot()
        self.cues[index].text = text

    def shift_all(self, delta_ms: int) -> None:
        self._snapshot()
        self.cues = [c.shifted(delta_ms) for c in self.cues]

    def shift_from(self, index: int, delta_ms: int) -> None:
        """이 줄부터 뒤로 전부 민다. 중간부터 어긋나는 자막에 쓴다 — 국내에서 가장 흔하다."""
        self._snapshot()
        for i in range(index, len(self.cues)):
            self.cues[i] = self.cues[i].shifted(delta_ms)

    def insert_after(self, index: int, text: str = "") -> int:
        self._snapshot()
        anchor = self.cues[index] if self.cues else None
        start = anchor.end_ms + 100 if anchor else 0
        self.cues.insert(index + 1, Cue(start, start + 2000, text))
        return index + 1

    def remove(self, index: int) -> None:
        self._snapshot()
        del self.cues[index]

    def sort(self) -> None:
        self._snapshot()
        self.cues.sort(key=lambda c: c.start_ms)

    # ── 내보내기 ─────────────────────────────────────────────────────────
    def to_srt(self) -> str:
        out: list[str] = []
        for n, cue in enumerate(sorted(self.cues, key=lambda c: c.start_ms), 1):
            out.append("%d\n%s --> %s\n%s\n" % (n, ms_to_srt(cue.start_ms),
                                                ms_to_srt(cue.end_ms), cue.text))
        return "\n".join(out)
