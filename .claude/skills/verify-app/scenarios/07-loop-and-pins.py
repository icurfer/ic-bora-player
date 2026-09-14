#!/usr/bin/env python3
"""시나리오 07 — 구간 반복(A-B)과 핀

  python3 .claude/skills/verify-app/scenarios/07-loop-and-pins.py

L1 버튼을 누르면 A -> B -> 해제로 순환한다
L2 구간을 잡으면 실제로 그 안에서 맴돈다
L3 끝점이 시작점보다 앞이면 거부한다
L4 F5/F6 로도 구간을 잡을 수 있다(곰·KMP 관례)
P1 시점 핀을 꽂고 그 자리로 돌아간다
P2 구간이 잡혀 있으면 구간 핀이 된다
P3 핀은 저장되고 다시 열어도 남아 있다
P4 핀을 지운다
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
from gi.repository import GLib  # noqa: E402

from bora.app import BoraApplication  # noqa: E402
from bora.notes.model import parse_stamps  # noqa: E402
from bora.state import State  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def wait_until(cond, timeout: float) -> bool:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.05)
    return bool(cond())


def pump(seconds: float) -> None:
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.05)


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-loop-"))
    cfg = folder / "cfg"
    try:
        video = folder / "lecture.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=320x240:rate=30:duration=90", "-c:v", "libx264",
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
                p = win.player

                # L1 — 순환
                p.seek_absolute(20)
                wait_until(lambda: (p.time_pos or 0) > 19, 5.0)
                win.cycle_loop()
                check("L1 첫 번째 누름 = 시작점", p.loop_a is not None and p.loop_b is None,
                      f"a={p.loop_a}")
                p.seek_absolute(26)
                wait_until(lambda: (p.time_pos or 0) > 25, 5.0)
                win.cycle_loop()
                check("L1 두 번째 누름 = 끝점", p.looping,
                      f"{p.loop_a:.1f} ~ {p.loop_b:.1f}" if p.looping else "안 걸림")

                # L2 — 실제로 그 안에서 맴도나
                a, b = p.loop_a, p.loop_b
                p.seek_absolute(b - 0.5)
                pump(4.0)
                inside = a - 1.0 <= (p.time_pos or -1) <= b + 1.0
                check("L2 구간 안에서 맴돈다", inside,
                      f"{p.time_pos:.1f} in [{a:.1f}, {b:.1f}]")

                win.cycle_loop()
                check("L1 세 번째 누름 = 해제", not p.looping and p.loop_a is None)

                # L3 — 거꾸로 된 구간 거부
                p.seek_absolute(40)
                wait_until(lambda: (p.time_pos or 0) > 39, 5.0)
                win.cycle_loop()                    # A = 40
                p.seek_absolute(10)
                wait_until(lambda: (p.time_pos or 99) < 12, 5.0)
                win.cycle_loop()                    # B = 10 -> 거부되어야 한다
                check("L3 거꾸로 된 구간을 거부한다", not p.looping,
                      f"a={p.loop_a}, b={p.loop_b}")
                p.clear_loop()

                # L4 — F5/F6
                p.seek_absolute(15)
                wait_until(lambda: (p.time_pos or 0) > 14, 5.0)
                win._set_loop_edge("a")
                p.seek_absolute(19)
                wait_until(lambda: (p.time_pos or 0) > 18, 5.0)
                win._set_loop_edge("b")
                check("L4 F5/F6 로도 구간이 잡힌다", p.looping,
                      f"{p.loop_a:.1f} ~ {p.loop_b:.1f}" if p.looping else "안 걸림")

                # P2 — 구간이 잡혀 있으면 구간 핀
                pin = win.add_pin("어려운 대목")
                check("P2 구간 핀이 된다", pin is not None and pin.is_range,
                      f"{pin.start:.1f}~{pin.end:.1f}" if pin else "없음")
                p.clear_loop()

                # P1 — 시점 핀
                p.seek_absolute(55)
                wait_until(lambda: (p.time_pos or 0) > 54, 5.0)
                pin2 = win.add_pin()
                check("P1 시점 핀이 된다", pin2 is not None and not pin2.is_range,
                      f"{pin2.start:.1f}" if pin2 else "없음")

                # 핀으로 이동
                p.seek_absolute(5)
                wait_until(lambda: (p.time_pos or 99) < 8, 5.0)
                win.goto_pin(pin2)
                wait_until(lambda: abs((p.time_pos or 0) - pin2.start) < 2, 5.0)
                check("P1 핀 자리로 이동", abs((p.time_pos or 0) - pin2.start) < 2,
                      f"{p.time_pos:.1f} vs {pin2.start:.1f}")

                # 구간 핀을 고르면 반복이 걸린다
                win.goto_pin(pin)
                check("P2 구간 핀을 고르면 반복이 걸린다", p.looping,
                      f"{p.loop_a:.1f} ~ {p.loop_b:.1f}" if p.looping else "안 걸림")
                p.clear_loop()

                # P3 — 저장
                stored = win.state.pins_for(video)
                check("P3 핀이 저장된다", len(stored) == 2, f"{len(stored)}개")
                reloaded = State(cfg).pins_for(video)
                check("P3 다시 읽어도 남아 있다", len(reloaded) == 2,
                      f"{[('%.0f' % p.start) for p in reloaded]}")
                check("P3 라벨도 남는다",
                      any(p.label == "어려운 대목" for p in reloaded))

                # 재생 위치 기록이 핀을 지우지 않는가
                win._remember_position()
                check("P3 위치 기록이 핀을 지우지 않는다",
                      len(win.state.pins_for(video)) == 2,
                      f"{len(win.state.pins_for(video))}개")

                # P5 — 핀이 메모에도 남는가 (학습 보조의 핵심)
                note_path = video.with_suffix(".md")
                check("P5 메모 파일이 생긴다", note_path.exists(), str(note_path))
                body = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
                check("P5 구간 핀이 구간 표기로 들어간다",
                      "~" in body and "어려운 대목" in body,
                      repr([l for l in body.splitlines() if "~" in l][:1]))
                check("P5 시점 핀도 들어간다",
                      body.count("## [") >= 2, f"제목 {body.count('## [')}개")

                # 그 표기를 다시 읽으면 구간으로 인식되는가
                stamps = [t for t in parse_stamps(body) if t.is_range]
                check("P5 메모의 구간 표기를 구간으로 읽는다", bool(stamps),
                      f"{stamps[0].seconds:.0f}~{stamps[0].range_end:.0f}" if stamps else "없음")

                # 메모의 구간을 눌렀을 때처럼 반복이 걸리는가
                if stamps:
                    p.clear_loop()
                    panel = win._notes
                    panel.window.player.set_loop(stamps[0].seconds, stamps[0].range_end)
                    check("P5 메모에서 구간 반복이 걸린다", p.looping,
                          f"{p.loop_a:.0f} ~ {p.loop_b:.0f}" if p.looping else "안 걸림")
                    p.clear_loop()

                # P4 — 삭제
                win.state.remove_pin(video, 0)
                check("P4 핀을 지운다", len(win.state.pins_for(video)) == 1)

                p.close()
                self.quit()
                return False

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 07 — 구간 반복과 핀 ===")
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
