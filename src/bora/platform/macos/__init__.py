"""macOS — **뼈대만 있다. 조사도 검증도 하지 않았다.**

윈도우(v0.6)와 다른 점을 미리 적어 둔다. 실제로 하려면 조사부터 한다.

| | 리눅스 | macOS 에서 달라지는 것 |
|---|---|---|
| GTK4 백엔드 | Wayland/X11 | **Quartz**. GTK4 의 macOS 백엔드는 리눅스만큼 다듬어져 있지 않다 |
| GL | EGL | **CGL/NSOpenGL**. 게다가 애플은 OpenGL 을 deprecated 로 두었다(Metal 권장) |
| libmpv | apt | `brew install mpv` 로 dylib 확보 |
| 경로 | XDG | `~/Library/Application Support` 등 — GLib 이 대체로 맞게 준다 |
| 배포 | deb | `.app` 번들 + 공증(notarization). **애플 개발자 계정이 필요하다** |
| 기본 재생기 | xdg-mime | Launch Services (`LSSetDefaultRoleHandlerForContentType`) |

**가장 큰 미지수**: GTK4 Quartz 백엔드에서 GLArea + libmpv 가 도는가.
OpenGL deprecated 와 맞물려 윈도우보다 위험이 크다고 본다 — 근거 없는 낙관을 적지 않는다.

기기가 없어 검증할 수 없다(`inno/mac/`, `hm-lab/mac-intel/` 에 맥이 있지만 이 작업에
쓸 수 있는지는 확인하지 않았다).
"""
