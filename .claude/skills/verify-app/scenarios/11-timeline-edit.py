#!/usr/bin/env python3
"""시나리오 11 — 하단 타임라인 컷 편집 (기획서 v0.5 §5)

  python3 .claude/skills/verify-app/scenarios/11-timeline-edit.py

T1 타임라인을 열면 즉시 뜨고 썸네일이 뒤이어 채워진다
T2 재생헤드 자리에서 자르면 구간이 둘로 쪼개진다
T3 구간 끝을 끌면 경계가 바뀐다 (이웃이 따라 준다)
T4 삭제한 구간이 결과에서 빠지고, 되살리면 돌아온다
T5 Ctrl+Z 로 자르기·삭제가 되돌아간다
T6 미리보기가 잘린 자리를 건너뛴다
T7 내보내기가 남은 구간만 넘긴다
T8 접혀 있을 때는 S 가 정지, 펴져 있을 때는 자르기
T9 재생헤드가 프레임 클록을 타고 매끄럽게 따라간다 (접으면 멈춘다)
T10 필름스트립 본체를 클릭하면 선택만 되고 재생은 끊기지 않는다
T11 눈금 띠를 클릭하면 재생헤드가 그리로 간다
T12 지운 구간을 지날 때 화면이 검게 덮인다
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

from bora.app import BoraApplication  # noqa: E402

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


def wait_until(cond, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(0.05)
        if cond():
            return True
    return bool(cond())


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-tl-"))
    try:
        video = folder / "lecture.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=320x240:rate=30:duration=120", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-g", "30", str(video)],
            check=True,
        )

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
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
                wait_until(lambda: (win.player.duration or 0) > 0, 8.0)

                # T8 앞부분 — 접혀 있을 때 S 는 정지
                check("T8 접힌 상태에서는 편집 키가 없다", not win.editing)

                # T1 — 열기
                t0 = time.monotonic()
                win.toggle_edit()
                pump(0.2)
                opened = time.monotonic() - t0
                tl = win._timeline
                check("T1 타임라인이 즉시 열린다",
                      win.editing and tl.model is not None and opened < 1.0,
                      f"{opened:.2f}초, 구간 {len(tl.model) if tl.model else 0}개")
                got = wait_until(lambda: bool(tl.thumbs and tl.thumbs._cache), 25.0)
                check("T1 썸네일이 뒤이어 채워진다", got,
                      f"{len(tl.thumbs._cache) if tl.thumbs else 0}장")

                # T2 — 자르기
                win.player.seek_absolute(40)
                wait_until(lambda: (win.player.time_pos or 0) > 39, 6.0)
                tl.set_position(win.player.time_pos or 40)
                before = len(tl.model)
                win.split_clip()
                check("T2 재생헤드에서 쪼개진다", len(tl.model) == before + 1,
                      f"{before} -> {len(tl.model)}개")

                # T3 — 경계 끌기 (이웃이 따라 준다)
                tl.model.trim(1, start=30)
                check("T3 경계를 옮기면 이웃이 따라 준다",
                      abs(tl.model[0].end - 30) < 0.01 and abs(tl.model[1].start - 30) < 0.01,
                      f"{tl.model[0].end:.1f} / {tl.model[1].start:.1f}")

                # T4 — 삭제·되살리기
                full = tl.model.output_duration()
                tl.selected = 0
                win.delete_clip()
                cut = tl.model.output_duration()
                win.delete_clip()
                back = tl.model.output_duration()
                check("T4 지우면 빠지고 되살리면 돌아온다",
                      cut < full and abs(back - full) < 0.01,
                      f"{full:.0f} -> {cut:.0f} -> {back:.0f}초")

                # T5 — 되돌리기
                tl.selected = 0
                win.delete_clip()
                steps = 0
                while tl.model.can_undo and steps < 20:
                    win.undo_edit()
                    steps += 1
                check("T5 Ctrl+Z 로 처음 상태까지 되돌아간다",
                      len(tl.model) == 1 and abs(tl.model.output_duration()
                                                 - (win.player.duration or 0)) < 1.0,
                      f"{len(tl.model)}개, {tl.model.output_duration():.0f}초")

                # T6 — 미리보기가 잘린 자리를 건너뛴다
                tl.model.split(40)
                tl.model.split(70)
                tl.model.toggle(1)                  # 40~70 을 들어낸다
                check("T6 잘린 자리에서 다음 구간으로 건너뛴다",
                      tl.model.next_enabled_start(50) == 70
                      and tl.model.next_enabled_start(10) is None,
                      f"50초→{tl.model.next_enabled_start(50)}")

                # T7 — 내보내기가 남은 것만 넘긴다
                win.export_timeline()
                pump(0.2)
                kept = [(round(c.start), round(c.end)) for c in win._clips]
                check("T7 남은 구간만 클립으로 넘어간다",
                      len(kept) == len(tl.model.enabled_clips()) and (40, 70) not in kept,
                      str(kept))
                if win._clip_window is not None:
                    win._clip_window.close()
                    pump(0.1)

                # T8 — 펴져 있을 때 S 는 자르기(정지가 아니다)
                win.player.seek_absolute(90)
                wait_until(lambda: (win.player.time_pos or 0) > 89, 6.0)
                tl.set_position(win.player.time_pos or 90)
                n = len(tl.model)
                eaten = win._on_key(None, Gdk.KEY_s, 0, none)
                check("T8 펴진 상태에서 S 는 자르기",
                      eaten and len(tl.model) == n + 1,
                      f"가로챔={eaten}, {n} -> {len(tl.model)}개")

                # T9 — 재생헤드가 프레임마다 따라오나
                check("T9 재생헤드가 재생 위치를 따라간다", tl._tick_id != 0,
                      "follow 안 걸림" if not tl._tick_id else "")
                win.player.paused = False
                seen = []
                for _ in range(8):
                    pump(0.25)
                    seen.append(round(tl.position, 2))
                moved = len(set(seen))
                check("T9 재생헤드가 매끄럽게 움직인다", moved >= 6,
                      f"2초 동안 서로 다른 값 {moved}/8")
                win.player.paused = True

                # T10~T12 — 선택/재생헤드 분리와 블랙아웃
                # 앞선 검사들이 이미 여기를 지워 뒀을 수 있다. toggle 은 되살려 버리므로
                # (실제로 그래서 한 번 헛짚었다) 상태를 명시적으로 만든다.
                tl.model.split(40)
                tl.model.split(70)
                index = tl.model.index_at(50)
                tl.model.set_enabled(index, False)
                tl.selected = index
                tl._changed()
                pump(0.2)
                check("T12 준비 — 50초 구간이 꺼져 있다",
                      not tl.model[tl.model.index_at(50)].enabled,
                      str([(round(c.start), round(c.end), c.enabled) for c in tl.model]))

                win.player.seek_absolute(50)
                wait_until(lambda: abs((win.player.time_pos or 0) - 50) < 3, 6.0)
                pump(0.4)
                check("T12 지운 구간에서 화면이 검게 덮인다",
                      win._blackout.get_visible(),
                      f"위치 {win.player.time_pos:.1f}")
                win.player.seek_absolute(85)
                wait_until(lambda: (win.player.time_pos or 0) > 80, 6.0)
                pump(0.4)
                check("T12 살아 있는 구간에서는 덮개가 걷힌다",
                      not win._blackout.get_visible(),
                      f"위치 {win.player.time_pos:.1f}")

                width = tl.get_width() or 400
                win.player.paused = False
                pump(0.5)
                before = win.player.time_pos or 0.0
                selected_before = tl.selected
                tl._on_pressed(None, 1, width * 0.2, 40)      # 본체(필름스트립) 클릭
                pump(0.7)
                after = win.player.time_pos or 0.0
                check("T10 본체 클릭은 선택만 — 재생이 끊기지 않는다",
                      after > before and tl.selected != -1,
                      f"{before:.1f} → {after:.1f}, 선택 {selected_before}→{tl.selected}")
                win.player.paused = True
                pump(0.3)

                tl._on_pressed(None, 1, width * 0.5, 5)       # 눈금 띠 클릭
                pump(0.5)
                want = tl._time_of(width * 0.5)
                check("T11 눈금 클릭은 재생헤드를 옮긴다",
                      abs((win.player.time_pos or -99) - want) < 4.0,
                      f"목표 {want:.1f} · 실제 {win.player.time_pos:.1f}")

                # 닫을 때 편집 중이면 묻는다
                win.toggle_edit()
                asked = win.editing
                win.toggle_edit()
                check("편집 중 접으면 한 번 확인한다",
                      asked and not win.editing,
                      "첫 시도에 접히지 않음" if asked else "바로 접혔다")
                check("T9 접으면 재생헤드 추적이 멈춘다", tl._tick_id == 0)

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 11 — 하단 타임라인 컷 편집 ===")
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
