# scope-v0.1.0 — Bora v0.1 구현 범위 (파일·함수 단위)

기준: [`../spec/plan-v0.1.0.md`](../spec/plan-v0.1.0.md) (2026-09-13 정정판)
근거 실측: [`../research/`](../research/) 2·3·4번 · 프로토타입: [`../research/scripts/`](../research/scripts/)
작성: 2026-09-13 · 대상: **Ubuntu 26.04 먼저** (22.04·24.04 는 [`../deferred/backlog-v0.1.0.md`](../deferred/backlog-v0.1.0.md) §1)

## §0 이 범위가 끝나면 되는 것

기획서 §6 의 T1~T4 와 T6 가 26.04 에서 통과한다. (T5 = 3개 릴리스 검증은 연기)

| # | 시나리오 | 이 범위에서 어떻게 |
|---|---|---|
| T1 | CP949 `.smi` 를 영상과 같은 폴더에 두고 열기 | `sub-auto=fuzzy` + 인코딩 판정 주입 |
| T2 | 107 B 급 짧은 CP949 SAMI | 판정 ④단계(한글 비율)로 CP949 확정 |
| T3 | `KRCC`+`ENCC` 통합 SAMI | 클래스 분리 → 트랙 2개, 한국어 기본 |
| T4 | UTF-8 `.srt` | 판정 ①단계에서 끝. 아무것도 하지 않는다 |
| T6 | 1080p H.264 | `hwdec=auto-safe`, `hwdec-current` 를 UI 에 노출 |

## §1 파일 구조

```
src/bora/
  __init__.py          버전 문자열 하나
  __main__.py          진입점 — 명령행 인자 파싱 → BoraApplication 실행
  app.py               BoraApplication (Adw.Application)
  window.py            BoraWindow — GLArea + 컨트롤 + 자막 메뉴
  player.py            Player — libmpv 래퍼 (MPV + MpvRenderContext)
  glarea.py            MpvGLArea — Gtk.GLArea 서브클래스, 렌더 컨텍스트 소유
  subtitle/
    __init__.py
    detect.py          인코딩 판정        ← research/scripts/pipeline.py 승격
    sami.py            SAMI 파서·분리기   ← research/scripts/sami_split.py 승격
    loader.py          판정 결과로 무엇을 할지 결정하고 Player 에 주입
  util/
    __init__.py
    gl.py              ctypes 로 eglGetProcAddress / 현재 FBO 조회
pyproject.toml         의존성·진입점
tests/
  fixtures/            자막 표본 (Gate F 예외 경로)
  test_detect.py       판정 11케이스 회귀 — pipeline.py 의 EXPECT 표를 그대로 옮긴다
  test_sami.py         분리 결과의 큐 시각·클래스 검증
```

**포함하지 않는다**: 설정 파일·설정 창, 플레이리스트, 국제화, 패키징 매니페스트.

## §2 모듈별 범위

### 2-1. `subtitle/detect.py` — 인코딩 판정 (이 프로젝트의 핵심 1)

프로토타입 `research/scripts/pipeline.py` 를 그대로 옮기고 테스트를 붙인다. **로직을 새로 만들지 않는다.**

```python
CJK_TRUSTED: dict[str, str]      # uchardet 이름 -> 파이썬 코덱. 지목하면 신뢰한다
HANGUL_MIN = 0.7                 # 비ASCII 중 한글 음절 비율 임계 (실측 근거: research 2 §2-3)

def strip_markup(raw: bytes) -> bytes
    """태그·엔티티·SRT 타임코드를 바이트 단위로 제거. 디코드 전에 부른다.
       안전 근거: '<' '>' '&' ';' 는 CP949/Shift_JIS/GB18030 의 trail byte 에 없다."""

def uchardet(data: bytes) -> str
    """libuchardet.so.0 을 ctypes 로 호출. 실패하면 빈 문자열."""

def hangul_ratio(data: bytes, enc: str = 'cp949') -> float | None
    """해당 인코딩으로 디코드해 '비ASCII 문자 중 한글 음절' 비율. 디코드 실패면 None."""

def detect(raw: bytes) -> DetectResult
    """① 엄격 UTF-8 → ② 태그 제거 후 uchardet → ③ CJK 면 신뢰
       → ④ 한글 비율 >= HANGUL_MIN 이면 cp949 → ⑤ cp949 폴백(확신 없음)"""

@dataclass
class DetectResult:
    encoding: str      # 파이썬 코덱 이름
    confident: bool    # False 면 UI 에 '추정' 배지
    reason: str        # 어느 단계에서 정해졌는지 — UI 툴팁과 로그에 그대로 쓴다
```

⚠ **③이 ④보다 먼저다.** 한글 비율로는 일본어를 구분할 수 없다(Shift_JIS 가 1.00). 순서를 바꾸면 T3 이 아니라
일본어 자막이 깨진다. 테스트로 고정한다.

### 2-2. `subtitle/sami.py` — SAMI 분리 (이 프로젝트의 핵심 2)

프로토타입 `research/scripts/sami_split.py` 를 옮긴다.

```python
def parse(text: str) -> tuple[dict[str, list[Cue]], dict[str, str]]
    """-> ({클래스: [Cue]}, {클래스: lang}). <STYLE> 의 lang: 을 우선 읽는다."""

def to_srt(cues: list[Cue]) -> str
    """큐 끝 = '같은 클래스'의 다음 SYNC. &nbsp; 단독 큐는 종료 신호로만 쓰고 출력하지 않는다."""

def split_to_files(raw: bytes, encoding: str, outdir: Path) -> list[Track]
    """클래스별 UTF-8 SRT 를 outdir 에 쓰고 [Track(path, lang, title)] 반환.
       클래스가 하나뿐이면 빈 리스트를 반환한다 — 분리할 이유가 없다."""

@dataclass
class Track:
    path: Path
    lang: str        # 'ko' / 'en' … mpv 의 lang 인자로 넘긴다
    title: str       # 트랙 메뉴에 보일 이름
```

언어 매핑: `<STYLE>` 의 `lang:` → 없으면 관례(`KRCC`→ko, `ENCC`→en) → 그래도 없으면 클래스 이름 그대로.

### 2-3. `subtitle/loader.py` — 오케스트레이션

**"무엇을 할지 정하는" 층.** 실측 결론(research 2 §4)을 코드로 옮긴 곳이다.

```python
def prepare(video_path: Path, sub_path: Path, cache_dir: Path) -> Plan
    """자막 하나를 보고 계획을 세운다.
       1) detect() 로 인코딩 판정
       2) SAMI 이고 클래스가 2개 이상 -> split_to_files() -> 분리 트랙들을 주입
       3) 그 밖에는 파일을 건드리지 않는다. --sub-codepage=+<enc> 주입으로 끝"""

@dataclass
class Plan:
    codepage: str | None        # '+cp949' 형태. None 이면 건드리지 않는다
    tracks: list[Track]         # 비어 있으면 원본 자막을 그대로 쓴다
    detect: DetectResult        # UI 표시용
    fallback_stretch: bool      # 분리 실패한 SAMI 일 때만 True
```

원칙: **파일을 다시 쓰는 것은 한·영 통합 SAMI 일 때뿐이다.** 나머지는 옵션 주입으로 끝낸다.
임시 파일은 원본 폴더가 아니라 `cache_dir`(= `GLib.get_user_cache_dir()/bora`)에 쓴다.

### 2-4. `player.py` — libmpv 래퍼

```python
class Player:
    def __init__(self, get_proc_address)      # hwdec='auto-safe', vo='libmpv'
    def attach_render_context(self, gl)       # MpvRenderContext(api_type='opengl')
    def render(self, width, height, fbo)      # ctx.render(flip_y=True, opengl_fbo=…)
    def open(self, path: Path, plan: Plan)    # codepage 적용 -> play -> tracks 주입
    def add_sub(self, track: Track, select: bool)
    def toggle_pause / seek / set_volume / set_sub_delay / set_fullscreen
    @property sub_tracks / hwdec_current / duration / time_pos
```

- 콜백 타입은 **`mpv.MpvGlGetProcAddressFn`** (옛 이름 `OpenGlCbGetProcAddrFn` 은 없다 — 실측).
- `ctx.update_cb` → `GLib.idle_add(area.queue_render, priority=GLib.PRIORITY_HIGH)`.
- 트랙 주입은 `sub_add(path, 'select'|'auto', title, lang)` — 제목·언어를 같이 넘긴다.

### 2-5. `glarea.py` · `util/gl.py`

`research/scripts/spike_gtk4.py` 에서 검증된 코드를 그대로 옮긴다. **PyOpenGL 을 쓰지 않는다.**

```python
# util/gl.py
def get_proc_address(_ctx, name) -> int     # libEGL.so.1 의 eglGetProcAddress
def current_fbo() -> int                    # libGL.so.1 의 glGetIntegerv(0x8CA6)

# glarea.py
class MpvGLArea(Gtk.GLArea):
    # set_auto_render(False), 'realize' 에서 Player 연결, 'render' 에서 Player.render()
    # 크기는 get_width()*get_scale_factor()
```

### 2-6. `window.py` — UI (기획서 §5-3 범위)

**위젯은 libadwaita 1.1 범위를 기본으로 쓴다.** 26.04 에서도 같게 동작하므로 지금 비용이 없고,
나중에 22.04 를 맞출 때의 비용을 줄인다. 불가피하게 1.4+ API 를 쓰면 `# ADW-1.4+` 주석을 단다.

| 요소 | 쓰는 위젯 (1.1 범위) |
|---|---|
| 창 | `Adw.ApplicationWindow` + `Adw.HeaderBar` + `Gtk.Box`(수직) |
| 영상 | `MpvGLArea` |
| 컨트롤 | `Gtk.Box` + `Gtk.Button` + `Gtk.Scale`(탐색·볼륨) |
| 자막 트랙 선택 | `Gtk.PopoverMenu` 또는 `Gtk.DropDown` |
| 자막 싱크 | `Gtk.SpinButton`(±0.1초) — `Adw.SpinRow` 를 쓰지 않는다 |
| 파일 열기 | `Gtk.FileChooserNative` — `Gtk.FileDialog`(4.10+)를 쓰지 않는다 |
| 알림·오류 | `Adw.Toast` + `Adw.ToastOverlay` |
| 자막 상태 표시 | 헤더바의 `Gtk.Label`/`Gtk.MenuButton` — 인코딩 · '추정' 배지 · 트랙 수, 툴팁에 `DetectResult.reason` |

입력 경로: 명령행 인자 · 드래그 앤 드롭(`Gtk.DropTarget`) · 파일 열기 버튼.

### 2-7. `__main__.py` · `app.py`

- 인자가 2개 이상이면 **두 번째를 자막으로 본다**(포털에서 영상·자막을 함께 고른 경우 — research 4 §4).
- `app.py` 는 `Adw.Application` 하나. 단일 인스턴스 여부는 v0.1 범위 밖.

## §3 테스트 범위

| 파일 | 무엇을 고정하나 |
|---|---|
| `test_detect.py` | `research/scripts/pipeline.py` 의 11케이스 그대로. **특히 일본어·중국어가 cp949 로 판정되지 않을 것** |
| `test_sami.py` | 한·영 통합 SAMI 분리 시 큐 시각이 0초가 아닐 것, 클래스별 트랙 수, `&nbsp;` 큐가 출력되지 않을 것 |

표본은 `tests/fixtures/` 에 둔다(Gate F 예외 경로). 생성은 `research/scripts/gen.py` 로 재현 가능.
**실제 자막 표본 수집은 구현과 병행한다** — 임계값 0.7 의 근거가 합성 11개뿐이다(deferred §4).

GUI 자동화 테스트는 범위 밖. 수동 검증 절차는 `.claude/skills/verify-app/` 에 쌓는다.

## §4 순서 (의존 관계)

1. `util/gl.py` + `glarea.py` + `player.py` — **영상이 창에 나온다**(스파이크 코드 이식)
2. `subtitle/detect.py` + `test_detect.py` — 판정이 회귀로 고정된다
3. `subtitle/sami.py` + `test_sami.py`
4. `subtitle/loader.py` — 둘을 묶어 Plan 을 만든다
5. `window.py` 의 파일 열기 + 자동 로드 → **T1·T2·T4 통과**
6. 자막 트랙 선택 UI → **T3 통과**
7. 싱크 조절 · 상태 표시 · 드래그 앤 드롭 → 마무리

1번이 끝나면 눈에 보이는 것이 생긴다. 2~4번은 UI 없이 테스트로 검증되므로 병행 가능하다.

## §5 이 범위에서 하지 않기로 한 것

`deferred/backlog-v0.1.0.md` 전부. 특히 자주 유혹받을 것들:
- 설정 창 · 단축키 커스터마이즈 · 플레이리스트
- `.ass` 스타일 보존 · 자막 자동 다운로드
- Flatpak 매니페스트 · deb 패키징
- 22.04 대응 코드 분기 — **대신 위젯을 1.1 범위로 쓰는 규율만 지킨다**
