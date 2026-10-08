# 로컬 터미널 도구 선택

메모 작업에 Codex와 Claude Code를 선택한다. 기본 Codex 유지.
배치 위치: 메모 상단의 도구 메뉴, 메인 학습 메뉴. 메모 위/앱 대화 아래 배치 유지.
설정·비밀값 위치: state.json의 terminal_provider만 저장. Claude 로그인은 원본 CLI가 관리하며 앱은 자격증명을 읽지 않는다.
기존 패턴: 메모 저장·외부 변경 감지·충돌 보존과 플랫폼 launch_terminal을 재사용한다.
도구 선택은 실행하지 않는다. 현재 줄 질문 또는 메모 폴더 열기를 명시적으로 실행한다.
Ctrl+Enter는 선택 도구, Ctrl+Shift+Enter는 기존 앱 질문 초안. 앱 AI 제공자와 독립적이다.
