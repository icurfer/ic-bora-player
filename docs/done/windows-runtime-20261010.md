# Windows 실행 환경 보완 — 2026-10-10

## 결과
현재 Windows PC에서 실제 Bora 영상 재생과 CP949 자막 표시를 확인했다.
전체 Windows 지원이나 portable 배포 완료로 표시하지 않는다. `verified()`와 제품 버전은 유지한다.

## 구현
- Windows 플랫폼: 활성 WGL/EGL 함수/FBO 조회와 오류 주소 처리, uchardet DLL 탐색,
  MSYS2 bin/정식 CPython Scripts venv 경로, Python/GIO 명령줄 보정.
- exe/ps1 CLI의 PowerShell 새 콘솔 실행. cmd/bat는 아직 명시적으로 거절한다.
- `windows/run.ps1`: 사용자 로컬 런타임과 UTF-8 출력으로 앱 실행.
- 공통 앱은 플랫폼 기반 클래스를 사용하고 자막 판정은 플랫폼 제공 라이브러리 경로를 사용한다.
  자막 판정 순서/임계값과 Linux 앱 기반 클래스는 유지한다.
- 기존 검사 fixture의 shebang/JSON/경로/권한/플랫폼 가정을 정리하고 실제 Windows GIO 회귀를 추가했다.
- 검증 시나리오의 중첩 이벤트 루프를 보완하고 DPI를 고려한 검증 창 캡처 helper를 추가했다.

## 실측
Windows 빌드26200·25H2·x64, MSYS2 Python3.14.8, GTK4.24.1, Adw1.10, libmpv0.41.0.
런타임은 `%LOCALAPPDATA%/BoraDev`, 검증 영상/로그/화면은 `%TEMP%/bora-windows-review`.

- 실제 재생 스파이크 반복 통과: GdkWin32GLContextWGL, 5초 동안150프레임,
  재생4.57→9.60초, hwdec=d3d11va-copy. 화면으로 실제 색상 테스트 영상 출력 확인.
- 자막 시나리오02: T1~T4 모두 통과. CP949 SAMI/짧은 SAMI/한영 통합/UTF-8 SRT.
- 메모 시나리오06: 14항목 통과. 한글 본문 저장/재열기/타임스탬프/자동 저장.
  GtkTextBuffer로 입력했으며 실제 IME나 키입력 검사는 아니다.
- 클립 시나리오09: 8항목 통과. 실제 ffmpeg 내보내기/디코딩/정확 모드15.000초/취소 정리.
- 일반 `run.ps1 --debug "한글 강의.mp4"` 실행: 한글·공백 경로, 실제 영상·CP949 "안녕하세요" 표시,
  검증용 창에 WM_CLOSE를 보내 종료. `cli-subtitle.png`에 캡처.
- 해당 실행에서 libmpv가 `Error decoding subtitle` 한 줄을 출력했으나 한글 표시는 정상.
  이 엔진 로그의 추가 원인 분석은 남았으며 로그를 숨기지 않았다.
- 전체 Python: **284 통과, 6 건너뜀**. Linux GIO2/설치 스크립트1/dpkg1/파일 symlink 권한2.
- 하네스: **8 통과, 2 건너뜀**. POSIX 전용 CI staging/프로세스 그룹 검사.
- Windows 전용 회귀에는 실제 PowerShell 프로세스 인자 전달과 실제 GIO argv 검사2가 포함된다.

## 실행 방법
```powershell
powershell -NoProfile -File src/bora/platform/windows/run.ps1 "영상 경로"
```

검증 런타임 준비/실패 이력은 [실측 기록](../research/2026-10-10-windows-runtime.md)에 남겼다.
개인 작업 레코드: `windows-playback-20261010` 및 이전 `windows-runtime-20261010`.
전체 하네스 검증과 현재 Git 상태를 확인한 뒤 커밋/push한다. 패키지는 로컬에서 만들지 않았다.

## 남은 수용 항목
portable 설치/재실행, 실제 IME/키입력, Windows10, Ubuntu GUI 회귀, STT 모델,
실제 사용자 CLI 계정 응답과 Windows 파일 ACL은 미검증이다.
