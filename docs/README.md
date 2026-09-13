# docs/ — 4단계 문서 체계

변경은 코드가 되기 **전에** 문서로 고정한다. 결정이 유실되지 않게 모든 작업 단위가 아래 단계를 지난다.
(`ic-crawl`과 같은 체계다.)

| 폴더 | 역할 |
|---|---|
| `requirements/backlog.md` | 사용자 요구 백로그. 기획 전에 확인하고, 처리한 항목은 ✅ + 버전 표기 |
| `spec/plan-vX.Y.Z.md` | **기획서(스펙)** — 통합 기능 단위 하나. 모든 작업의 뿌리. 최신본을 복제해 diff 로 수정 |
| `scope/scope-vX.Y.Z.md` | MVP 범위를 파일·함수 단위로 |
| `deferred/backlog-vX.Y.Z.md` | MVP 밖으로 밀어낸 항목 |
| `done/done-vX.Y.Z-{timestamp}.md` | 완료 보고. "영향받는 레포" 표 포함 |
| `research/` | 기획 근거가 된 실측·조사 기록. 재현 가능한 명령을 남긴다 |
| `../CHANGELOG.md` | 한 줄 요약 인덱스 |

**큰 변경만 전 단계를 밟는다.** 오타·소규모 수정은 `spec/scope/deferred` 를 건너뛰고 코드 수정 →
`version` bump → `CHANGELOG` 한 줄 → `backlog.md` 체크로 끝낸다.
("큰 변경" = 소스 파일 추가, 100줄 이상 변경, API·의존성·인프라 추가, 규칙 변경)

## 문서가 규칙이 되고, 규칙이 게이트가 된다
이 체계의 규칙 중 **기계로 검사 가능한 것은 문장으로 두지 않고 커밋 게이트로 옮긴다**
(`scripts/check-conventions.sh`, [`../CLAUDE.md`](../CLAUDE.md) §자동 게이트).
`version` bump 누락·형식 위반·비밀값·한자 같은 것은 잊을 수 있는 규칙이 아니라 커밋이 막히는 규칙이다.
회고에서 새 규칙이 나오면 먼저 **검사 가능한가**를 묻고, 가능하면 게이트를 추가한다.

## 버전 정책

**두 개의 축이 있다. 섞지 않는다.**

| | 무엇 | 언제 움직이나 |
|---|---|---|
| `spec/plan-vX.Y.Z.md` 의 `X.Y` | **기획 단위**. 통합 기능 하나 | 기획의 범위가 바뀔 때. 같은 기획 안의 정정은 파일명을 바꾸지 않고 문서 안에 "정정" 절로 남긴다 |
| 루트 `version` | **저장소의 진행 상태**(= 배포 트리거) | 코드나 `docs/` 산출물이 바뀔 때마다 patch bump |

그래서 `plan-v0.1.0.md` 가 그대로인 채로 `version` 이 `0.1.0 → 0.1.1 → 0.1.2` 로 오르는 것이 정상이다.
`0.1.0` 으로 시작, **`1.0.0` = 릴리스**.

**`version` 은 기획 단계에도 관리한다.** CI 가 아직 없다는 이유로 bump 를 건너뛰면 영영 안 움직인다.
`docs/{spec,research,scope,deferred,done}` 이 바뀌면 patch bump 하고, 커밋 게이트(Gate A)가 이를 강제한다.
색인·백로그(`docs/README.md`, `docs/requirements/`)와 `scripts/` 는 대상이 아니다.

`version` 파일은 1줄만 두고 뒤에 빈 줄을 두지 않는다 — `printf '%s' "<ver>" > version`.
