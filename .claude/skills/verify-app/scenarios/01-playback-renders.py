#!/usr/bin/env python3
"""시나리오 01 — 창이 뜨고 실제로 프레임이 렌더되는가 (scope §4 의 1단계)

  python3 .claude/skills/verify-app/scenarios/01-playback-renders.py <영상파일>

통과 기준:
  - GDK 백엔드가 GdkWaylandToplevel (XWayland 경유가 아니다)
  - 렌더 콜백이 한 번이라도 돌았다 (렌더 경로가 살아 있다)
  - 재생 위치가 0보다 크다 (디코딩되고 있다)
  - hwdec 이 'no' 가 아니다 (하드웨어 디코딩 활성 — 기획서 T6)

⚠ 초당 렌더 수는 **판정 기준으로 쓰지 않는다.** 창이 다른 창에 가려지거나 다른 워크스페이스에
   있으면 컴포지터가 프레임 콜백을 주지 않아 렌더가 뚝 떨어진다 — 앱 문제가 아닌데 실패로 잡힌다
   (실측: 같은 코드가 단독 실행 25.8/s, 다른 검증 직후 10/s 미만).
   참고값으로 출력만 하고, 낮으면 그 이유를 안내한다.
샘플 영상이 없으면 helpers/make_sample.sh 로 만든다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

import bora.player as player_mod  # noqa: E402
from bora import __version__  # noqa: E402
from bora.app import BoraApplication  # noqa: E402

SECONDS = 5
state = {"frames": 0, "report": {}}

# 렌더 횟수는 Player.render 에서 센다.
# GLArea 의 'render' 시그널에 핸들러를 덧붙이는 방법은 쓸 수 없다 — 앞선 핸들러가
# True 를 반환해 전파를 멈추기 때문에 절대 호출되지 않는다(실측으로 확인).
_orig_render = player_mod.Player.render


def _counting_render(self, w, h, fbo):
    state["frames"] += 1
    return _orig_render(self, w, h, fbo)


player_mod.Player.render = _counting_render


class Probe(BoraApplication):
    def do_activate(self):
        super().do_activate()
        win = self.props.active_window
        GLib.timeout_add_seconds(SECONDS, self._finish, win)

    def _finish(self, win):
        p = win.player
        state["report"] = {
            "버전": __version__,
            "GDK 백엔드": type(win.get_surface()).__name__,
            "렌더 콜백": state["frames"],
            "초당 렌더": round(state["frames"] / SECONDS, 1),
            "재생 위치(초)": round(p.time_pos or 0, 2),
            "hwdec 실제": p.hwdec_current,
        }
        p.close()
        self.quit()
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: 01-playback-renders.py <영상파일>", file=sys.stderr)
        return 2
    Probe().run([sys.argv[0], sys.argv[1]])
    r = state["report"]
    print("=== 시나리오 01 — 재생·렌더 ===")
    for k, v in r.items():
        print("  %-14s %s" % (k, v))

    fails = []
    if "Wayland" not in r.get("GDK 백엔드", ""):
        fails.append("Wayland 네이티브가 아니다")
    if r.get("렌더 콜백", 0) <= 0:
        fails.append("렌더 콜백이 한 번도 돌지 않았다 — 화면에 아무것도 그려지지 않는다")
    if r.get("재생 위치(초)", 0) <= 0:
        fails.append("재생이 진행되지 않았다")
    if r.get("hwdec 실제", "no") == "no":
        fails.append("하드웨어 디코딩이 비활성 (기획서 T6)")

    if 0 < r.get("초당 렌더", 0) < 10:
        print("\n  참고: 초당 렌더가 낮다. 창이 가려졌거나 다른 워크스페이스에 있으면"
              " 컴포지터가 프레임을 주지 않아 정상이어도 이렇게 나온다.")

    if fails:
        print("\n실패:")
        for f in fails:
            print("  - " + f)
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
