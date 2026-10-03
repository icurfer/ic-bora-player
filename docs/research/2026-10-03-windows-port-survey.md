# 조사 기록 — 윈도우 지원이 실제로 무엇을 요구하나 (2026-10-03)

기획서 `../spec/plan-v0.6.0.md` 의 근거.
**⚠ 이 문서의 상당 부분은 웹 조사이며 윈도우 실기 검증이 아니다.** 실측한 것과 조사한 것을
문단마다 구분해 적는다. 윈도우 머신(`lap-surface`, Surface Laptop 5 / Win11)이 조사 시점에
꺼져 있어(192.168.0.205 응답 없음) 실기 확인을 하지 못했다.

## 0. 결론 요약

| # | 사실 | 출처 | 의미 |
|---|---|---|---|
| A | 코드 6,904줄 중 **플랫폼에 묶인 것은 약 150줄**뿐이다 | **실측**(이 저장소) | 포팅 비용의 대부분은 코드가 아니라 배포다 |
| B | `util/gl.py` 가 `libEGL.so.1`·`libGL.so.1` 을 직접 연다 | **실측** | **하드 블로커.** 윈도우엔 그 파일이 없다 |
| C | gvsbuild 가 GTK4·PyGObject·libadwaita·pycairo 윈도우 빌드를 **한 묶음으로** 제공한다 | 웹 | "GTK4 윈도우 배포는 별도 프로젝트급"이라던 1차 판단은 **과했다** |
| D | 윈도우의 GL 진입점은 `wglGetProcAddress`(opengl32.dll)다 | 웹 | B 의 대응책. 다만 1.1 핵심 함수는 `GetProcAddress` 폴백이 필요하다 |
| E | GTK4 on Windows 에서 **GLArea + libmpv 조합이 실제로 도는지는 확인하지 못했다** | — | **가장 큰 미지수.** 여기가 막히면 설계를 바꿔야 한다 |

## 1. 코드가 얼마나 묶여 있나 (실측)

```bash
find src -name '*.py' | wc -l            # 38 모듈
wc -l src/bora/*.py src/bora/*/*.py      # 6904 줄
```

| 묶인 곳 | 규모 | 성격 |
|---|---|---|
| `util/gl.py` — `ctypes.CDLL("libEGL.so.1")`, `libGL.so.1` | 34줄 | **하드 블로커** |
| `desktop.py` — `.desktop`·xdg 기본앱 | 104줄 | 윈도우에선 통째로 비활성 |
| `stt/install.py`·`ai/client.py` — `~/.local/share` 직접 조립 | 2곳 | `GLib.get_user_data_dir()` 로 교체 가능 |
| venv 경로 `bin/python` | 2곳 | 윈도우는 `Scripts/python.exe` |
| `ffmpeg`/`ffprobe` 호출 | 10파일 | 실행명만 맞으면 그대로. 윈도우 바이너리 동봉 필요 |

**플랫폼과 무관한 부분**(그대로 쓸 수 있다): 자막 전처리 725줄, 메모 663줄,
클립 모델·판정·실행 666줄, 상태 231줄, 트랙 72줄, 로그 138줄 — 합쳐 약 2,500줄.
이 앱의 값어치(국내 자막 처리, 학습 도구, 컷 편집)는 전부 여기 있다.

## 2. GTK 스택 배포 (웹 조사)

[gvsbuild](https://github.com/wingtk/gvsbuild) — Windows 용 GTK 스택 빌드 도구.
최신 릴리스 **2026.8.0**(GLib 2.88.3), 2026.6.0 에서 GTK 4.22.4. 활발히 유지되고 있다.

> It comes with GTK4, Cairo, **PyGObject**, Pycairo, GtkSourceView5, adwaita-icon-theme,
> and all of their dependencies.

미리 빌드된 zip 을 `C:\gtk` 에 풀고 PATH 를 잡으면 된다. PyGObject·pycairo 는
**gvsbuild 가 만든 휠**을 써야 한다(업스트림 PyGObject 이슈 #545 회피).

> ⚠ 배포용으로는 직접 빌드를 권한다고 명시돼 있다("provided AS IS … We strongly
> recommend building your own binaries, especially if you plan to distribute them").
> 우리가 zip 을 그대로 재배포할지, CI 에서 빌드할지는 정해야 한다.

## 3. GL 진입점 (웹 조사 + 설계 판단)

리눅스에서는 `eglGetProcAddress` 하나로 끝난다. 윈도우는 두 단계다.

1. `wglGetProcAddress(name)` — 확장 함수는 여기서 나온다
2. 실패하면 `GetProcAddress(opengl32.dll, name)` — **OpenGL 1.1 핵심 함수는 1번이
   NULL 을 돌려준다.** 이 폴백이 없으면 `glGetIntegerv` 같은 것이 안 잡힌다

`current_fbo()` 가 쓰는 `glGetIntegerv` 가 바로 1.1 함수다 → 폴백 필수.

또한 **GTK4 가 윈도우에서 WGL 을 쓰는지 ANGLE(EGL)을 쓰는지**에 따라 달라진다.
ANGLE 경로면 EGL 쪽 조회가 맞다. 실기에서 `GDK_DEBUG` 로 확인해야 한다.

## 4. 확인하지 못한 것 — 여기가 위험의 전부다

| # | 미지수 | 왜 중요한가 | 어떻게 확인하나 |
|---|---|---|---|
| 1 | **GTK4(Windows) GLArea + libmpv 렌더가 도는가** | 막히면 렌더 전략을 바꿔야 한다(별도 컨텍스트 + 텍스처 복사 등) | 윈도우에서 최소 스파이크 — 창 하나 띄워 영상 한 편 |
| 2 | GTK4 가 쓰는 GL 백엔드(WGL / ANGLE) | §3 의 분기를 어느 쪽으로 쓸지 결정 | `GDK_DEBUG=opengl` 출력 |
| 3 | python-mpv 가 `libmpv-2.dll` 을 찾는가 | `ctypes.util.find_library('mpv')` 가 윈도우에서 동작하는 방식이 다르다 | 스파이크에서 함께 |
| 4 | 하드웨어 디코딩(d3d11va) | 1080p 이상 재생 품질 | `hwdec_current` 읽기 |
| 5 | 한글 글꼴·IME | 메모 입력이 핵심 기능이다 | 실기 타이핑 |
| 6 | libadwaita 가 윈도우에서 어떻게 보이는가 | GNOME 디자인이라 이질감이 있을 수 있다 | 눈으로 |

**1번이 막히면 이 기획은 다시 쓴다.** 그래서 순서를 "스파이크 먼저"로 잡는다(기획서 §7).

## 5. 참고

- gvsbuild — https://github.com/wingtk/gvsbuild
- gvsbuild 릴리스(2026.8.0) — https://github.com/wingtk/gvsbuild/releases
- winget 설치 — `winget install wingtk.gvsbuild.GTK4`
- libmpv + get_proc_address 사례 — https://discourse.libcinder.org/t/use-of-libmpv-and-getprocaddress/1535
- Celluloid 패턴(GTK4 GLArea 에 직접 렌더) 언급 — https://github.com/ophymx/mpv-engine
