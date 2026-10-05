# scope-v0.7.0 — 인수 검토 수정

- clip/runner.py: 출력 경로 검증, 고유 임시 파일, 원자적 합치기, stderr 배수.
- notes/panel.py와 window.py: 저장 실패 보호, AI 마크와 세대 구분, 파일 전환 초기화.
- player.py와 glarea.py: 외부 자막, 트랙 상태 안내, 런타임 로그, GL 오류 표시.
- state.py: 구조와 값 검증.
- ai/client.py, stt/install.py, scripts/install-*.sh, build-deb.sh: 사용자용 설치 경로 일치.
- tests/와 verify-app 시나리오: 기존 테스트 밖 경계 조건 재현 및 회귀.
- version, CHANGELOG, README, 완료 보고: 0.26.2 빌드와 검증 결과.
