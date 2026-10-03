#!/usr/bin/env python3
"""윈도우 스파이크 — GTK4 + GLArea + libmpv 가 윈도우에서 도는가 (기획서 v0.6 §7-1)

  python win-01-spike.py <영상파일>

**이 하나가 윈도우 지원의 전부를 가른다.** 막히면 기획을 다시 쓴다(별도 GL 컨텍스트 +
텍스처 복사가 차선). 리눅스에서도 돌아가므로 먼저 리눅스에서 "통과"를 확인한 뒤,
같은 스크립트를 윈도우에서 돌려 비교한다.

보는 것
  S1 GTK4 창이 뜨고 GL 컨텍스트가 잡히는가
  S2 libmpv 가 로드되는가 (윈도우는 libmpv-2.dll)
  S3 GL 진입점 조회가 되는가 (윈도우: wglGetProcAddress + GetProcAddress 폴백)
  S4 렌더 콜백이 실제로 불리는가 — **여기가 핵심**
  S5 재생 위치가 흐르는가
  S6 하드웨어 디코딩이 붙는가 (윈도우는 d3d11va 기대)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="bora-cfg-")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: win-01-spike.py <영상파일>")
        return 2
    video = Path(sys.argv[1])
    if not video.is_file():
        print(f"파일이 없다: {video}")
        return 2

    from bora.platform import name as platform_name  # noqa: E402
    from bora.platform import gl as platform_gl  # noqa: E402

    print(f"플랫폼: {platform_name()}  ·  파이썬 {sys.version.split()[0]}")
    print(f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}."
          f"{Gtk.get_micro_version()}  ·  Adw {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}")
    print(f"GDK_DEBUG={os.environ.get('GDK_DEBUG', '(미설정)')}  "
          f"— GL 백엔드를 보려면 GDK_DEBUG=opengl 로 띄운다")

    # S3 — GL 진입점 (창 없이도 라이브러리 로드는 확인된다)
    check("S3 GL 라이브러리를 열었다", platform_gl.available())

    # S2 — libmpv
    try:
        from bora.player import Player  # noqa: E402
        check("S2 libmpv 바인딩 로드", True)
    except Exception as exc:                        # noqa: BLE001
        check("S2 libmpv 바인딩 로드", False, f"{type(exc).__name__}: {exc}")
        _report()
        return 1

    # 렌더 횟수는 Player.render 를 감싸서 센다. GLArea 의 'render' 시그널에 핸들러를
    # 덧붙이는 방법은 쓸 수 없다 — 앞선 핸들러가 전파를 멈춘다(시나리오 01 과 같은 이유).
    from bora import player as player_mod  # noqa: E402

    rendered = {"n": 0}
    _orig_render = player_mod.Player.render

    def _counting_render(self, w, h, fbo):
        rendered["n"] += 1
        return _orig_render(self, w, h, fbo)

    player_mod.Player.render = _counting_render

    from bora.app import BoraApplication  # noqa: E402

    class Spike(BoraApplication):
        def do_activate(self):
            super().do_activate()
            self.win = self.props.active_window
            GLib.timeout_add_seconds(4, self._run, self.win)

        def _run(self, win):
            try:
                area = win._video
                context = area.get_context()
                check("S1 GL 컨텍스트가 잡혔다", context is not None,
                      type(context).__name__ if context else "없음")
                # 창에서 실제로 조회되는지 (컨텍스트가 현재일 때)
                addr = platform_gl.get_proc_address(None, b"glGetString")
                check("S3 glGetString 주소를 얻었다", addr != 0, hex(addr))
                fbo = platform_gl.current_fbo()
                check("S3 현재 FBO 를 읽었다", isinstance(fbo, int), str(fbo))

                before = rendered["n"]
                ctx = GLib.MainContext.default()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    while ctx.pending():
                        ctx.iteration(False)
                    time.sleep(0.05)
                after = rendered["n"]
                check("S4 렌더 콜백이 불린다 ★핵심", after - before > 5,
                      f"{before} → {after} (5초 동안 {after - before}회)")

                position = win.player.time_pos
                check("S5 재생 위치가 흐른다", (position or 0) > 0.3,
                      f"{position}")
                hw = win.player.hwdec_current
                check("S6 하드웨어 디코딩", hw not in ("", "no"), hw)
            except Exception as exc:                # noqa: BLE001
                import traceback
                traceback.print_exc()
                check("스파이크가 끝까지 돌았다", False, f"{type(exc).__name__}: {exc}")
            finally:
                win.player.close()
                self.quit()
            return False

    Spike(non_unique=True).run([sys.argv[0], str(video)])
    return _report()


def _report() -> int:
    print("\n=== 윈도우 스파이크 (기획서 v0.6 §7-1) ===")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'통과' if ok else '실패'}] {name}" + (f"  ({detail})" if detail else ""))
        failed += (not ok)
    if not results:
        print("  결과가 없다 — 창이 뜨지 않았다")
        return 1
    print(f"\n{'전부 통과 — 윈도우 지원을 진행할 수 있다' if not failed else f'{failed}건 실패'}")
    if failed:
        print("S4 가 실패했다면 GLArea 직접 렌더가 불가능하다는 뜻이다 — 기획서 §6 의 차선으로 간다")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
