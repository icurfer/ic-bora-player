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
    enabled: bool = True        # 꺼지면 결과에서 빠진다. 원본은 건드리지 않는다

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


# ── 타임라인 (기획서 v0.5) ───────────────────────────────────────────────
# 자르기 지점이 이보다 구간 끝에 가까우면 쪼개지 않는다. 0 길이 구간을 막는다.
MIN_SPLIT_GAP = 0.05
# 되돌리기 깊이. 구간 목록이 작아서(수십 개) 통째로 복사해 쌓아도 부담이 없고,
# 연산별 역연산을 만드는 것보다 틀릴 여지가 적다.
UNDO_DEPTH = 50


class Timeline:
    """한 영상의 컷 편집 상태.

    **v0.4 와 기본이 반대다.** 처음에 영상 전체가 구간 하나로 놓여 있고, 자르고 **지워서**
    남길 것을 만든다 — 강의에서 잡담을 걷어내는 쪽이 훨씬 흔하기 때문이다.
    필요한 데만 남기고 싶으면 전체를 끄고 원하는 구간만 되살리면 된다.

    구간은 **항상 시각순으로 이어져 있다**(빈틈도 겹침도 없다). 순서를 바꾸면 그 순서대로
    이어 붙지만, 잘라낸 자리는 여전히 원본의 시각을 가리킨다.
    """

    def __init__(self, duration: float) -> None:
        self.duration = max(0.0, float(duration))
        self.clips: list[Clip] = [Clip(0.0, self.duration)]
        self._undo: list[list[Clip]] = []
        self._redo: list[list[Clip]] = []

    # ── 조회 ─────────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.clips)

    def __iter__(self):
        return iter(self.clips)

    def __getitem__(self, index: int) -> Clip:
        return self.clips[index]

    def enabled_clips(self) -> list[Clip]:
        """내보내기·미리보기가 받는 것. 목록의 순서를 그대로 따른다."""
        return [c for c in self.clips if c.enabled]

    def output_duration(self) -> float:
        return sum(c.duration for c in self.enabled_clips())

    def index_at(self, seconds: float) -> int:
        """그 시각을 품은 구간. 못 찾으면 -1 (목록 순서가 아니라 시각으로 찾는다)."""
        for index, clip in enumerate(self.clips):
            if clip.start <= seconds < clip.end:
                return index
        # 맨 끝은 end 와 같을 수 있다
        if self.clips and abs(seconds - self.clips[-1].end) < 1e-6:
            return len(self.clips) - 1
        return -1

    def source_to_output(self, seconds: float) -> float | None:
        """원본의 시각이 결과에서는 몇 초인가. 잘려 나간 자리면 None."""
        elapsed = 0.0
        for clip in self.enabled_clips():
            if clip.start <= seconds < clip.end:
                return elapsed + (seconds - clip.start)
            elapsed += clip.duration
        return None

    def next_enabled_start(self, seconds: float) -> float | None:
        """미리보기용 — 이 시각 다음에 재생해야 할 원본 위치.

        지금 구간 안이면 그대로 두고(None), 잘린 자리에 들어섰으면 다음 살아 있는
        구간의 시작을 돌려준다. 더 없으면 끝이라는 뜻으로 `duration` 을 준다.
        """
        order = self.enabled_clips()
        for index, clip in enumerate(order):
            if clip.start <= seconds < clip.end:
                return None                     # 계속 재생하면 된다
        for clip in order:
            if clip.start > seconds:
                return clip.start
        return None

    # ── 편집 ─────────────────────────────────────────────────────────────
    def split(self, at: float) -> int:
        """재생헤드 자리에서 쪼갠다. 새로 생긴 **뒤쪽** 구간의 번호를 돌려준다(-1 이면 안 쪼갬)."""
        index = self.index_at(at)
        if index < 0:
            return -1
        clip = self.clips[index]
        if at - clip.start < MIN_SPLIT_GAP or clip.end - at < MIN_SPLIT_GAP:
            return -1                           # 끝에 붙은 자리는 쪼개도 의미가 없다
        self._push()
        tail = Clip(at, clip.end, clip.title, clip.enabled)
        clip.end = at
        self.clips.insert(index + 1, tail)
        return index + 1

    def toggle(self, index: int) -> bool:
        """삭제 ↔ 되살리기. 지운 구간은 회색으로 남아 되돌릴 수 있다."""
        if not (0 <= index < len(self.clips)):
            return False
        self._push()
        self.clips[index].enabled = not self.clips[index].enabled
        return True

    def set_enabled(self, index: int, value: bool) -> bool:
        if not (0 <= index < len(self.clips)) or self.clips[index].enabled == value:
            return False
        self._push()
        self.clips[index].enabled = value
        return True

    def trim(self, index: int, *, start: float | None = None,
             end: float | None = None, push: bool = True) -> bool:
        """구간의 끝을 옮긴다. **이웃이 같이 늘거나 준다** — 빈틈을 만들지 않는다.

        `push=False` 는 드래그 중 연속 호출용이다(놓을 때 한 번만 되돌리기에 쌓는다).
        """
        if not (0 <= index < len(self.clips)):
            return False
        clip = self.clips[index]
        if push:
            self._push()
        if start is not None:
            low = self.clips[index - 1].start + MIN_SPLIT_GAP if index else 0.0
            new_start = min(max(start, low), clip.end - MIN_SPLIT_GAP)
            if index:
                self.clips[index - 1].end = new_start
            clip.start = new_start
        if end is not None:
            high = (self.clips[index + 1].end - MIN_SPLIT_GAP
                    if index + 1 < len(self.clips) else self.duration)
            new_end = max(min(end, high), clip.start + MIN_SPLIT_GAP)
            if index + 1 < len(self.clips):
                self.clips[index + 1].start = new_end
            clip.end = new_end
        return True

    def move(self, index: int, delta: int) -> int:
        """이어 붙는 순서를 바꾼다. 구간이 가리키는 원본 시각은 그대로다."""
        target = index + delta
        if not (0 <= index < len(self.clips)) or not (0 <= target < len(self.clips)):
            return index
        self._push()
        self.clips[index], self.clips[target] = self.clips[target], self.clips[index]
        return target

    def remove(self, index: int) -> bool:
        """구간을 목록에서 아예 뺀다(이웃이 그 자리를 흡수한다).

        평소에는 `toggle` 로 끄는 게 낫다 — 되살릴 수 있으니까. 이건 정리용이다.
        """
        if not (0 <= index < len(self.clips)) or len(self.clips) <= 1:
            return False
        self._push()
        gone = self.clips.pop(index)
        neighbour = self.clips[index - 1] if index else self.clips[0]
        if index:
            neighbour.end = gone.end
        else:
            neighbour.start = gone.start
        return True

    def reset(self) -> None:
        self._push()
        self.clips = [Clip(0.0, self.duration)]

    # ── 되돌리기 ─────────────────────────────────────────────────────────
    @property
    def dirty(self) -> bool:
        """손댄 적이 있나 — 닫을 때 물어볼지 정하는 데 쓴다."""
        return bool(self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self.clips = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self.clips = self._redo.pop()
        return True

    def _snapshot(self) -> list[Clip]:
        return [Clip(c.start, c.end, c.title, c.enabled) for c in self.clips]

    def _push(self) -> None:
        self._undo.append(self._snapshot())
        del self._undo[:-UNDO_DEPTH]
        self._redo.clear()
