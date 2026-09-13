# 실측 기록 3 — GTK4 렌더 스파이크와 22.04 호환성 (2026-09-13)

기획서 [`../spec/plan-v0.1.0.md`](../spec/plan-v0.1.0.md) **§8-3 · §8-5 · §8-7** 검증.
§7 이 "가장 먼저 하라"고 지목한 최대 위험(렌더 연동 실패 → C 포크 전환)을 확인하는 것이 목적이다.

재현 스크립트: [`scripts/spike_gtk4.py`](scripts/spike_gtk4.py), [`scripts/jammy_check.sh`](scripts/jammy_check.sh)

## 0. 결론 요약

| # | 항목 | 결과 |
|---|---|---|
| 8-3 | python-mpv 렌더 컨텍스트 + GtkGLArea | **동작한다.** Wayland 네이티브, 1080p H.264 드랍 0, 하드웨어 디코딩 활성 |
| 8-5 | jammy `python3-mpv 0.5.2` 의 렌더 API | **심볼이 전부 있다.** libmpv 인스턴스 생성까지 정상 (실제 렌더는 미검증) |
| 8-7 | jammy 에서 `find_library('mpv')` | **`libmpv.so.1` 을 정상 반환.** 분기 코드가 필요 없다 |

→ **언어 결정(Python)을 바꿀 이유가 없다.** §7 의 최대 위험이 해소됐다.
→ **A안(시스템 패키지)의 실현 가능성이 기획 시점보다 높아졌다.** 남은 장벽은 UI 툴킷 버전뿐이다(§3).

## 1. §8-3 렌더 스파이크 — lab(26.04)

환경: Ubuntu 26.04 · GNOME Wayland · mpv/libmpv 0.41.0 · python3-mpv 1.0.8 ·
GTK **4.22.4** · libadwaita **1.9.0** · python3-gi 3.56.2

`Adw.ApplicationWindow` + `Gtk.GLArea`(`set_auto_render(False)`) 에 `mpv.MpvRenderContext(api_type='opengl')`
를 붙이고 1080p H.264 10초 파일을 4초간 재생했다.

```
GDK 백엔드        GdkWaylandToplevel      ← XWayland 경유가 아니다
렌더 콜백 호출       123                     ← 4.07초 동안 약 30fps
mpv 버전          mpv v0.41.0
재생 위치(초)       4.07
hwdec 요청         auto-safe
hwdec 실제         vulkan-copy             ← 하드웨어 디코딩 활성
영상 코덱          H.264 / AVC / MPEG-4 AVC
해상도            1920x1080
드랍 프레임        0
vo               libmpv
```

### 실무적으로 중요한 세부

- **PyOpenGL 이 필요 없다.** `get_proc_address` 는 `libEGL.so.1` 의 `eglGetProcAddress` 를,
  현재 FBO 조회는 `libGL.so.1` 의 `glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING=0x8CA6)` 를
  ctypes 로 직접 부르면 된다. 의존성이 하나 줄어든다.
- 콜백 타입 이름은 **`mpv.MpvGlGetProcAddressFn`** 이다(`OpenGlCbGetProcAddrFn` 은 옛 이름 — 예제가 낡았다).
- `ctx.update_cb` 에서 `GLib.idle_add(area.queue_render, priority=GLib.PRIORITY_HIGH)` 로 넘긴다.
- `ctx.render(flip_y=True, opengl_fbo={'w':…, 'h':…, 'fbo': 현재FBO})` — 크기는 `get_scale_factor()` 를 곱한다.
- `hwdec=auto-safe` 가 고른 것은 **VA-API 가 아니라 `vulkan-copy`** 였다.
  기획서 §6 T6 의 기준은 "VA-API"인데 실제로는 Vulkan 경로가 잡힌다 — **T6 의 판정 기준을 고쳐야 한다**
  ("하드웨어 디코딩이 활성인가"로. 어느 백엔드인지는 환경마다 다르다).

## 2. §8-5 · §8-7 — jammy(22.04) 호환성

`docker run --rm ubuntu:22.04` 안에서 `python3-mpv libmpv1 python3-gi gir1.2-gtk-4.0` 설치 후 측정.

```
libgtk-4-1     4.6.9+ds-0ubuntu0.22.04.2
libmpv1        0.34.1-1ubuntu3
python3-mpv    0.5.2-3

find_library('mpv')  ->  'libmpv.so.1'      (→ libmpv.so.1.109.0)

python-mpv 0.5.2 의 렌더 심볼:
  MpvRenderContext, MpvRenderCtxHandle, MpvRenderFrameInfo, MpvRenderParam,
  RenderUpdateFn, _mpv_render_context_create/_render/_free/_update/...
  (+ 구식 _mpv_opengl_cb_render 도 남아 있다)

libmpv 로드/인스턴스 생성: OK,  mpv-version = mpv 0.34.1
```

- **8-7 해소**: `ctypes.util.find_library('mpv')` 가 jammy 에서도 정상 동작한다.
  `.so.1` / `.so.2` 분기 코드를 쓸 필요가 없다.
- **8-5 부분 해소**: 렌더 API 심볼이 존재하고 `MpvRenderContext` 클래스가 있다.
  ⚠ **다만 컨테이너에는 GL 컨텍스트가 없어 "실제로 렌더되는지"는 검증하지 못했다.**
  0.5.2 와 1.0.8 의 인자 이름이 다를 가능성도 남아 있다. 22.04 실기·VM 에서 §1 스파이크를 그대로 돌려야 확정된다.

## 3. 배포 방식(§8-1)에 주는 영향 — 아직 결정하지 않았다

기획서 §4 는 A안(시스템 패키지)의 불확실성으로 세 가지를 들었다. 그중 둘이 해소됐다.

| 기획 시점의 우려 | 지금 |
|---|---|
| jammy `python3-mpv 0.5.2` 가 렌더 API 를 지원하는지 미확인 | 심볼 존재·인스턴스 생성 확인 (실렌더 미검증) |
| `libmpv1`(.so.1) 을 `find_library` 가 찾는지 미확인 | 정상 반환 — 분기 불필요 |
| **GTK 4.6 / libadwaita 1.1 에 없는 위젯** | **그대로 남아 있다.** jammy 는 GTK 4.6.9 · libadwaita 1.1 |

→ 남은 장벽은 **UI 툴킷 버전 하나**다. `ToolbarView`(1.4) · `Dialog`(1.5) · `SpinRow`(1.4) 를
쓰지 않고 1.1 범위로 UI 를 짜면 A안이 성립한다. 이는 **UI 설계 제약을 받아들이느냐**의 문제이지
기술적 불가능이 아니다.

**8-1 은 여전히 미결이다.** 결정하려면 22.04 실기 또는 VM 에서
(1) §1 스파이크 그대로 실행, (2) Flatpak 판 하드웨어 디코딩 확인 — 두 가지가 필요하다.
이 머신에는 `qemu-system-x86_64` 와 `/dev/kvm` 은 있으나 virt-manager·multipass 는 없고,
Flatpak 도 설치돼 있지 않다.

## 4. 아직 검증하지 않은 것

- 22.04 실기/VM 에서의 실제 렌더 (8-5 의 남은 절반, 8-1 의 전제)
- Flatpak 런타임에서의 하드웨어 디코딩과 포털 권한 (8-1 · 8-2)
- 창 크기 변경·전체화면 전환 시 렌더 안정성, 여러 파일 연속 재생 시 컨텍스트 재사용
- `vulkan-copy` 외 환경(NVIDIA, 구형 인텔)에서 `auto-safe` 가 무엇을 고르는지
