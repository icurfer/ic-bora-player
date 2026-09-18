# scope-v0.4.0 — 영상 자르기·이어붙이기

기획서: [`../spec/plan-v0.4.0.md`](../spec/plan-v0.4.0.md)

## 들어가는 것

### `src/bora/clip/model.py` (신규)

```python
@dataclass
class Clip:
    start: float
    end: float
    title: str = ""
    @property
    def duration(self) -> float
    def label(self) -> str          # "03:20 ~ 03:50 · 30초 · 제목"

class ClipList:                     # 순서가 있는 목록
    def add(self, clip) -> int
    def remove(self, index) -> None
    def move(self, index, delta) -> None
    def total_duration(self) -> float
```

GTK 의존 없음 — 단위 테스트가 이 층을 본다.

### `src/bora/clip/probe.py` (신규)

```python
@dataclass(frozen=True)
class StreamInfo:                   # codec_name, width, height, sample_rate …
def probe(path) -> StreamInfo
def duration(path) -> float
def can_stream_copy(infos) -> str | None   # 이유 문자열 또는 None(가능)
def ffmpeg_available() -> bool
```

`can_stream_copy` 가 이번 기획의 핵심 방어선(실측 E — 조용한 실패).

### `src/bora/clip/runner.py` (신규)

`stt/runner.py` 와 같은 구조. 별도 venv 는 필요 없다.

```python
@dataclass
class ExportJob:
    source: Path
    clips: list[Clip]
    output: Path
    mode: str          # "copy" | "encode"
    join: bool         # True=하나로, False=조각별
    audio_track: int | None

class ExportRunner:
    def start(self, job) -> bool        # on_progress / on_done / on_error
    def cancel(self) -> None            # 부분 파일 삭제까지
```

진행률은 `ffmpeg -progress pipe:1` 의 `out_time_us`.

### `src/bora/clip/dialog.py` (신규)

클립 목록 창. 행마다 제목·구간·삭제·위아래 이동, 클릭하면 그 지점으로 이동.
하단에 모드·합치기 선택과 내보내기 버튼, 진행률 바.

### `src/bora/window.py` (수정)

- `add_clip()` — A-B 구간이 있으면 그것을, 없으면 현재 위치부터 30초
- `show_clips()` — 목록 창
- 단축키 `K` / `Shift+K`, 하단 메뉴에 항목 추가
- **버그 수정**: `Gdk.KEY_p` 가 재생 토글과 핀 추가에 중복 등록돼 재생 토글이 죽어 있다

### `scripts/build-deb.sh` (수정)

`Depends` 에 `ffmpeg` 추가.

## 들어가지 않는 것

→ [`../deferred/backlog-v0.4.0.md`](../deferred/backlog-v0.4.0.md)

## 수용 테스트

기획서 §4 의 C1~C6.
