#!/usr/bin/env python3
"""시나리오 05 — 자막 에디터 수용 테스트 (기획서 v0.2 §5 의 E1~E4)

  python3 .claude/skills/verify-app/scenarios/05-subtitle-editor.py

E1 재생 중 일시정지한 시각을 그 큐의 시작으로 박는다
E2 이 줄부터 뒤로 전부 밀기 — 앞 줄은 그대로여야 한다
E3 저장하면 .bak 이 생기고 원본 내용이 거기 남는다. 저장본이 화면에 다시 물린다
E4 SAMI 를 편집해 저장하면 .srt 로 나가고 원본 .smi 는 그대로다
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures"

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from bora.app import BoraApplication  # noqa: E402
from bora.subtitle.model import ms_to_srt  # noqa: E402

results: list[tuple[str, bool, str]] = []

SRT = """1
00:00:02,000 --> 00:00:06,000
첫 줄

2
00:00:08,000 --> 00:00:12,000
둘째 줄

3
00:00:14,000 --> 00:00:18,000
셋째 줄
"""


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


def make_media(folder: Path, sami: bool = False) -> Path:
    video = folder / "movie.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "ultrafast", str(video)],
        check=True,
    )
    if sami:
        if not (FIXTURES / "sample_cp949.smi").exists():
            subprocess.run([sys.executable, str(FIXTURES / "make_fixtures.py")], check=True)
        shutil.copy(FIXTURES / "sample_cp949.smi", folder / "movie.smi")
    else:
        (folder / "movie.srt").write_text(SRT, encoding="utf-8")
    return video


def run_srt_case(folder: Path) -> None:
    video = make_media(folder)
    original = (folder / "movie.srt").read_text(encoding="utf-8")

    class Probe(BoraApplication):
        def do_activate(self):
            super().do_activate()
            self.win = self.props.active_window
            GLib.timeout_add_seconds(3, self._run, self.win)

        def _run(self, win):
            p = win.player
            p.seek_absolute(9.0)
            wait_until(lambda: (p.time_pos or 0) > 8.5, 5.0)

            editor = win.open_editor()
            check("에디터가 열린다", editor is not None)
            if editor is None:
                p.close(); self.quit(); return False
            check("열면서 일시정지된다", p.paused, f"paused={p.paused}")

            # E1 — 지금 위치(9초 근처)의 큐는 2번(8~12초)
            check("재생 위치의 큐를 잡는다", editor.index == 1, f"index={editor.index}")
            before = editor.doc.cues[1].start_ms
            editor.stamp("start")
            after = editor.doc.cues[1].start_ms
            check("E1 시작을 현재 위치로 박는다",
                  after != before and abs(after - int((p.time_pos or 0) * 1000)) < 500,
                  f"{ms_to_srt(before)} -> {ms_to_srt(after)}")

            # E2 — 이 줄부터 뒤로 밀기. 1번은 그대로여야 한다
            first_before = editor.doc.cues[0].start_ms
            third_before = editor.doc.cues[2].start_ms
            editor._shift_spin.set_value(-1.5)
            editor.shift(from_current=True)
            check("E2 앞 줄은 그대로", editor.doc.cues[0].start_ms == first_before)
            check("E2 뒤 줄이 밀린다",
                  editor.doc.cues[2].start_ms == third_before - 1500,
                  f"{ms_to_srt(third_before)} -> {ms_to_srt(editor.doc.cues[2].start_ms)}")

            # 되돌리기
            editor.undo()
            check("되돌리기", editor.doc.cues[2].start_ms == third_before)

            # 잘못된 시각 입력은 거부
            editor._start_entry.set_text("아무말")
            editor._commit_time("start")
            check("잘못된 시각 입력을 거부한다",
                  editor._start_entry.get_text() != "아무말", editor._start_entry.get_text())

            # E3 — 저장
            editor.save()
            backups = list(folder.glob("movie.srt.bak*"))
            check("E3 백업이 생긴다", len(backups) == 1, f"{[b.name for b in backups]}")
            check("E3 원본 내용이 백업에 그대로",
                  bool(backups) and backups[0].read_text(encoding="utf-8") == original)
            saved = (folder / "movie.srt").read_text(encoding="utf-8")
            check("E3 저장본이 바뀌었다", saved != original and "첫 줄" in saved)
            check("저장 후 dirty 해제", editor.doc.dirty is False)
            wait_until(lambda: abs(p.sub_delay) < 0.001, 2.0)
            check("저장 후 sub-delay 가 0", abs(p.sub_delay) < 0.001, f"{p.sub_delay}")

            p.close()
            self.quit()
            return False

    Probe(non_unique=True).run([sys.argv[0], str(video)])


def run_sami_case(folder: Path) -> None:
    video = make_media(folder, sami=True)
    smi = folder / "movie.smi"
    original_bytes = smi.read_bytes()

    class Probe(BoraApplication):
        def do_activate(self):
            super().do_activate()
            self.win = self.props.active_window
            GLib.timeout_add_seconds(3, self._run, self.win)

        def _run(self, win):
            editor = win.open_editor()
            check("E4 SAMI 로도 에디터가 열린다", editor is not None)
            if editor is None:
                win.player.close(); self.quit(); return False
            editor._shift_spin.set_value(0.5)
            editor.shift(from_current=False)
            editor.save()

            srt = list(folder.glob("*.srt"))
            check("E4 SRT 로 저장된다", bool(srt), f"{[s.name for s in srt]}")
            check("E4 원본 .smi 가 그대로", smi.read_bytes() == original_bytes)
            win.player.close()
            self.quit()
            return False

    Probe(non_unique=True).run([sys.argv[0], str(video)])


def main() -> int:
    for runner in (run_srt_case, run_sami_case):
        folder = Path(tempfile.mkdtemp(prefix="bora-editor-"))
        try:
            runner(folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 05 — 자막 에디터 ===")
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
