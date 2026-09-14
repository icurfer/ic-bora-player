#!/usr/bin/env python3
"""시나리오 08 — 텍스트 추출과 핀 제목 입력

  python3 .claude/skills/verify-app/scenarios/08-stt-and-pin-title.py

T1 자막 없는 영상을 열면 추출을 제안한다
T2 설치 상태를 정확히 알린다(미설치여도 앱은 멀쩡하다)
T3 추출 메뉴가 모델·언어 선택을 보여 준다
P6 핀을 꽂으면 메모가 열리고 그 줄 끝에 커서가 온다 — 바로 제목을 칠 수 있다
P7 이어서 친 글자가 그대로 제목이 된다
P8 Shift+P 는 메모를 열지 않고 조용히 꽂는다
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
from bora.state import State  # noqa: E402
from bora.stt import ensure_ready  # noqa: E402

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


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-stt-"))
    cfg = folder / "cfg"
    try:
        video = folder / "lecture.mp4"       # 자막을 일부러 두지 않는다
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "color=c=black:s=320x240:d=60", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "ultrafast", str(video)],
            check=True,
        )

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
                self.win.state = State(cfg)
                GLib.timeout_add_seconds(4, self._run, self.win)

            def _run(self, win):
                p = win.player

                # T1 — 자막이 없다는 것을 알아채고 제안했나
                check("T1 자막 없음을 안다", win._plan is None)
                win._offer_extract()
                check("T1 추출을 제안한다",
                      "자막이 없다" in (win._last_toast_title or ""),
                      win._last_toast_title or "(없음)")

                # T2 — 설치 상태
                ready, hint = ensure_ready()
                check("T2 설치 상태를 판단한다", isinstance(ready, bool),
                      "준비됨" if ready else hint.splitlines()[0])
                check("T2 미설치여도 재생은 정상", (p.duration or 0) > 0,
                      f"duration={p.duration}")

                # T3 — 메뉴
                win._rebuild_extract_menu()
                child = win._stt_popover.get_child()
                check("T3 추출 메뉴가 그려진다", child is not None)
                if ready:
                    check("T3 모델을 고를 수 있다", hasattr(win, "_stt_model"))
                    check("T3 언어를 고를 수 있다", hasattr(win, "_stt_lang"))

                # P6 — 핀 꽂고 제목 입력
                p.seek_absolute(20)
                wait_until(lambda: (p.time_pos or 0) > 19, 5.0)
                pin = win.add_pin()
                check("P6 핀이 꽂힌다", pin is not None)
                check("P6 메모가 열린다", win._notes_open)
                buffer = win._notes._buffer
                cursor = buffer.get_iter_at_mark(buffer.get_insert())
                check("P6 커서가 문서 끝에 온다",
                      cursor.get_offset() == buffer.get_end_iter().get_offset(),
                      f"{cursor.get_offset()} / {buffer.get_end_iter().get_offset()}")

                # P7 — 이어서 치면 제목이 된다
                buffer.insert(buffer.get_end_iter(), "합의 알고리즘이 어렵다")
                win._notes.save()
                body = win._notes.doc.path.read_text(encoding="utf-8")
                check("P7 친 글자가 그 줄의 제목이 된다",
                      "합의 알고리즘이 어렵다" in body
                      and any("합의 알고리즘이 어렵다" in l and l.startswith("## [")
                              for l in body.splitlines()),
                      repr([l for l in body.splitlines() if "합의" in l][:1]))

                # P8 — 조용히 꽂기
                lines_before = len(body.splitlines())
                win.toggle_notes(False)
                p.seek_absolute(40)
                wait_until(lambda: (p.time_pos or 0) > 39, 5.0)
                win.add_pin(write_title=False)
                check("P8 메모를 열지 않는다", not win._notes_open)
                after = win._notes.doc.path.read_text(encoding="utf-8")
                check("P8 그래도 메모에는 남는다",
                      len(after.splitlines()) > lines_before,
                      f"{lines_before} -> {len(after.splitlines())}줄")

                p.close()
                self.quit()
                return False

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 08 — 텍스트 추출 · 핀 제목 ===")
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
