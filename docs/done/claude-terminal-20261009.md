# 로컬 터미널 도구 선택

Codex 기본값을 유지하고 Claude Code 원본 CLI 실행을 추가했다. 앱 대화 제공자는 변경하지 않는다.
상단 메뉴에서 선택값을 저장하고 Ctrl+Enter/현재줄/폴더 실행이 같은 선택값을 사용한다.
메모 저장 실패·외부 충돌에서는 실행하지 않는다. Claude 인증은 CLI가 처리한다.

## 독립 UI 검토

bora-ui-review를 적용한 별도 검토 에이전트가 격리된 실제 GTK 창에서 확인했다.
어두운 시스템 테마, 요청 320×620 → 실제 352×620. 메뉴 311×422.
저장·닫기와 선택·설치 안내·실행 버튼 잘림 없음. Codex↔Claude 선택과 설정/표시 일치.
캡처: /tmp/bora-ui-agent-review.png, /tmp/bora-ui-agent-review-menu.png.
검증창 모두 종료. 실제 CLI/모델 호출·밝은 테마·전체 재생화면·실제 키입력 E2E는 이 검토에 포함하지 않았다.

전체 단위/GTK 통합 검사 276개 통과. Claude Code 2.1.289에서 실행 옵션을 --version으로 검사했다(모델 호출 없음).
로컬 시나리오16은 검증창의 X11 포커스 불일치로 키 주입 전에 중단했다. 실제 키 검증은 격리된 CI에서 별도 수행한다.
GitHub CI 결과는 아래에 기록한다. 로컬 deb 빌드·설치는 하지 않는다.

## 원격 검증 완료

- 커밋 c88e77d의 [GitHub 실행](https://github.com/icurfer/ic-bora-player/actions/runs/37811138840) 성공.
- 전체 단위/GTK 통합 검사, 시나리오17 실제 XTest Ctrl+Enter 10항목 성공.
- 시나리오17은 격리 Xvfb에서 Claude/Codex 선택별 질문 전달·실행 전 저장·선택 기억·중복 실행을 검사했다.
- 실제 CLI/API 호출은 모의 처리. 사용자 로그인·모델 응답·실제 OS 터미널 창은 미검증이다.
- GitHub 서버에서 deb 빌드·apt 설치·설치 버전 검증·development-deb 업로드 성공.
- artifact ID 11564189351, 107261 bytes, deb와 SHA256SUMS 포함, 14일 보관.
- 로컬 검토창과 시나리오 프로세스 종료 확인. 로컬 설치본은 변경하지 않았다.
