#!/usr/bin/env python3
"""시나리오 10 — 단축키 우선순위 · 메뉴 위치 · 로그 설정

  python3 .claude/skills/verify-app/scenarios/10-keys-and-logging.py

K1 키 컨트롤러가 CAPTURE 라 포커스된 버튼보다 먼저 받는다
K2 버튼에 포커스가 있어도 Space 가 일시정지를 건다
    (실제 버그: 파일 열기 버튼이 Space 를 삼켜 파일 탐색기가 열렸다)
K3 메모에 타이핑할 때는 글자 키가 단축키로 먹히지 않는다
K4 Ctrl·Alt 조합은 단축키로 가로채지 않는다
L1 로그 등급을 바꾸면 즉시 반영된다
L2 바꾼 등급이 설정에 저장된다
L3 파일로도 남길 수 있다
M1 하단 메뉴 버튼이 실제로 열린다 (창보다 긴 메뉴여도)
M2 우클릭 메뉴가 화면 네 귀퉁이 어디서든 잘리지 않는다
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from bora import log as logmod  # noqa: E402
from bora.app import BoraApplication  # noqa: E402
from bora.state import State  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def pump(seconds: float = 0.0) -> None:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while True:
        while ctx.pending():
            ctx.iteration(False)
        if time.monotonic() >= end:
            return
        time.sleep(0.02)


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-keys-"))
    cfg = folder / "cfg"
    try:
        video = folder / "v.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=320x240:rate=30:duration=30", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(video)],
            check=True,
        )

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
                self.win.state = State(cfg)
                GLib.timeout_add_seconds(3, self._run, self.win)

            def _run(self, win):
                try:
                    self._checks(win)
                except Exception as exc:            # noqa: BLE001
                    import traceback
                    check("시나리오가 끝까지 돌았다", False,
                          f"{exc.__class__.__name__}: {exc}")
                    traceback.print_exc()
                finally:
                    win.player.close()
                    self.quit()
                return False

            def _checks(self, win):
                none = Gdk.ModifierType(0)

                # K1 — CAPTURE 여야 포커스 위젯보다 먼저 받는다
                phases = [c.get_propagation_phase() for c in win.observe_controllers()
                          if isinstance(c, Gtk.EventControllerKey)]
                check("K1 키 컨트롤러가 CAPTURE",
                      Gtk.PropagationPhase.CAPTURE in phases,
                      str([p.value_nick for p in phases]))

                # K2 — 버튼에 포커스가 있어도 Space 가 일시정지
                focused = win.get_focus()
                before = win.player.paused
                win._on_key(None, Gdk.KEY_space, 0, none)
                check("K2 버튼 포커스에서도 Space 가 일시정지",
                      win.player.paused != before,
                      f"포커스={type(focused).__name__}, {before} -> {win.player.paused}")
                win._on_key(None, Gdk.KEY_space, 0, none)      # 되돌린다

                # K3 — 메모에서 타이핑하는 동안은 단축키가 아니다
                win.toggle_notes()
                pump()
                win._notes._view.grab_focus()
                pump()
                typing = win._typing()
                eaten = win._on_key(None, Gdk.KEY_s, 0, none)
                check("K3 메모 타이핑 중에는 글자 키를 가로채지 않는다",
                      typing and not eaten,
                      f"_typing()={typing}, 가로챔={eaten}")
                win.toggle_notes()
                pump()

                # K4 — Ctrl/Alt 조합은 통과
                ctrl = win._on_key(None, Gdk.KEY_s, 0, Gdk.ModifierType.CONTROL_MASK)
                check("K4 Ctrl 조합은 단축키로 먹지 않는다", not ctrl)

                # L1 — 등급 즉시 반영
                win._on_log_level(_Checked(True), "debug")
                check("L1 로그 등급이 즉시 바뀐다", logmod.level_name() == "debug",
                      logmod.level_name())

                # L2 — 저장
                check("L2 등급이 설정에 저장된다",
                      win.state.settings.log_level == "debug",
                      win.state.settings.log_level)
                saved = State(cfg)
                check("L2 다시 읽어도 남아 있다", saved.settings.log_level == "debug",
                      saved.settings.log_level)

                # L3 — 파일로 남기기
                win._on_log_to_file(_Checked(True))
                path = logmod.log_file_path()
                logmod.get("verify").debug("테스트 한 줄")
                for handler in logmod.get().handlers:
                    handler.flush()
                wrote = bool(path) and Path(path).is_file() and \
                    "테스트 한 줄" in Path(path).read_text(encoding="utf-8")
                check("L3 로그가 파일에 쌓인다", wrote, path or "경로 없음")

                win._on_log_level(_Checked(True), "warning")

                # M1 — 하단 메뉴 버튼. 메뉴가 창보다 길면 팝오버가 아예 뜨지 않는다
                # (항목이 늘어 767px 이 되자 눌러도 아무 일도 안 일어났다).
                win._menu_button.popup()
                pump(1.0)
                child = win._main_popover.get_child()
                _m, nat = child.get_preferred_size()
                check("M1 하단 메뉴가 열린다",
                      win._main_popover.get_visible() and nat.height <= win.get_height(),
                      f"visible={win._main_popover.get_visible()}, "
                      f"메뉴 {nat.height}px / 창 {win.get_height()}px")
                win._main_popover.popdown()
                pump(0.3)

                # M2 — 우클릭 메뉴가 네 귀퉁이에서 잘리지 않는다
                vw, vh = win._video.get_width(), win._video.get_height()
                bad = []
                for label, (cx, cy) in (("좌상", (5, 5)), ("우상", (vw - 5, 5)),
                                        ("우하", (vw - 5, vh - 5)), ("좌하", (5, vh - 5))):
                    win._on_right_click(None, 1, cx, cy)
                    pump(0.45)
                    rect = win._menu_popover.get_pointing_to()[1]
                    _mm, size = win._menu_popover.get_child().get_preferred_size()
                    inside = (rect.x - size.width / 2 >= -1
                              and rect.x + size.width / 2 <= vw + 1)
                    if not (inside and win._menu_popover.get_visible()):
                        bad.append(f"{label}→({rect.x},{rect.y})")
                    win._menu_popover.popdown()
                    pump(0.2)
                check("M2 우클릭 메뉴가 네 귀퉁이에서 화면 안에 들어온다",
                      not bad, ", ".join(bad) if bad else f"영상 {vw}x{vh}")

        class _Checked:
            """CheckButton 흉내 — 토글 핸들러는 get_active() 만 본다."""
            def __init__(self, value): self._v = value
            def get_active(self): return self._v

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 10 — 단축키·메뉴·로그 ===")
    failed = 0
    for name, ok, detail in results:
        print(f"  [{'통과' if ok else '실패'}] {name}" + (f"  ({detail})" if detail else ""))
        failed += (not ok)
    if not results:
        print("  결과가 없다 — 창이 뜨지 않았다")
        return 1
    print(f"\n{'전부 통과' if not failed else f'{failed}건 실패'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
