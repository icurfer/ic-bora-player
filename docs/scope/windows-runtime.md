# Windows 실행 환경 보완 범위

- `windows/gl.py`: 현재 컨텍스트 선택, WGL 오류 주소 제거, EGL/GLES 함수 조회, 현재 FBO 조회.
- `windows/integration.py`: `launch_terminal`의 PowerShell 새 콘솔과 오류 처리.
- `tests/test_windows_runtime.py`: GTK 없이 Windows 플랫폼 모듈을 직접 로드해 회귀 검사.
- 환경 진단과 실제 실행 시도의 결과를 research/done 및 인수인계에 기록.
- GTK 의존성이 없는 단위 검사는 GUI E2E로 집계하지 않는다.
- Windows 런타임 준비, 격리 테스트 영상 생성, 실제 앱 스파이크 및 오류 반복 수정.
- `windows/run.ps1`: 준비된 사용자 로컬 런타임으로 앱을 실행하는 개발 진입점.
- `win-01-spike.py`: 현재 GL 컨텍스트를 명시하고 실제 렌더 컨텍스트 존재도 검사.
- 하네스 회귀 fixture: URL을 OS 경로로 변환하고 디렉터리 링크에는 junction을 사용해 Windows 권한 없이 같은 보호 계약을 검사.
- 검증 helper `capture-windows.ps1`: 검증용 PID의 창만 화면 또는 PrintWindow로 캡처. DPI 보정 포함.
- `windows/libraries.py`와 공통 플랫폼 진입점: uchardet DLL 경로를 제공.
- `subtitle/detect.py`: 플랫폼 제공 경로로 라이브러리를 로드하며 판정 알고리즘 유지.
- `windows/paths.py`: 실측한 MSYS2 bin venv와 정식 CPython Scripts venv 경로를 구분.
- `windows/application.py`: GIO의 원래 Windows 명령줄 대신 정규화한 Python argv를 사용.
  `app.py`는 플랫폼 제공 기반 클래스를 사용하며 OS 분기를 두지 않는다.
- 시나리오06/09의 이벤트 처리 횟수를 제한해 연속 렌더에서도 대기 조건을 검사한다.
- 기존 Python fixture를 실제 Python 프로세스로 실행하고 JSON/플랫폼 경로 계약을 검사.
  Linux GIO/설치 스크립트/dpkg와 권한 없는 파일 symlink 검사는 명시적으로 건너뛴다.
