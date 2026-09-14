#!/usr/bin/env python3
"""시나리오 06 — 학습 메모 패널 (기획서 v0.3 §6 N1~N5)

  python3 .claude/skills/verify-app/scenarios/06-notes-panel.py

N1 Ctrl+T 로 현재 시각이 제목으로 들어가고 재생은 계속된다
N2 입력이 멈추면 영상 옆 .md 로 저장된다
N3 본문의 [HH:MM:SS] 를 누르면 그 시점으로 이동한다
N4 다시 열면 메모가 그대로 있다
N5 저장된 파일이 평문 마크다운이다
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


def make_video(folder: Path) -> Path:
    video = folder / "lecture.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=120", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "ultrafast", str(video)],
        check=True,
    )
    return video


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-notes-"))
    note_path = folder / "lecture.md"
    try:
        video = make_video(folder)

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
                GLib.timeout_add_seconds(3, self._run, self.win)

            def _run(self, win):
                p = win.player
                panel = win._notes

                # 패널 열기
                win.toggle_notes(True)
                check("메모 패널이 열린다", win._notes_open and panel.get_visible())
                check("영상 옆 .md 를 연다",
                      panel.doc is not None and panel.doc.path == note_path,
                      str(panel.doc.path if panel.doc else None))
                check("새 메모는 제목으로 시작한다",
                      panel.doc.text.startswith("# lecture"), panel.doc.text[:20])

                # N1 — 타임스탬프 삽입. 재생은 계속되어야 한다
                p.seek_absolute(45)
                wait_until(lambda: (p.time_pos or 0) > 43, 5.0)
                paused_before = p.paused
                panel.insert_stamp()
                body = panel._text()
                stamps = parse_stamps(body)
                check("N1 타임스탬프가 들어간다", bool(stamps),
                      repr(body.splitlines()[-1] if body else ""))
                check("N1 현재 시각과 맞는다",
                      bool(stamps) and abs(stamps[-1].seconds - (p.time_pos or 0)) < 2,
                      f"{stamps[-1].seconds if stamps else '-'} vs {p.time_pos:.1f}")
                check("N1 재생 상태는 그대로", p.paused == paused_before)

                # 이어서 본문 입력
                panel._buffer.insert(panel._buffer.get_end_iter(), "합의 알고리즘 정리\n")

                # N2 — 자동 저장
                check("N2 자동 저장이 예약된다", panel._save_id != 0)
                wait_until(lambda: note_path.exists() and "합의" in
                           note_path.read_text(encoding="utf-8"), 6.0)
                check("N2 파일로 저장된다", note_path.exists(), str(note_path))
                saved = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
                check("N2 내용이 들어 있다", "합의 알고리즘 정리" in saved)

                # N5 — 평문 마크다운
                check("N5 평문 마크다운이다",
                      saved.startswith("# lecture") and "## [" in saved,
                      repr(saved[:40]))

                # N3 — 타임스탬프로 이동
                p.seek_absolute(5)
                wait_until(lambda: (p.time_pos or 99) < 8, 5.0)
                stamp = parse_stamps(panel._text())[-1]
                p.seek_absolute(stamp.seconds)
                wait_until(lambda: abs((p.time_pos or 0) - stamp.seconds) < 2, 5.0)
                check("N3 타임스탬프 시점으로 이동",
                      abs((p.time_pos or 0) - stamp.seconds) < 2,
                      f"{p.time_pos:.1f} vs {stamp.seconds}")

                # 태그가 입혀졌는가(클릭 영역)
                tag_table = panel._buffer.get_tag_table()
                check("타임스탬프에 태그가 붙는다", tag_table.lookup("stamp") is not None)

                # N4 — 닫았다 다시 열기
                win.toggle_notes(False)
                check("패널을 닫으면 저장된다", panel.doc.dirty is False)
                win.toggle_notes(True)
                check("N4 다시 열면 내용이 남아 있다",
                      "합의 알고리즘 정리" in panel._text())

                p.close()
                self.quit()
                return False

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 06 — 학습 메모 ===")
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
