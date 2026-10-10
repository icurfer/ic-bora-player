# Windows 실행 환경 보완 이후

- portable zip 및 설치 프로그램은 실제 GTK+libmpv 재생 확인 뒤 CI에서 준비한다.
- 기본 앱 등록/변경은 기존 Windows 기획의 제외 범위를 유지한다.
- cmd/bat 터미널 실행은 안전한 인자 전달 검증 이후 추가한다.
- W1~W7, 실제 사용자 계정 CLI 응답과 한글 IME를 검증한다.
- 현재 PC의 재생·자막·메모·클립은 확인. portable zip, 실제 IME/키입력, Win10, Ubuntu GUI 회귀는 아직 미검증.
- Windows 파일 ACL의 사용자별 접근 제한, 선택 STT 모델 설치/인식은 별도 검증한다.
