<!--
  CLAUDE.md — 이 저장소의 헌법. 에이전트가 매 세션 읽는다.
  규칙만 적는다(산문 금지). 기계로 검사 가능한 규칙은 CLAUDE.md 가 아니라
  scripts/check-conventions.sh 의 게이트로 옮긴다.

  praxis:shared 마커 블록은 AGENTS.md 와 공유하기 위한 것이다. 이 저장소는
  Claude Code 단일 진입점이라 AGENTS.md 를 두지 않았고, Gate E 는 한쪽만
  있으면 아무것도 검사하지 않는다. Codex 를 쓰게 되면 이 블록을 AGENTS.md 로
  그대로(바이트 단위로 동일하게) 복사하면 Gate E 가 동기화를 강제한다.
-->

<!-- praxis:shared:begin -->
# ic-bora-player (Bora · 보라)

libmpv 를 재생 엔진으로 쓰는 GTK 프론트엔드. 국내 자막(CP949 인코딩 오탐, 한·영 통합 SAMI)
문제를 mpv 에 넘기기 **전에** 전처리로 해결하는 것이 이 프로젝트의 존재 이유다.

> **현재 상태: 기획 완료 · 구현 미착수(코드 없음).**
> 구현 착수 전에 [`docs/spec/plan-v0.1.0.md`](docs/spec/plan-v0.1.0.md) §8 검증 항목을 먼저 처리한다.

## 구성 지도

| 구성요소 | 위치 | 역할 |
|---|---|---|
| UI | 미구현 (`src/bora/` 예정) | GTK4 + libadwaita 창·컨트롤·자막 트랙 선택·싱크 조절 |
| 재생 엔진 | **외부 libmpv** | 디코딩·하드웨어 가속·렌더·싱크. **직접 구현하지 않는다** |
| 엔진 바인딩 | 미구현 | python-mpv(ctypes) ↔ GtkGLArea 렌더 컨텍스트 |
| 자막 전처리기 | 미구현 | 인코딩 2단 탐지 → SAMI 클래스 분리 → UTF-8 임시파일 → `--sub-file` 주입 |
| 배포 | **미결** (기획서 §8-1) | Flatpak 유력. 결정 전까지 배포 의존 코드를 굳히지 않는다 |
| 배포 트리거 | `version` | 1줄. 코드가 바뀌면 patch bump |

## 변경 크기 — 워크플로를 먼저 고른다 (건너뛰지 않는다)
오타 하나에 문서 네 개를 요구하면 사람이 체계를 우회하고, 그러면 체계가 죽는다.
크기를 먼저 재고 맞는 워크플로를 탄다.

**큰 변경** — 다음 중 **하나라도** 해당: 소스 파일 추가, 100줄 이상 코드 변경, 새 API·의존성,
인프라 변경, 규칙 변경. → 아래 전체 절차.

**작은 변경** — 위에 해당 없음(오타, 문구 수정, 소규모 버그픽스). → `spec`/`scope`/`deferred` 생략:
고치고, 코드가 바뀌었으면 `version` bump, `CHANGELOG` **한 줄**, `backlog.md` 체크로 끝.

### 큰 변경 작업 순서
1. **백로그 먼저 확인** — 새 기획 전에 `docs/requirements/backlog.md` 를 읽고, 처리한 항목은 ✅ + 버전 표기.
2. **`docs/spec/plan-vX.Y.Z.md`** (기획서) — 최신본을 복제해 diff 로 수정. 새 기능은 **배치 위치 / 설정·비밀값 보관 위치 / 따르는 기존 패턴** 세 줄을 반드시 적는다.
3. **`docs/scope/scope-vX.Y.Z.md`** — MVP 범위를 파일·함수 단위로.
4. **`docs/deferred/backlog-vX.Y.Z.md`** — MVP 밖 항목을 옮긴다.
5. 구현.
6. **`version` patch bump** — 지시를 기다리지 않고 에이전트가 한다. 안 하면 CI 가 안 돈다.
7. **`docs/done/done-vX.Y.Z-{timestamp}.md`** + `CHANGELOG` 한 줄 + 백로그 ✅.

## 위임된 책임 (지시 없이 에이전트가 한다)
- 배포에 영향 있는 코드를 건드리면 `version` 을 patch bump 한다.
- **기획 단계에도 `version` 을 관리한다.** `docs/spec` · `docs/research` · `docs/scope` ·
  `docs/deferred` · `docs/done` 의 산출물이 추가·변경되면 patch bump 한다.
  (why: CI 가 없다는 이유로 bump 를 건너뛰면 `version` 이 영영 안 움직인다. `version` 은 CI 트리거이기
  이전에 **프로젝트의 진행 상태 표시**다. Gate A 가 이를 강제한다.)
  색인·백로그(`docs/README.md`, `docs/requirements/`)와 개발 도구(`scripts/`)는 대상이 아니다.
- `version` 은 **1줄, 빈 줄 없음** — `printf '%s' "<ver>" > version`.
- 코드 변경 → 검증 → 커밋까지 끝났으면 **push 까지가 한 사이클**이다. 별도 지시를 기다리지 않는다.
  (예외로 사전 확인: force push, main 외 브랜치, 다른 저장소.)

## 하지 말 것 (Do NOT)
- **재생 엔진·코덱·필터·싱크를 직접 구현하지 않는다.** 전부 libmpv/ffmpeg 에 위임한다.
  (why: 기획서 §3-3 의 비목표. 엔진에 손대기 시작하면 유지비가 프로젝트를 삼킨다.)
- **자막 문제를 추정으로 고치지 않는다.** 재현 명령과 실측을 `docs/research/` 에 먼저 남긴다.
  (why: P1~P4 는 전부 실측으로 확정했다. 추정으로 고치면 원인이 다를 때 재발한다.)
- **기획서 §8 검증 항목을 처리하기 전에 구현에 들어가지 않는다.**
  (why: 배포 방식·렌더 연동이 미결이라, 틀리면 쓴 코드를 통째로 버린다.)
- **Ubuntu 22.04 에서 못 도는 API 를 배포 방식 확정 전에 쓰지 않는다** (libadwaita 1.4+ 위젯 등).
  (why: 기획서 §4 — 22.04~26.04 전부 지원이 제약이고, 그 제약이 스택을 결정한다.)
- **한자를 쓰지 않는다.** 등급·범주도 한글("높음/보통/낮음")이나 기호로 적는다.
  (why: 읽는 사람이 한자를 알아보지 못한다. Gate F 가 커밋을 막는다.)
- **빌드·체크가 실패하면 push 하지 않는다** — `check && commit && push` 로 묶는다.
- **`sed` 블라인드 치환으로 코드를 고치지 않는다** — 정확히 일치하는 편집만 한다.
  (why: 엉뚱한 곳이 같이 치환돼 파일이 깨진 적이 있다.)
- **진단을 건너뛰는 "빠른 수정"을 제안하지 않는다** — 진단 → 기획 → 구현 순서를 지킨다.

## 자동 게이트
위 규칙 중 기계로 검사 가능한 것은 커밋 시점에 강제된다:
`.githooks/pre-commit` → `scripts/check-conventions.sh`.

| 게이트 | 막는 것 |
|---|---|
| A | 배포 코드 **또는 `docs/` 산출물**이 바뀌었는데 `version` 이 스테이징되지 않음 |
| B | `version` 형식 위반 (1줄·빈 줄 없음) |
| C | 비밀값·금칙 패턴 (키, 토큰, 개인키) |
| D | 배포 매니페스트 태그 ↔ `version` 불일치 (배포 방식 확정 시 활성화) |
| E | `CLAUDE.md` ↔ `AGENTS.md` 헌법 어긋남 (현재는 단일 진입점이라 무검사) |
| F | 한자·금칙어 |

클론마다 한 번: `bash scripts/install-hooks.sh`. 긴급 우회: `git commit --no-verify`.
**회고에서 기계로 검사 가능한 규칙이 나오면 이 문서에 문장을 더하지 말고 그 스크립트에 게이트를 더한다.**
<!-- praxis:shared:end -->

## 새 규칙을 어느 층에 둘 것인가 (라우팅)
기계적일수록, 자주 발동해야 할수록 **더 단단한 층**에 둔다:
- **커밋 시점에 검사 가능** → `scripts/check-conventions.sh` 게이트
- **에이전트의 도구 사용 중 발동**(차단·수정·반응) → `.claude/settings.json` 훅(PreToolUse/PostToolUse)
- **반복되는 여러 단계 절차** → `.claude/skills/` 스킬
- **떠올려야 할 지속적 사실** → `.claude/memory/`
- **항상 켜둬야 할 판단 규칙** → 이 문서의 한 줄
좁은 규칙을 항상 로드되는 층에 두지 않는다 — 무관한 모든 세션에 세금을 매긴다.

## 메모리
`.claude/memory/` 는 세션을 넘는 공유 메모리다(파일 하나에 사실 하나, `MEMORY.md` 가 색인).
지속적인 사실만 저장하고 대화의 부스러기는 넣지 않는다. 클론마다 한 번
`bash scripts/setup-claude-memory.sh` 를 실행하면 git 으로 버전 관리되며 매 세션 로드된다.
`(STARTER RULE …)` 표시가 붙은 것은 기본 제공 규칙이니 맞으면 남기고 아니면 지운다.
이 체계는 자라야 하지만 자란 만큼 정리돼야 한다 — 주기적으로 `/praxis-review`
(또는 `bash scripts/praxis-review.sh`)로 낡은 규칙과 죽은 게이트를 쳐낸다.
