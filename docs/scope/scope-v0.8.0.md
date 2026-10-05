# scope-v0.8.0

- ai/client.py: 로컬 app-server 프로토콜·ChatGPT 로그인 확인·질의·중지.
- ai/context.py, history.py: 주변 맥락과 제한된 대화 이력, 영상별 원자 저장.
- ai/settings.py, panel.py: 로그인 연결 창, 메모와 분리된 대화 영역.
- ai/workspace.py, platform/*/integration.py: 기본 외부 Codex 터미널 실행과 작업 경로.
- notes/model.py, panel.py: 실행 전 저장, 포커스 복귀 시 외부 변경 확인.
- window.py: 메모 위/Codex 아래 세로 분할, 메뉴, 파일 전환·종료 보호.
- build-deb.sh, README: 연동 기본 포함, API SDK 선택 설치 제거.
- bora-ui-review 스킬과 조사: 10개 후보 선정·GTK 적응·UI 독립 검수.
- tests/verify-app: 모의 프로토콜, 메모 보존, 실제 GTK 및 터미널 검증.
