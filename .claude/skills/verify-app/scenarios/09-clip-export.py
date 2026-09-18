#!/usr/bin/env python3
"""시나리오 09 — 클립 자르기·이어붙이기 (기획서 v0.4 §4)

  python3 .claude/skills/verify-app/scenarios/09-clip-export.py

C1 구간을 잡고 K 를 누르면 그 구간이 담긴다
C2 구간 없이 누르면 현재 위치부터 30초가 담긴다
C3 빠른 모드로 합치면 **재생 가능한** 파일이 나온다
C4 정확 모드의 길이가 요청과 0.2초 이내로 맞는다
C5 취소하면 부분 파일도 임시 파일도 남지 않는다
C6 코덱이 다르면 이어붙이기를 막는다
"""
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from bora.app import BoraApplication  # noqa: E402
from bora.clip.model import Clip  # noqa: E402
from bora.clip.probe import StreamInfo, can_stream_copy, probe  # noqa: E402
from bora.clip.runner import ExportJob, ExportRunner  # noqa: E402

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


def export(job: ExportJob, timeout: float = 120.0) -> tuple[object, str]:
    """내보내기를 돌리고 (결과, 오류) 를 돌려준다."""
    done = threading.Event()
    box: dict = {}
    runner = ExportRunner(
        on_done=lambda r: (box.__setitem__("res", r), done.set()),
        on_error=lambda m: (box.__setitem__("err", m), done.set()),
    )
    runner.start(job)
    done.wait(timeout)
    return box.get("res"), box.get("err", "")


def decodes(path: Path) -> bool:
    """실제로 디코딩되는지 — 실측 E 의 깨진 파일은 여기서 걸린다."""
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True)
    return done.returncode == 0 and not done.stderr.strip()


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-clip-"))
    try:
        video = folder / "lecture.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "testsrc2=size=640x480:rate=30:duration=240", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=240", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-g", "30",
             "-c:a", "aac", "-shortest", str(video)],
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
                    check("시나리오가 끝까지 돌았다", False, f"{exc.__class__.__name__}: {exc}")
                    traceback.print_exc()
                finally:
                    win.player.close()
                    self.quit()
                return False

            def _checks(self, win):
                p = win.player

                # C1 — 구간을 잡고 담는다
                p.seek_absolute(20)
                wait_until(lambda: (p.time_pos or 0) > 19, 5.0)
                win._set_loop_edge("a")
                p.seek_absolute(40)
                wait_until(lambda: (p.time_pos or 0) > 39, 5.0)
                win._set_loop_edge("b")
                win.add_clip()
                got = win._clips[0] if len(win._clips) else None
                check("C1 잡은 구간이 담긴다",
                      got is not None and abs(got.duration - 20) < 1.5,
                      got.label() if got else "담기지 않았다")

                # C2 — 구간 없이 담으면 30초
                p.clear_loop()
                p.seek_absolute(60)
                wait_until(lambda: (p.time_pos or 0) > 59, 5.0)
                win.add_clip()
                got = win._clips[1] if len(win._clips) > 1 else None
                check("C2 구간 없이 담으면 30초",
                      got is not None and abs(got.duration - 30) < 1.5,
                      got.label() if got else "담기지 않았다")

                # 오디오 트랙 순번이 ffmpeg 기준으로 나오나
                check("오디오 트랙 순번은 0-기반",
                      win.current_audio_index() in (0, None),
                      str(win.current_audio_index()))

                # C6 — 코덱이 다르면 막는다
                mixed = can_stream_copy([
                    StreamInfo("h264", 320, 240, "aac", 44100, 1),
                    StreamInfo("hevc", 320, 240, "aac", 44100, 1)])
                check("C6 코덱이 다르면 이어붙이기를 막는다", bool(mixed), mixed or "막지 않았다")

        Probe(non_unique=True).run([sys.argv[0], str(video)])

        # ── 내보내기는 창 없이 확인한다 (ffmpeg 만 쓰므로) ──────────────
        clips = [Clip(10, 25), Clip(60, 80)]

        # C3 — 빠른 모드 합치기
        out = folder / "fast.mp4"
        res, err = export(ExportJob(video, clips, out, mode="copy", join=True))
        ok = res is not None and out.exists() and decodes(out)
        check("C3 빠른 모드로 합친 결과가 재생된다", ok,
              err or (f"{probe(out).duration:.2f}초" if out.exists() else "파일 없음"))

        # C4 — 정확 모드 길이
        out2 = folder / "exact.mp4"
        res, err = export(ExportJob(video, [Clip(30, 45)], out2, mode="encode"))
        length = probe(out2).duration if out2.exists() else 0.0
        check("C4 정확 모드 길이가 0.2초 이내로 맞는다", abs(length - 15.0) <= 0.2,
              err or f"{length:.3f}초 (요청 15.0)")

        # C5 — 취소
        out3 = folder / "cancelled.mp4"
        done = threading.Event()
        box: dict = {}
        runner = ExportRunner(on_done=lambda r: done.set(),
                              on_error=lambda m: (box.__setitem__("err", m), done.set()))
        runner.start(ExportJob(video, [Clip(0, 240)], out3, mode="encode"))
        time.sleep(1.2)            # 전체 재인코딩은 약 4.7초 — 확실히 중간이다
        runner.cancel()
        done.wait(30)
        time.sleep(0.5)
        leftovers = list(folder.glob(".bora-clip*"))
        check("C5 취소하면 부분 파일이 남지 않는다",
              box.get("err") == "취소됨" and not out3.exists() and not leftovers,
              f"알림={box.get('err')!r}, 결과={out3.exists()}, "
              f"임시={[p.name for p in leftovers]}")

        # 조각별 저장
        out4 = folder / "parts.mp4"
        res, err = export(ExportJob(video, clips, out4, mode="copy", join=False))
        names = sorted(p.name for p in folder.glob("parts-*.mp4"))
        check("조각별 저장은 번호를 붙인다", names == ["parts-1.mp4", "parts-2.mp4"],
              err or str(names))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 09 — 클립 자르기·이어붙이기 ===")
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
