# Bora UI/UX 디자인 에이전트 선정

확인일: 2026-10-06. 사용자 제공 10개 저장소의 공개 README를 직접 확인했다.
선정 후보는 실제 스킬 원문도 읽었다. 각 프로젝트의 품질·성능 주장을 실행 검증한 것은 아니다.

## 선택

**plugin87의 근거 중심 검토 + Layout의 기존 디자인 맥락 정리 + Frameground의 실행 결과 확인**을
Bora 전용 `bora-ui-review` 스킬에 적용한다. 별도 디자인 앱·서버 설치 없이 현재 Codex 디자인
에이전트가 실제 GTK 화면을 검토한다. 외부 프로젝트 소스나 스킬 본문을 복제하지 않았다.

판단 기준은 GTK4/libadwaita 1.1 적합성, 기존 플레이어 흐름 보존, 실제 조작 검증,
추가 모델/API 비용과 운영 부담, 현재 저장소에서 반복 가능한가이다. 아래 적합성은 이 작업에
대한 판단이며 프로젝트 자체의 일반적인 품질 순위가 아니다.

## 10개 비교

| 프로젝트 · 원문 | 확인한 방식 | Bora 적용 판단 |
|---|---|---|
| [plugin87/ux-ui-agent-skills](https://github.com/plugin87/ux-ui-agent-skills) | 디자인 검토·접근성·실제 렌더 검증을 스킬로 제공 | **주요 채택**. 근거와 우선순위가 있는 독립 검토. 웹 전용 검사 도구는 GTK 검사로 대체 |
| [basta/frameground](https://github.com/basta/frameground) | 파일 기반 HTML 프레임, 공유 디자인 문서, 편집 결과 즉시 반영 | **방식 채택**. 실행 화면과 소스 연결. HTML 캔버스 런타임은 불필요 |
| [uselayout/app](https://github.com/uselayout/app) | Figma/웹 디자인을 에이전트용 맥락 문서로 변환 | **방식 채택**. Bora 기존 위젯·간격·상태 문구를 검토 맥락에 고정. 웹 추출·DB·Anthropic 설정은 설치하지 않음 |
| [onlook-dev/onlook](https://github.com/onlook-dev/onlook) | Next.js/Tailwind 앱의 DOM 시각 편집 | 보류. 현재 GTK 소스를 직접 편집·검증하는 경로와 다름 |
| [heldernoid/openstitch](https://github.com/heldernoid/openstitch) | 텍스트·스케치로 HTML 화면 생성, 화면 연결·프로토타입 | 보류. 새 HTML 생성과 로컬 모델 운영보다 현재 GTK 동작 검토가 우선 |
| [OpenCoworkAI/open-codesign](https://github.com/OpenCoworkAI/open-codesign) | 데스크톱 디자인 도구, HTML/JSX 생성과 검증, 여러 모델 연결 | 보조 참고. 진행·취소를 드러내는 흐름은 유용하지만 별도 디자인 제품 도입 불필요 |
| [awdr74100/figwright](https://github.com/awdr74100/figwright) | Figma 플러그인과 MCP로 디자인 읽기·쓰기 | 보류. Figma 원본을 사용하는 작업이 생기면 재검토 |
| [sijeeshmiziha/visionagent](https://github.com/sijeeshmiziha/visionagent) | 비전·도구 호출 프레임워크, Figma/Stitch 연결·React 변환 | 보류. 현재 에이전트에 또 다른 모델 SDK/런타임을 추가할 이유가 없음 |
| [JewelArimattom/frame2code](https://github.com/JewelArimattom/frame2code) | VS Code에서 Figma 구조를 MCP·코드 생성 맥락으로 전달 | 보류. Figma/VS Code 중심이고 GTK 화면의 실제 동작 검증 도구가 아님 |
| [jiawenwan/screenshot-to-code](https://github.com/jiawenwan/screenshot-to-code) | 스크린샷에서 웹 코드 생성, 별도 모델 API 사용 | 보류. 이미지 유사성이 메모 보존·대화 전환·재생 응답성을 입증하지 않음 |

## 원문에서 실제로 검토한 항목

- [design-review](https://github.com/plugin87/ux-ui-agent-skills/blob/main/.claude/skills/design-review/SKILL.md): 시각 계층·일관성·접근성·사용성 등 검토 관점.
- [design-qa](https://github.com/plugin87/ux-ui-agent-skills/blob/main/.claude/skills/design-qa/SKILL.md): 상태와 테마별 검증, 자동 검사와 수동 검토의 역할 구분.
- [design-critic](https://github.com/plugin87/ux-ui-agent-skills/blob/main/.claude/agents/design-critic.md): 렌더 화면을 보고 근거가 있는 결함을 찾는 독립 검토.
- [frame](https://github.com/basta/frameground/blob/master/.claude/skills/frame/SKILL.md): 기존 프로젝트 디자인 맥락을 읽고 파일 수정 결과를 확인하는 흐름.

원본의 가중 총점, 웹 모바일 폭 강제, 웹 CSS/axe 실행, 시스템 글꼴 금지,
새 미학마다 승인 대기를 요구하는 절차는 채택하지 않았다. Bora의 네이티브 테마와 기존
제품 범위에 맞지 않는다. 계정·키 저장에 관한 외부 프로젝트의 선택도 그대로 옮기지 않는다.

## 적용 구성

소스: [bora-ui-review/SKILL.md](../../.claude/skills/bora-ui-review/SKILL.md).
설계 검토 담당은 구현 담당과 독립적으로 다음 흐름을 검토한다.

1. 실제 기존 UI에서 위젯·간격·상태 표현과 주요 사용자 흐름을 파악한다.
2. 파일을 보면서 메모·편집·Codex 대화를 오가는 흐름의 배치와 상태를 점검한다.
3. 구현 중간 화면을 확인하고 재현 동작·근거·수정안을 구현 담당에게 보낸다.
4. 수정 후 실제 GTK 화면과 동작을 다시 확인한다. 미검증 항목은 별도로 남긴다.

Codex 대화의 핵심 검토 대상은 메모와 대화 구분, 명시적인 답변 옮기기, 현재 파일과 문맥 표시,
로그인/연결/응답/중지/실패 상태, 비용 경로 안내, 긴 한국어 텍스트, 키보드 포커스다.
메모 손실·파일 간 대화 혼입·조작 불능은 차단 결함이다. 테마의 미세한 취향 차이는 차단하지 않는다.

사용자의 최종 방향은 **기본 동작을 메모 폴더에서 외부 Codex 터미널 열기**로 두고,
앱 안 대화를 추가로 제공하는 것이다. 앱 안에서는 오른쪽을 **위 메모 / 아래 Codex 대화**로
세로 분할하여 두 입력을 동시에 보며 경계를 조절한다. 탭 전환을 전제로 한 검토는 이 배치로
대체한다. 외부 작업 후 돌아왔을 때 메모 변경을 반영하되, 사용자의 동시 편집이 있으면
원본을 덮지 않고 별도 파일 보관 후 새로고침할 수 있어야 한다.

## 검증 게이트와 한계

스킬 형식은 `skill-creator/scripts/quick_validate.py`로 검사한다. 실무 적용 검증은
별도 UI/UX 검토 담당이 이 스킬을 읽고 현재 변경을 평가하는 방식으로 진행한다.
앱의 수용 검증에는 기존 `verify-app`의 설정 격리·시나리오를 사용한다.
기본/최소 창 크기, 실제 지원 테마, 빈 상태·답변 중·오류, 키보드 입력,
파일 전환과 메모 보존, 대화 중 재생 응답성을 확인한다.

이 문서는 구성 선정과 검증 기준이다. 실제 앱 검증 결과와 캡처는 해당 버전의 완료 보고에
남긴다. 스킬 검사 통과는 UI 품질이나 접근성 전체의 통과를 의미하지 않는다.

추가 독립 회귀 검증: `14-workspace-notes.py`를 격리된 GTK/X11 창에서 실행하여 25/25 통과.
첫 메모 생성, 현재 줄·영상·메모를 외부 작업 진입점에 전달, 미저장 내용 저장,
수정 시각이 과거인 외부 변경, 충돌 시 자동 저장 중지, Ctrl+S 확인 대기,
사용자 편집 별도 보관과 원본 보존, 대화 저장 실패 시 영상/메모 일치,
손상된 대화 기록과 무관한 영상 열기를 확인했다. 터미널 실행은 모의 처리했으며
실제 Codex 실행·로그인·모델 호출의 증거는 아니다.
