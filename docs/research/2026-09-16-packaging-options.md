# 실측 기록 8 — 배포 방식: deb · 컨테이너 · Flatpak (2026-09-16)

질문: **"dpkg 로 만들 수 있나? 의존성 걸리나? 컨테이너는? 그건 서버 방식이라 안 맞나?"**
답을 추측하지 않으려고 실제로 deb 를 만들어 설치해 봤다.

## 0. 결론

| 방식 | 되나 | 이 프로젝트에 맞나 |
|---|---|---|
| **deb (dpkg)** | ✅ **된다. 만들어서 설치까지 확인했다** | ✅ **가장 맞다** — 56 KB, 의존성 4개 |
| 컨테이너(Docker/Podman) | ◐ 되지만 번거롭다 | ❌ **직관이 맞다** — 서버용이다(§3) |
| Flatpak | ✅ 된다 | ◐ 파일 접근 제약이 있다(research 4) |
| pipx / 소스 실행 | ✅ | ◐ 개발용 |

## 1. deb — 실제로 만들었다

`scripts/build-deb.sh`. debhelper 없이 `dpkg-deb` 로 직접 조립한다 — 순수 파이썬이라
빌드 단계가 없다(`Architecture: all`).

```
dist/bora_0.16.0_all.deb   56 KB (설치 후 296 KB)
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-mpv
Recommends: ffmpeg, fonts-noto-cjk
```

설치 후 확인한 것:
- `/usr/bin/bora` 로 실행된다
- 앱 목록에 뜨고 영상 MIME 이 연결된다
- 실제 재생 확인 (4.1초 재생, `hwdec=vulkan-copy`)

## 2. 의존성 — 가볍다

Bora 가 실제로 import 하는 외부 모듈은 **두 개뿐**이다:

```
gi   -> python3-gi      (+ gir1.2-gtk-4.0, gir1.2-adw-1)
mpv  -> python3-mpv     (이것이 libmpv2 를 알아서 끌고 온다)
```

나머지(`argparse ctypes dataclasses hashlib json locale logging os pathlib re shutil
subprocess sys threading time typing`)는 전부 **파이썬 표준 라이브러리**다.

### 22.04 호환

`libmpv2` 는 24.04+ 이고 22.04 는 `libmpv1` 이다. 그런데 **우리가 직접 적을 필요가 없다** —
`python3-mpv` 가 각 릴리스에서 알맞은 것을 의존한다. `Depends` 에 `python3-mpv` 만 적으면 된다.

### 선택 기능은 deb 에 넣지 않는다

`anthropic`(AI 질의)과 `faster-whisper`(텍스트 추출)는 **데비안 패키지가 없고** 모델까지 수백 MB 다.
deb 에서 빼고 설치 후 `scripts/install-ai.sh` · `install-stt.sh` 로 각자 넣게 한다.
`Suggests: python3-venv` 로 힌트만 남긴다.

## 3. 컨테이너 — "서버 방식이라 안 맞나?" 는 맞는 직관이다

Docker·Podman 으로 GUI 앱을 돌릴 수는 있다. 그러나 데스크톱 플레이어에는 어긋난다:

| 필요한 것 | 컨테이너에서 |
|---|---|
| 창 띄우기 | Wayland 소켓(`$XDG_RUNTIME_DIR/wayland-0`)을 마운트해야 한다 |
| 하드웨어 디코딩 | `/dev/dri` 를 넘기고 드라이버 버전을 맞춰야 한다 |
| 소리 | PipeWire/PulseAudio 소켓을 마운트해야 한다 |
| **사용자 영상 파일** | 볼륨을 일일이 마운트해야 한다 — 파일 관리자에서 더블클릭이 안 된다 |
| 메모·설정 저장 | 호스트 경로를 또 마운트해야 한다 |

컨테이너는 **서비스를 격리해 돌리는 도구**다. 사용자의 파일을 열고 화면에 그리고 설정을 남기는
데스크톱 앱과는 방향이 반대다. 마운트를 다 뚫고 나면 격리가 남지 않는다.

**다만 "컨테이너 기술로 데스크톱 앱을 배포하는" 방식은 따로 있다** — Flatpak·Snap 이다.
Flatpak 은 이미 검토했고(research 4), **파일 선택 포털이 고른 파일 하나만 노출해** 동명 자막
자동 로드가 막힌다. `--filesystem=host:ro` 로 풀 수는 있으나 그러면 샌드박스 이점이 대부분 사라진다.

## 4. 그래서

**deb 를 주 배포 수단으로 삼는다.** 가볍고(56 KB), 의존성이 네 개뿐이고, 파일 접근 제약이 없어
"영상 옆 자막·메모"라는 이 앱의 방식과 맞는다.

Flatpak 은 Flathub 배포가 필요해지면 그때 다시 본다. 컨테이너는 쓰지 않는다.

## 5. 걸린 것 두 가지

1. **설치본 버전이 0.0.0 으로 떴다.** `__init__` 이 저장소의 `version` 파일을 읽는데 설치본에는
   없다. 빌드가 `_BUILD_VERSION` 을 코드에 심도록 고쳤고, 심지 못하면 빌드를 실패시킨다.
2. **`~/.local/bin/bora` 가 `/usr/bin/bora` 를 가린다.** 개발용 `install-desktop.sh` 와 deb 를
   같이 두면 PATH 우선순위 때문에 옛 것이 실행된다. 스크립트에 주의를 적고 `--remove` 로 걷어냈다.
