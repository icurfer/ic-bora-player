# Windows 실행 환경 실측

## 최신 결과 — 런타임 준비 이후
MSYS2 공식 base tar.xz를 `%LOCALAPPDATA%/BoraDev`에 풀고 서명 검증하는 pacman으로
UCRT64 gtk4/libadwaita/python-gobject/python-cairo/python-pytest/python-charset-normalizer/
mpv/ffmpeg/python-pip 패키지를 설치했다. Python3.14.8, GTK4.24.1, Adw1.10, mpv0.41.0.
python-mpv1.0.8 휠 SHA256을 PyPI 메타데이터와 대조한 후
`pip --target %LOCALAPPDATA%/BoraDev/python-packages`로 설치했다.
관리 패키지 환경을 강제로 덮어쓰지 않았다. 시스템 PATH는 바꾸지 않았다.

환경변수는 검사 프로세스에서만 설정했다.
```powershell
$env:PATH = "$env:LOCALAPPDATA/BoraDev/msys64/ucrt64/bin;C:/Program Files/Git/bin;$env:PATH"
$env:PYTHONPATH = "$env:LOCALAPPDATA/BoraDev/python-packages;$(Get-Location)/src"
$env:PYTHONUTF8 = '1'
```

- 스파이크 반복: WGL, 5초150프레임, 재생 위치 증가, d3d11va-copy 통과.
- 실제 화면: `playback-full.png`, `cli-subtitle.png` (모두 `%TEMP%/bora-windows-review`).
- 자막 T1~T4, 메모14·클립8항목 통과. 메모 입력은 위젯 API이며 IME/키입력 E2E가 아니다.
- 전체 pytest284 통과·6 환경 검사 건너뜀. 하네스8 통과·2 플랫폼 검사 건너뜀.
- GIO argv 보정 뒤 일반 `python -m bora` 개발 런처도 한글/공백 경로를 정확히 열었다.
- 실제 MSYS2 venv 생성(`--without-pip`)과 bin/python.exe 실행을 확인하고 플랫폼 경로 함수를 보완했다.
- SAMI에서 mpv가 libass 디코딩 오류 한 줄을 출력했으나 화면의 "안녕하세요"는 정상.
  엔진 로그의 추가 원인 분석은 아직 남았다.
- 아래 초기 환경/실패 기록은 런타임 준비 전의 이력이며 최신 결과보다 우선하지 않는다.

## 실제 실행 반복에서 발견한 자막 DLL 문제
MSYS2 런타임 준비 뒤 전체 pytest에서 일본어/중국어 자막 판정 3개가 실패했다.
`ctypes.util.find_library('uchardet')`는 None, `detect._UCHARDET`도 None이었다.
반면 같은 프로세스의 `ctypes.CDLL('libuchardet.dll')`는 성공했다.
설치된 DLL을 찾지 못해 기존 Linux `.so` 폴백으로 가는 것이 원인이다.
자막 판정 순서는 유지하고 Windows 플랫폼에서 DLL 이름을 제공하도록 고친다.

```powershell
& $python -c "import ctypes,ctypes.util; from bora.subtitle import detect; print(ctypes.util.find_library('uchardet'),detect._UCHARDET); print(ctypes.CDLL('libuchardet.dll'))"
```

## Windows GApplication 인자 재해석
시나리오06은 생성한 lecture.mp4 대신 06-notes-panel.py를 영상으로 열었고,
검증 스크립트 옆에 `# 06-notes-panel` 메모를 생성했다. time_pos는 None이며 시나리오는 시간 초과했다.
GIO 공식 [run 문서](https://docs.gtk.org/gio/method.Application.run.html)는 Windows에서
넘겨받은 argv를 무시하고 원래 프로세스 명령줄을 읽는다고 명시한다.
Windows 플랫폼 기반 클래스에서 정규화한 argv를 GIO register/open/activate로 처리한다.
검증이 생성한 스크립트 옆 메모는 내용 확인 후 삭제하며 사용자 메모는 건드리지 않는다.

## 환경
- Windows 레지스트리: DisplayVersion 25H2, CurrentBuild 26200, x64.
- ProductName은 Windows 10 Pro로 남아 있어 이 문자열만으로 제품 버전을 판정하지 않는다.
- `python --version`: WindowsApps 별칭이 `Python`만 출력하며 종료 코드 1.
- `where.exe node`: 찾지 못함.
- `C:/msys64`, `C:/gtk`, `C:/GTK-build`, 표준 Python 설치 경로에서 런타임을 찾지 못함.
- `codex.exe`, `claude.exe`는 명령 탐색에서 발견. 계정 실행은 하지 않음.

## 검증 도구
저장소 밖 `%TEMP%/bora-windows-tools`에 공식 Python 3.13.7 embeddable와
Node.js 22.20.0을 내려받았다. 배포 패키지를 만들거나 시스템 PATH를 변경하지 않았다.

## 재현 명령과 결과
임시 Python을 `$python`으로 지칭한다.

```powershell
& $python tests/test_windows_runtime.py
& $python .claude/skills/verify-app/scenarios/win-01-spike.py sample.mp4
```

- Windows 플랫폼 회귀: 11개 통과. GL 조회는 모의 컨텍스트로 검사.
- 그중 1개는 실제 Windows PowerShell → Python 프로세스를 실행해 한글, 공백,
  따옴표, 셸 메타문자, 줄바꿈, 빈 인자가 그대로 전달되는지 확인.
- 실제 `opengl32.dll` 로드 성공. GL 컨텍스트 생성/렌더 성공의 증거는 아니다.
- `importlib.util.find_spec`: gi, mpv, pytest, charset_normalizer 모두 없음.
- 재생 스파이크: `ModuleNotFoundError: No module named 'gi'`, 종료 코드 1.
  영상 인자 검사보다 앞선 import에서 중단. sample.mp4는 존재하는 재생 표본이 아니다.
  GTK 창, libmpv 로드, 렌더, 재생, 자막, 하드웨어 디코딩은 실행되지 않았다.

## 코드 결함 근거
기존 코드에서는 opengl32 존재만으로 WGL 주소를 먼저 조회하고 FBO도 그 DLL에서 읽었다.
ANGLE의 활성 EGL 컨텍스트를 선택하는 경로가 없었다. 현재 컨텍스트를 조회하도록 보완했다.
WGL 실패 주소 1/2/3/-1 처리는 [Khronos 함수 로드 문서](https://wikis.khronos.org/opengl/Load_OpenGL_Functions)를 따랐다.
실제 재생에서 이 결함이 나타났다는 주장은 하지 않는다.

## 남은 환경
호환되는 Python/PyGObject/GTK4/libadwaita, python-mpv/libmpv,
charset-normalizer/pytest, ffmpeg/ffprobe와 격리 영상 표본을 준비한 뒤 스파이크를 다시 실행한다.
재생 성공 뒤에도 자막, IME, 클립과 W1~W7 수용 검증이 남는다. Windows 지원은 미검증이다.
