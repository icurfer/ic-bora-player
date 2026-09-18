"""클립 목록 — 순수 데이터. GTK 도 ffmpeg 도 모른다.

기획서 v0.4 §2. 담는 것(재생 중)과 꺼내는 것(내보내기)을 분리했으므로,
그 사이를 잇는 이 층이 유일하게 상태를 들고 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 구간을 잡지 않고 담을 때 쓰는 기본 길이(초). 핀처럼 가볍게 누를 수 있어야 해서 둔다.
DEFAULT_SPAN = 30.0
# 이보다 짧으면 담지 않는다. 키프레임 간격(실측 1.0~4.4초)보다 짧은 클립은
# 빠른 모드에서 사실상 의미가 없고, 실수로 두 번 누른 경우가 대부분이다.
MIN_DURATION = 0.5


def fmt(seconds: float) -> str:
    """`03:20` / `1:03:20`. 목록에 촘촘히 늘어놓을 것이라 짧게 적는다."""
    total = int(max(0.0, seconds))
    h, m, s = total // 3600, total // 60 % 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_span(seconds: float) -> str:
    """길이 표기. 분 단위가 넘어가면 초는 버린다 — 목록에서 읽기 쉬우라고."""
    total = int(max(0.0, round(seconds)))
    if total < 60:
        return f"{total}초"
    if total % 60 == 0:
        return f"{total // 60}분"
    return f"{total // 60}분 {total % 60}초"


@dataclass
class Clip:
    start: float
    end: float
    title: str = ""

    def __post_init__(self) -> None:
        # 거꾸로 잡힌 구간을 여기서 바로잡는다. F5/F6 를 반대 순서로 누르는 일이 흔하다.
        if self.end < self.start:
            self.start, self.end = self.end, self.start
        self.start = max(0.0, self.start)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def valid(self) -> bool:
        return self.duration >= MIN_DURATION

    def label(self) -> str:
        span = f"{fmt(self.start)} ~ {fmt(self.end)} · {fmt_span(self.duration)}"
        return f"{span} · {self.title}" if self.title else span


@dataclass
class ClipList:
    items: list[Clip] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index: int) -> Clip:
        return self.items[index]

    @property
    def empty(self) -> bool:
        return not self.items

    def add(self, clip: Clip) -> int:
        """담은 순서를 유지한다 — 시각순으로 정렬하지 않는다.

        복습본에서 결론을 먼저 보고 근거를 뒤에 붙이고 싶을 수 있다.
        순서를 바꾸는 것은 목록 창에서 손으로 한다.
        """
        self.items.append(clip)
        return len(self.items) - 1

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.items):
            del self.items[index]

    def move(self, index: int, delta: int) -> int:
        """`delta` 만큼 위아래로. 옮겨진 자리를 돌려준다(목록에서 선택을 따라가려고)."""
        target = index + delta
        if not (0 <= index < len(self.items)) or not (0 <= target < len(self.items)):
            return index
        self.items[index], self.items[target] = self.items[target], self.items[index]
        return target

    def clear(self) -> None:
        self.items.clear()

    def total_duration(self) -> float:
        return sum(c.duration for c in self.items)
