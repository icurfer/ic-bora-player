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

## 실행

```bash
# 저장소에서 바로
PYTHONPATH=src python3 -m bora <영상파일>

# 앱 목록에 등록해서 쓰려면 (사용자 영역, sudo 불필요)
bash scripts/install-desktop.sh      # 되돌리기: --remove
bora <영상파일>                       # ~/.local/bin/bora 로 설치된다
```

필요한 패키지(26.04 기준):

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-mpv libmpv2
```

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
