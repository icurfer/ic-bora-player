# scope-v0.5.0 — 하단 타임라인 컷 편집

기획서: [`../spec/plan-v0.5.0.md`](../spec/plan-v0.5.0.md)

## 들어가는 것

### `src/bora/clip/model.py` (확장)

```python
@dataclass
class Clip:
    start: float
    end: float
    title: str = ""
    enabled: bool = True        # ← 신규. 꺼지면 결과에서 빠진다(원본은 그대로)

class Timeline:                 # ← 신규. 편집의 중심
    def __init__(self, duration): ...      # 전체가 구간 하나로 시작한다
    def split(self, at) -> int             # 재생헤드 자리에서 쪼갠다
    def toggle(self, index) -> None        # 삭제 ↔ 되살리기
    def trim(self, index, *, start=None, end=None) -> None
    def move(self, index, delta) -> int
    def enabled_clips(self) -> list[Clip]  # 내보내기·미리보기가 받는 것
    def undo(self) / redo(self) -> bool    # 상태 스냅숏 방식
    def source_to_output(self, t) -> float | None    # 미리보기 위치 변환
```

`ClipList`(v0.4)는 남긴다 — 목록 창이 계속 쓴다.

### `src/bora/clip/thumbs.py` (신규)

```python
class ThumbStrip:
    def request(self, times: list[float]) -> None   # 보이는 것만, 백그라운드
    def get(self, time) -> GdkPixbuf | None         # 아직이면 None
    def cancel(self) -> None
```

캐시: `~/.cache/bora/thumbs/<해시>/<초>.jpg`. 지워도 되게 만든다.

### `src/bora/clip/timeline.py` (신규)

`Gtk.DrawingArea` + `GestureClick`/`GestureDrag`/`EventControllerScroll`.
그리는 것: 필름스트립 · 구간 경계 · 삭제된 구간(회색) · 선택 테두리 · 재생헤드 · 눈금.

### `src/bora/window.py` (수정)

- 하단에 타임라인을 **접힌 채로** 둔다 (`Gtk.Revealer`)
- `Ctrl+E` 토글, 메뉴 항목
- 자르기 `S`… **충돌**: `S` 는 정지다 → 타임라인이 펴져 있을 때만 `S` 가 자르기,
  아니면 정지. 도구막대 ✂ 버튼은 항상 자르기
- `Delete` 삭제, `Ctrl+Z`/`Ctrl+Shift+Z` 되돌리기 (타임라인이 펴져 있을 때만)
- 미리보기 — `time-pos` 를 지켜보다 구간 끝에서 다음 시작으로 seek

### `src/bora/clip/runner.py` (그대로)

`enabled_clips()` 를 받으면 된다. 내보내기 경로는 바뀌지 않는다.

## 들어가지 않는 것

→ [`../deferred/backlog-v0.5.0.md`](../deferred/backlog-v0.5.0.md)

## 수용 테스트

기획서 §5 의 T1~T8.
