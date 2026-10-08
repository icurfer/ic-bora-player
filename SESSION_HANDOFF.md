# 현재 인계 — 2026-10-09 버전 정책 전환

이 아래의 2026-10-08 기록은 과거 상태다. 현재 기준은 다음과 같다.

- AGENTS.md/CLAUDE.md 공통 지침과 docs/RELEASING.md를 먼저 읽는다.
- 개발 소스는 `0.26.6-dev.1`. `0.26.6` 정식 출시나 설치는 하지 않았다. 설치본은 마지막 확인 0.26.5.
- 일반 커밋/문서 변경에는 버전 증가 없음. Unreleased에 모으고 릴리스 단위로 결정한다.
- `bash scripts/build-deb.sh`는 커밋 식별자가 붙은 개발 deb를 생성한다. dist는 Git 추적 대상이 아니다.
- 공개 태그/Release 없음(2026-10-09 조회). 태그 workflow는 검증 후 Draft Release를 만든다.
- 이미지/단축키 작업의 실제 XTest E2E(시나리오16), 화면 검토, 로컬 설치는 아직 남아 있다.
- 이전 workspace-write 제한은 이번 세션에서 해제됐다. 다음 세션 권한은 그때 확인한다.
- 버전정책 회귀 21개, 기존 관련 단위 포함 총102개 통과. 정책 변경은 UI E2E 통과 증거가 아니다.
- 커밋/원격 반영 여부는 `git status`와 `git log`로 확인한다. 완료 기록은 docs/done/release-policy-20261009.md.

## 과거 인계 원문 (이후 변경 사항은 위 기준 우선)

# 세션 인계 — 2026-10-08

## 바로 이어갈 작업

**0.26.6은 소스 수정·단위 검사·deb 빌드까지만 완료했다. 실제 키 입력 E2E, 설치, 커밋·push가 남아 있다.**
사용자는 단순 함수 호출을 E2E라고 보고한 점을 지적했다. 실제 키 입력을 시험하지 않고
Ctrl+Enter 동작 완료 또는 UI 검증 통과라고 말하지 않는다.

- 작업 경로: `/data/github-icurfer/ic-bora-player`
- 설치 버전: `0.26.5` (2026-10-08 재확인)
- 소스/빌드 버전: `0.26.6`, `dist/bora_0.26.6_all.deb`
- 마지막 커밋: `9cc088f` — 0.26.5 BYOK. 이전 세션에서 main push 완료.
- 현재 변경은 **미커밋**. `git status --short`로 확인하고 그대로 이어간다. 되돌리거나 재구현하지 않는다.
- 현재 세션: workspace-write, `.git` 읽기 전용, approval never, `NoNewPrivs=1`, GUI 접근 실패.
  권한이 바뀌지 않으면 설치·커밋·실제 GUI 검증은 진행할 수 없다. 우회하지 않는다.

## 사용자 요구와 구현

사용자가 메모의 캡처 이미지 링크는 보이지만 AI가 이미지 자체를 못 받는 화면을 제시했다.
또한 메모 단축키와 AI Ctrl+Enter 전송, 실제 키입력 E2E 검증을 요구했다.

- `ai/images.py`: 현재 메모의 마크다운 로컬 이미지 탐색, PNG/JPEG/WEBP 최대4장/총20MiB.
  중복 제거, 한글·공백·괄호·타임스탬프 alt 링크 처리. 외부 URL/폴더탈출/누락/초과는 오류.
  형식 검증은 시그니처 수준이며 완전한 이미지 디코딩 검증은 아니다.
- `ai/context.py`: Question에 note_path/image_paths 추가.
- `ai/client.py`: worker에서 이미지 읽기, 임시 작업폴더 복사 후 Codex localImage 입력, 종료 후 정리.
- `ai/api.py`: 실제 이미지 바이트를 OpenAI Responses input_image data URL로 전달.
- `ai/panel.py`: 텍스트 맥락과 독립적인 이미지 첨부 체크, 개수/오류 안내, 기록에는 파일 이름만.
  AI 입력 키 컨트롤러 CAPTURE, Ctrl+Enter 전송 / Enter 줄바꿈 상시 안내.
- `notes/panel.py`: Ctrl+S 저장, Ctrl+T 시각, Ctrl+Shift+S 캡처, Ctrl+Enter 기존 Codex 터미널,
  Ctrl+Shift+Enter 앱 질문 초안 추가(기존 초안 보존·자동 전송 없음), 키보드 아이콘 도움말.
- `window.py`: Ctrl+M 패널 토글. 마지막 수정으로 파일 전환에서 `_current = path` 직후
  `_chat.refresh_context()`를 호출해 새 파일 이미지 표시가 갱신되도록 했다. 이 수정 후 재빌드 완료.
- 메모 위 / AI 대화 아래 배치는 유지한다. 별도 터미널 작업은 여전히 기본 Codex 기능이다.

## 검증 사실

- 관련 단위 **81 passed**:
  `python3 -m pytest -q tests/test_ai_images.py tests/test_ai_api.py tests/test_ai.py tests/test_notes.py tests/test_state.py`
- compileall / 시나리오16 py_compile / `git diff --check` 통과.
- `bash scripts/build-deb.sh` 성공. 패키지 생성 후 source 추가 변경 없음.
- GUI 시나리오13 및16 시도는 GTK 초기화 실패. 실제 GUI 항목은 실행되지 않음. Xvfb 없음.
- 시나리오16은 현재 GUI 불가 시 미검증 안내와 exit2 반환. 예전처럼 0/0 통과로 표시하지 않는다.
- 실제 API/Codex 계정에 이미지 질문을 보내지 않았다. 이미지 의미 이해는 검증하지 않았다.
- 이번 버전의 새 실제 화면 캡처 없음. 이전 0.26.5 캡처를 이번 검증 근거로 재사용하지 않는다.
- 2026-10-08 정리 시 실행 중인 verify-app Python 테스트 프로세스 없음.

## 다음 세션 순서

1. 권한과 유효 DISPLAY/XAUTHORITY를 확인하고 아래 실제 GUI 시나리오를 **하나씩** 실행한다.
   XAUTHORITY 이전 임시 파일명을 하드코딩하지 않는다. 사용자 파일/설정 대신 격리 샘플만 쓴다.

   ```bash
   GDK_BACKEND=x11 GSETTINGS_BACKEND=memory \
     BORA_REVIEW_SHOTS=/tmp/bora-images-ui-review \
     python3 .claude/skills/verify-app/scenarios/16-shortcuts-images.py
   ```

   시나리오16은 검증창 XID 포커스 확인 후 XTest 실제 키 주입, 두 제공자의 실제 runner+모의응답,
   이미지 바이트, 첨부 해제, 제한/폴더탈출, 작은 창/도움말을 검사한다.
   키를 다른 사용자 창에 보내지 않도록 포커스 검사 실패를 우회하지 않는다.
   사용자 API 키·과금 요청은 쓰지 않는다.

2. 시나리오13(대화), 10(전역 키), 필요 시06(메모) 회귀를 순차 실행한다.
   960×560와 좁은 패널에서 추가된 이미지 안내와 두 입력·전송 버튼 실제 배치를 캡처해 본다.
   미실행 시나리오에는 아직 발견되지 않은 테스트/앱 결함이 있을 수 있으므로 수정 후 다시 검증한다.
3. `.claude/skills/bora-ui-review/SKILL.md`로 구현자와 별도 검토자가 확인한다.
   기존 에이전트 역할: design_skill=메모 UI/단축키 구현, ui_ux_review=독립 검토/시나리오16.
   내부 에이전트 이름과 사용자의 Agents/Untitled UI 항목은 매핑 확인되지 않았다. 보인다고 단정하지 않는다.
4. 통과 후 0.26.6을 설치하고 dpkg 버전 및 설치 소스 일치를 확인한다.

   ```bash
   sudo apt install ./dist/bora_0.26.6_all.deb
   dpkg-query -W bora
   ```

5. done/백로그를 실제 결과로 갱신하고 저장소 규칙에 따라 체크 → 커밋 → main push.
   현재 수정은 같은 미완료 0.26.6 작업이다. 인계 문서 작성만으로 다른 버전을 추가하지 않았다.
6. **테스트로 띄운 Bora는 종료한다.** 사용자 실행 중인 플레이어나 Codex 터미널을 일괄 종료하지 않는다.

## 읽을 파일

- `docs/done/done-v0.10.0-20261007.md`: 독립 소스 검토, 검증/미검증 구분
- `docs/spec/plan-v0.10.0.md`, `docs/scope/scope-v0.10.0.md`, `docs/deferred/backlog-v0.10.0.md`
- `.claude/skills/verify-app/SKILL.md`: 실제 키 E2E 판정 규칙 추가됨
- `.claude/skills/verify-app/scenarios/16-shortcuts-images.py`: 신규 E2E 시나리오
- `tests/test_ai_images.py`: 이미지 단위/모의 제공자 검사
- `docs/requirements/backlog.md` 항목28: 미완료 상태
