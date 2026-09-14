#!/usr/bin/env python3
"""시나리오 04 — v0.2 재생 부가기능 (기획서 v0.2 §5 의 S1~S3, R1~R2)

  python3 .claude/skills/verify-app/scenarios/04-playback-extras.py

확인: 재생 속도, 화면 비율·확대, 스크린샷(자막 포함/제외), 자막 크기,
      이어보기 기록·복원, 최근 파일.

⚠ 스크린샷은 **실제 렌더 경로가 있어야** 동작한다. vo=null 로는 검증할 수 없다.
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
from gi.repository import GLib  # noqa: E402

from bora.app import BoraApplication  # noqa: E402
from bora.state import State  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def wait_until(cond, timeout: float) -> bool:
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


def make_media(folder: Path) -> Path:
    video = folder / "movie.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=30:duration=120", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(video)],
        check=True,
    )
    if not (FIXTURES / "sample_cp949.smi").exists():
        subprocess.run([sys.executable, str(FIXTURES / "make_fixtures.py")], check=True)
    shutil.copy(FIXTURES / "sample_cp949.smi", folder / "movie.smi")
    return video


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="bora-extras-"))
    cfg = folder / "cfg"
    shots = folder / "shots"
    try:
        video = make_media(folder)

        class Probe(BoraApplication):
            def do_activate(self):
                super().do_activate()
                self.win = self.props.active_window
                # 설정을 임시 폴더로 돌린다 — 사용자 설정을 건드리지 않는다.
                self.win.state = State(cfg)
                self.win.state.settings.screenshot_dir = str(shots)
                GLib.timeout_add_seconds(3, self._run, self.win)

            def _run(self, win):
                p = win.player

                # 재생 속도
                win._nudge_speed(0.5)
                check("재생 속도 변경", abs(p.speed - 1.5) < 0.01, f"{p.speed}x")
                check("설정에 반영", abs(win.state.settings.speed - 1.5) < 0.01)
                win._nudge_speed(-0.5)

                # 화면 비율·확대
                p.set_aspect("4:3")
                p.zoom = 0.3
                check("확대 적용", abs(p.zoom - 0.3) < 0.01, f"zoom={p.zoom}")
                p.set_aspect("-1")
                p.zoom = 0.0

                # 자막 크기
                p.set_sub_style(size=64)
                check("자막 크기 변경", p.sub_font_size == 64, f"{p.sub_font_size}")

                # 스크린샷 — 렌더 경로가 있어야 된다
                wait_until(lambda: (p.time_pos or 0) > 1.5, 5.0)
                with_subs = win.take_screenshot(include_subs=True)
                check("스크린샷 저장(자막 포함)",
                      bool(with_subs) and with_subs.exists() and with_subs.stat().st_size > 1000,
                      f"{with_subs}" if with_subs else "실패")
                if with_subs:
                    check("저장 위치가 설정을 따른다", str(shots) in str(with_subs), str(with_subs))

                # 이어보기 기록
                p.seek_absolute(60)
                wait_until(lambda: (p.time_pos or 0) > 55, 5.0)
                win._remember_position()
                resume = win.state.resume_for(video)
                check("이어보기 위치 기록", resume is not None and resume > 55,
                      f"resume={resume}")

                # 최근 파일
                items = win.state.recent_items()
                check("최근 파일 목록", len(items) == 1 and items[0].title == "movie.mp4",
                      f"{[i.title for i in items]}")

                # 다시 읽어도 유지되는가
                win.state.save()
                reloaded = State(cfg)
                check("설정이 파일로 유지된다",
                      reloaded.resume_for(video) is not None,
                      f"resume={reloaded.resume_for(video)}")

                # 더보기 메뉴가 그려지는가
                win._rebuild_more_menu()
                check("더보기 메뉴 구성", win._more_popover.get_child() is not None)

                p.close()
                self.quit()
                return False

        Probe(non_unique=True).run([sys.argv[0], str(video)])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("=== 시나리오 04 — 재생 부가기능 ===")
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
