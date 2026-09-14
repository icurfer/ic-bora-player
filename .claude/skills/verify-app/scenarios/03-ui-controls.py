#!/usr/bin/env python3
"""시나리오 03 — UI 동작 (scope §4 7단계)

  python3 .claude/skills/verify-app/scenarios/03-ui-controls.py [영상파일]

키 입력·드래그는 합성 이벤트로 자동화하기 어렵고 Wayland 에서는 더 그렇다.
그래서 **핸들러를 직접 불러** 상태 변화를 확인한다. 위젯이 실제로 연결돼 있는지는
컨트롤러 존재 여부로 함께 본다.

확인하는 것
  - 재생/일시정지 토글
  - 탐색(상대 이동)
  - 볼륨 조절이 슬라이더와 함께 움직이는가
  - 전체화면 토글과 버튼 아이콘 전환
  - 자막 싱크 단축키가 값과 UI 를 같이 바꾸는가
  - 드롭 처리: 영상+자막을 함께 떨궜을 때, 자막만 떨궜을 때
  - DropTarget / KeyController 가 실제로 붙어 있는가
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import bora.player as player_mod  # noqa: E402
from bora.app import BoraApplication  # noqa: E402

# 렌더 횟수를 센다 — 창 크기가 바뀐 뒤 다시 그려지는지 확인하려고.
_orig_render = player_mod.Player.render


def _counting_render(self, w, h, fbo):
    state["renders"] += 1
    return _orig_render(self, w, h, fbo)


player_mod.Player.render = _counting_render

results: list[tuple[str, bool, str]] = []
state = {"renders": 0}


def wait_until(cond, timeout: float) -> bool:
    """메인 루프를 돌리며 조건이 참이 되기를 기다린다."""
    import time

    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def make_media(folder: Path) -> tuple[Path, Path]:
    video = folder / "movie.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "ultrafast", str(video)],
        check=True,
    )
    if not (FIXTURES / "sample_cp949.smi").exists():
        subprocess.run([sys.executable, str(FIXTURES / "make_fixtures.py")], check=True)
    sub = folder / "other-name.smi"          # 일부러 영상과 다른 이름
    shutil.copy(FIXTURES / "sample_cp949.smi", sub)
    return video, sub


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-ui-"))
    try:
        video, sub = make_media(folder)

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
                GLib.timeout_add_seconds(3, self._run, self.win)

            def _run(self, win):
                p = win.player

                # 컨트롤러가 실제로 붙어 있는가
                has_drop = has_key = False
                for ctrl in win.observe_controllers():
                    has_drop = has_drop or isinstance(ctrl, Gtk.DropTarget)
                    has_key = has_key or isinstance(ctrl, Gtk.EventControllerKey)
                check("DropTarget 연결(창 전체)", has_drop)
                check("KeyController 연결", has_key)

                # 재생/일시정지
                before = p.paused
                win.toggle_pause()
                check("일시정지 토글", p.paused != before, f"{before} -> {p.paused}")
                win.toggle_pause()

                # 탐색
                start = p.time_pos or 0
                p.seek_relative(3)
                moved = (p.time_pos or 0) - start
                check("탐색(+3초)", moved > 1.0, f"{start:.2f} -> {p.time_pos:.2f}")

                # 볼륨
                win._nudge_volume(-20)
                check("볼륨 조절", abs(p.volume - 80) < 1 and abs(win._vol_scale.get_value() - p.volume) < 1,
                      f"volume={p.volume}, slider={win._vol_scale.get_value()}")

                # 정지 — 처음으로 되돌리고 멈춘다. 파일은 열린 채여야 한다.
                p.seek_absolute(4)
                wait_until(lambda: (p.time_pos or 0) > 2, 3.0)
                win.stop()
                # seek 는 즉시 반영되지 않는다. time_pos 가 실제로 돌아갈 때까지 기다린다.
                wait_until(lambda: (p.time_pos or 99) < 1.0, 3.0)
                pos = p.time_pos or 0
                check("정지(처음으로 + 일시정지)", pos < 1.0 and p.paused,
                      f"time_pos={pos:.2f}, paused={p.paused}")
                check("정지 후에도 파일이 열려 있다", (p.duration or 0) > 0,
                      f"duration={p.duration}")
                win.toggle_pause()       # 다시 재생

                # 전체화면 — fullscreen() 은 비동기라 상태가 반영될 때까지 기다린다
                renders_before = state["renders"]
                win.set_fullscreen(True)
                wait_until(lambda: win.is_fullscreen(), 3.0)
                check("전체화면 상태 진입", win.is_fullscreen())
                icon_fs = win._fs_button.get_icon_name()
                check("전체화면 진입 직후엔 UI 가 보인다", win.chrome_visible)
                check("크기 변경 뒤 다시 그린다(검은 화면 방지)",
                      state["renders"] > renders_before,
                      f"렌더 {renders_before} -> {state['renders']}")
                win._hide_ui()          # 타이머가 할 일을 당겨서 실행
                check("전체화면에서 헤더바·컨트롤이 감춰진다", not win.chrome_visible,
                      f"reveal={win.chrome_visible}")
                check("접히는 전환이 붙어 있다(툭 사라지지 않는다)",
                      win._header_revealer.get_transition_duration() > 0
                      and win._header_revealer.get_transition_type() == Gtk.RevealerTransitionType.SLIDE_DOWN,
                      f"{win._header_revealer.get_transition_duration()}ms")
                win._on_motion(None, 0, 0)
                check("마우스를 움직이면 다시 보인다", win.chrome_visible)

                # 창 관리자가 직접 되돌리는 경우 — set_fullscreen 을 거치지 않는다
                win.unfullscreen()
                wait_until(lambda: not win.is_fullscreen(), 3.0)
                icon_normal = win._fs_button.get_icon_name()
                check("전체화면 버튼 아이콘 전환", icon_fs != icon_normal, f"{icon_fs} / {icon_normal}")
                check("창 관리자로 나와도 UI 가 돌아온다", win.chrome_visible,
                      f"reveal={win.chrome_visible}")

                # 자막 싱크 단축키
                win._nudge_sub_delay(0.3)
                check("자막 싱크 단축키", abs(p.sub_delay - 0.3) < 0.01, f"delay={p.sub_delay}")

                # 키 핸들러가 키를 실제로 소비하는가
                consumed = win._on_key(None, Gdk.KEY_space, 0, Gdk.ModifierType(0))
                win._on_key(None, Gdk.KEY_space, 0, Gdk.ModifierType(0))   # 원래대로
                check("스페이스 키 처리", consumed is True)
                passthrough = win._on_key(None, Gdk.KEY_z, 0, Gdk.ModifierType(0))
                check("모르는 키는 넘긴다", passthrough is False)

                # 우클릭 메뉴
                has_right = any(
                    isinstance(c, Gtk.GestureClick) and c.get_button() == Gdk.BUTTON_SECONDARY
                    for c in win._video.observe_controllers())
                check("우클릭 제스처가 영상 위젯에 연결", has_right)
                check("팝오버 부모도 같은 위젯(좌표계 일치)",
                      win._menu_popover.get_parent() is win._video,
                      str(type(win._menu_popover.get_parent()).__name__))
                win._on_right_click(None, 1, 321, 234)
                check("우클릭 메뉴가 열린다", win._menu_popover.get_visible())
                rect = win._menu_popover.get_pointing_to()[1]
                check("클릭한 자리를 가리킨다(좌상단이 아니다)",
                      rect.x == 321 and rect.y == 234, f"pointing_to=({rect.x},{rect.y})")
                menu = win._menu_popover.get_child()
                labels = []
                row = menu.get_first_child()
                while row is not None:
                    if isinstance(row, Gtk.Button):
                        inner = row.get_child().get_first_child()
                        labels.append(inner.get_label())
                    row = row.get_next_sibling()
                check("메뉴 항목이 채워진다", len(labels) >= 8, f"{len(labels)}개: {labels[:4]}")
                win._menu_popover.popdown()

                # 툴팁에 단축키가 적혀 있다
                tips = [win._play_btn.get_tooltip_text(), win._stop_btn.get_tooltip_text(),
                        win._fs_button.get_tooltip_text(), win._sub_button.get_tooltip_text()]
                check("버튼 툴팁에 단축키 표기", all(t and any(k in t for k in "()[]") for t in tips),
                      " / ".join(str(t) for t in tips))

                # 드롭 — 자막만 떨구면 현재 영상에 붙는다
                ok = win.open_dropped([sub])
                check("자막만 드롭 -> 현재 영상에 적용", ok and win._plan is not None,
                      win._plan.summary() if win._plan else "(없음)")

                # 드롭 — 영상+자막 함께
                ok2 = win.open_dropped([video, sub])
                check("영상+자막 함께 드롭", ok2 and win._plan is not None,
                      win._plan.summary() if win._plan else "(없음)")

                p.close()
                self.quit()
                return False

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 03 — UI 동작 ===")
    failed = 0
    for name, ok, detail in results:
        mark = "통과" if ok else "실패"
        print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))
        failed += (not ok)
    if not results:
        print("  결과가 없다 — 창이 뜨지 않았다")
        return 1
    print(f"\n{'전부 통과' if not failed else f'{failed}건 실패'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
