# Windows 실행 환경 보완

기준: [기존 Windows 기획](plan-v0.6.0.md). W1~W7 수용 기준과 미검증 상태를 유지한다.

## 배치 위치
Windows 구현은 `src/bora/platform/windows/`의 gl/integration/paths/libraries/application과 개발 런처에 둔다.
공통 app/detect에는 플랫폼 진입점 호출만 추가하며 OS 조건은 넣지 않는다.

## 설정·비밀값 보관 위치
새 설정이나 비밀값 저장은 없다. 외부 터미널에는 호출자가 정리한 환경만 넘긴다.

## 따르는 기존 패턴
리눅스의 플랫폼 함수 계약을 유지하고, 미지원 항목은 구체적인 오류를 반환한다.

## 진단과 변경
2026-10-10 현재 PC에서 Python은 WindowsApps 별칭이며 Node.js가 PATH에 없다.
표준 설치 위치에서 GTK, libadwaita, libmpv를 찾지 못했다. 재생 검증 전에 런타임 준비가 필요하다.
기존 GL 코드는 WGL을 무조건 먼저 조회하고 FBO도 opengl32에서만 읽는다.
현재 WGL/EGL 컨텍스트에 맞는 함수 조회와 FBO 읽기로 바꾸며 WGL 오류 주소를 거른다.
외부 터미널은 PowerShell 새 콘솔로 열며 인자를 인코딩해 전달한다.
실측으로 확인한 uchardet DLL 탐색 실패는 플랫폼의 라이브러리 경로 함수로 해결한다.
자막 판정 단계나 임계값은 변경하지 않는다.
배치 실행 파일은 셸 메타문자 해석을 막기 위해 명시적으로 거절하고 exe/ps1 실행 경로를 안내한다.

## 검증
사용자 후속 요청에 따라 MSYS2 UCRT64 런타임을 사용자 로컬 BoraDev 폴더에 준비하고,
격리 영상으로 실제 앱 실행과 수정/재실행을 반복한다. 배포 패키지 생성은 하지 않는다.
Windows 네이티브 Python에서 플랫폼 함수 단위 검사를 실행한다.
GTK+libmpv 재생, 자막, IME, 하드웨어 디코딩, 클립, Windows 10/11 실기는 별도 관문이다.
이 검증을 끝내기 전 `verified()`와 지원 상태를 바꾸지 않는다.
