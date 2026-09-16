# ic-bora-player (Bora · 보라)

리눅스용 미디어 플레이어. **libmpv 를 재생 엔진으로 쓰는 GTK 프론트엔드**이며, 국내 사용자가 리눅스에서
겪는 **자막 문제(CP949 인코딩 오탐, 한·영 통합 SAMI)** 를 해결하는 데 집중한다.

"보라"는 *보다* 의 명령형이자 보라색이다. 실행 명령은 `bora`.

> 현재 상태: **기획 단계 (v0.1.0 기획서 작성 완료, 코드 없음).** → [`docs/spec/plan-v0.1.0.md`](docs/spec/plan-v0.1.0.md)

## 왜 만드나

- VLC 는 Wayland 네이티브가 아니라(XWayland 경유) 반응이 느리다.
- KMPlayer·팟플레이어·곰플레이어 등 국내 플레이어는 리눅스를 지원하지 않는다.
- mpv 계열은 빠르지만, **국내 관례 자막**에서 실제로 깨진다 — 실측 근거는 [`docs/research/`](docs/research/2026-09-13-subtitle-encoding-tests.md).

## 무엇을 하지 않는가

- **재생 엔진을 만들지 않는다.** 코덱·하드웨어 가속·싱크는 전부 libmpv(ffmpeg)에 맡긴다.
- **자막 사이트 크롤링·자동 다운로드를 v0.1 에 넣지 않는다.** (보류 목록)
- **Windows·macOS 를 지원하지 않는다.** 대상은 Ubuntu 22.04 ~ 26.04 (및 호환 배포판).
- 코덱 팩·DRM·스트리밍 서비스 로그인을 다루지 않는다.

## 지원 범위

Ubuntu **22.04 / 24.04 / 26.04** 를 모두 지원해야 한다. 이 제약이 기술 스택과 배포 방식을 결정한다
(기획서 §4).

## 문서

[`docs/README.md`](docs/README.md) — 4단계 문서 체계(요구 → 기획서 → 범위 → 보류 → 완료).

## 설치

### deb 로 설치 (권장)

```bash
wget https://github.com/icurfer/ic-bora-player/raw/main/dist/bora_0.17.0_all.deb
sudo apt install ./bora_0.17.0_all.deb
bora <영상파일>
```

56 KB. 의존성은 `python3-gi` · `gir1.2-gtk-4.0` · `gir1.2-adw-1` · `python3-mpv` 네 개이고
apt 가 알아서 받는다(`python3-mpv` 가 libmpv 를 끌고 온다).

> ⚠ **Ubuntu 26.04 에서만 검증했다.** 22.04·24.04 는 libadwaita 1.1 범위로 코드를 짰지만
> 실제로 돌려 보지 않았다(기획서 v0.1 §8-5). 그 버전에서 문제가 나면 알려 주면 좋겠다.

### 소스에서 실행 (개발)

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-mpv
PYTHONPATH=src python3 -m bora <영상파일>

bash scripts/build-deb.sh            # deb 를 직접 만들려면
bash scripts/install-desktop.sh      # 앱 목록에만 등록(개발용, --remove 로 되돌림)
```

### 선택 기능

없어도 재생·자막·메모는 그대로 동작한다.

```bash
bash scripts/install-stt.sh      # 음성 텍스트 추출 (faster-whisper, 약 436 MB)
bash scripts/install-ai.sh       # AI 질의 (anthropic SDK)
export ANTHROPIC_API_KEY=sk-ant-...   # AI 질의용. 앱은 키를 저장하지 않는다
```

## 단축키

| | | | |
|---|---|---|---|
| `Space` `P` | 재생/일시정지 | `A` | 구간 반복 (시작→끝→해제) |
| `S` | 정지 (처음으로) | `F5` `F6` | 구간 시작/끝 (곰·KMP 방식) |
| `←` `→` | 5초 탐색 | `P` | 핀 꽂고 제목 입력 |
| `↑` `↓` | 볼륨 | `Shift+P` | 핀만 꽂기 |
| `F` `Esc` | 전체화면 | `M` | 학습 메모 |
| `[` `]` | 자막 싱크 ±0.1초 | `E` | 자막 편집 |
| `R` `Shift+R` | 자막 위치 위/아래 | `C` `Shift+C` | 스크린샷 (자막 포함/제외) |
| `,` `.` | 재생 속도 | `O` | 파일 열기 |

메모 안에서: `Ctrl+T` 현재 시각 넣기 · `Ctrl+Enter` 이 줄을 AI 에게 묻기 · `Ctrl+S` 저장

## 개발 규율

이 저장소는 [ic-praxis](https://github.com/icurfer/ic-praxis) 체계를 쓴다 — 적어 둔 규칙 중
기계로 검사 가능한 것을 **커밋 시점에 강제**한다.

- [`CLAUDE.md`](CLAUDE.md) — 헌법(작업 순서·위임된 책임·하지 말 것). 에이전트가 매 세션 읽는다.
- `scripts/check-conventions.sh` — 커밋 게이트. `version` bump 누락·형식 위반·비밀값·한자·금칙어를 막는다.
- `.claude/memory/` — 세션을 넘는 작업 규칙. `.claude/skills/verify-app/` — 표준 검증 절차.

클론한 뒤 한 번만:

```bash
bash scripts/install-hooks.sh        # 커밋 게이트 활성화
bash scripts/setup-claude-memory.sh  # 메모리를 git 으로 관리
```
