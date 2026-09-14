#!/usr/bin/env python3
"""시나리오 02 — 자막 수용 테스트 T1~T4 (기획서 §6)

  python3 .claude/skills/verify-app/scenarios/02-subtitle-acceptance.py

실제 앱을 띄워 '화면에 나온 자막'을 모은다. 표본은 tests/fixtures 에서 가져와 임시 폴더에
영상과 같은 이름으로 놓는다 — T1 의 조건이 바로 그것이다.

통과 기준
  T1 CP949 SAMI 동명 파일  -> 설정 없이 한글 자막이 나온다
  T2 107 바이트급 짧은 SAMI -> 한글이 깨지지 않는다(탐지기 단독으로는 1252 로 오탐하는 표본)
  T3 한·영 통합 SAMI       -> 한국어 트랙 기본 선택 + 트랙 2개 + 화면에 영어가 섞이지 않는다
  T4 UTF-8 SRT            -> 그대로 정상

⚠ 케이스마다 **별도 프로세스**로 돌린다. 한 프로세스에서 Gtk Application 을 여러 번
   run() 하면 두 번째부터 제대로 뜨지 않는다(실측).
⚠ seek 로 특정 시각을 찍어 읽지 말고, 재생하면서 주기적으로 sub-text 를 모은다.
   seek 직후에는 자막이 아직 갱신되지 않아 빈 문자열이 잡힌다(실측).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "tests" / "fixtures"

# 이름, 표본 파일(None 이면 즉석 생성), 자막 확장자, 화면에 나와야 할 조각,
# 최소 트랙 수, 화면에 나오면 안 되는 조각
CASES = {
    "T1": ("CP949 SAMI 동명 자동 로드", "sample_cp949.smi", ".smi", "첫 번째 자막입니다", 2, None),
    "T2": ("짧은 CP949 SAMI(107 B)", "short_cp949.smi", ".smi", "안녕하세요", 1, None),
    "T3": ("한·영 통합 SAMI", "sample_cp949.smi", ".smi", "똠방각하", 2, "First subtitle line"),
    "T4": ("UTF-8 SRT", None, ".srt", "유니코드 자막", 1, None),
}
SAMPLES = 16          # 0.5초 간격으로 8초
INTERVAL_MS = 500


def build_case(key: str, folder: Path) -> Path:
    _name, fixture, suffix, *_ = CASES[key]
    video = folder / "movie.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "ultrafast", str(video)],
        check=True,
    )
    if fixture:
        shutil.copy(FIXTURES / fixture, folder / ("movie" + suffix))
    else:
        (folder / "movie.srt").write_text(
            "1\n00:00:01,000 --> 00:00:06,000\n유니코드 자막\n\n", encoding="utf-8")
    return video


def run_child(key: str) -> dict:
    """자식 프로세스에서 앱을 띄워 관찰 결과를 JSON 으로 돌려준다."""
    folder = Path(tempfile.mkdtemp(prefix="bora-verify-"))
    try:
        video = build_case(key, folder)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", str(video)],
            capture_output=True, text=True, timeout=120,
        )
        for line in reversed(proc.stdout.splitlines()):
            if line.startswith("{"):
                return json.loads(line)
        return {"error": proc.stderr.strip()[-400:] or "결과를 받지 못했다"}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def child_main(video: str) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib

    from bora.app import BoraApplication

    seen: list[str] = []
    out: dict = {}

    class Probe(BoraApplication):
        def do_activate(self):
            super().do_activate()
            self.win = self.props.active_window
            self.n = 0
            GLib.timeout_add(INTERVAL_MS, self._sample)

        def _sample(self):
            self.n += 1
            p = self.win.player
            try:
                text = (p.sub_text or "").strip()
                if text and text not in seen:
                    seen.append(text)
                if self.n >= SAMPLES:
                    out["tracks"] = [
                        {"title": t.get("title") or t.get("lang"), "selected": bool(t.get("selected"))}
                        for t in p.sub_tracks
                    ]
                    out["summary"] = self.win._plan.summary() if self.win._plan else "(자막 없음)"
                    p.close()
                    self.quit()
                    return False
            except Exception as exc:
                out["error"] = repr(exc)
                self.quit()
                return False
            return True

    Probe(non_unique=True).run([sys.argv[0], video])
    out["seen"] = seen
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main() -> int:
    if not (FIXTURES / "sample_cp949.smi").exists():
        subprocess.run([sys.executable, str(FIXTURES / "make_fixtures.py")], check=True)

    failures = []
    for key, (name, _f, _s, expect, min_tracks, forbidden) in CASES.items():
        got = run_child(key)
        seen = got.get("seen", [])
        tracks = got.get("tracks", [])
        joined = " | ".join(seen)

        problems = []
        if got.get("error"):
            problems.append(got["error"])
        if expect not in joined:
            problems.append(f"기대한 자막이 화면에 안 나왔다: {expect!r}")
        if len(tracks) < min_tracks:
            problems.append(f"트랙이 {len(tracks)}개뿐이다(최소 {min_tracks})")
        if forbidden and forbidden in joined:
            problems.append(f"섞이면 안 되는 텍스트가 나왔다: {forbidden!r}")
        if min_tracks >= 2 and tracks and not tracks[0]["selected"]:
            problems.append("첫 트랙(한국어)이 기본 선택되지 않았다")

        print(f"[{'통과' if not problems else '실패'}] {key} {name}")
        print(f"         요약 : {got.get('summary')}")
        print(f"         화면 : {seen}")
        print(f"         트랙 : {tracks}")
        for p in problems:
            print(f"         ! {p}")
        if problems:
            failures.append(key)

    if failures:
        print(f"\n실패: {', '.join(failures)}")
        return 1
    print("\n전부 통과 (T1~T4)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        raise SystemExit(child_main(sys.argv[2]))
    raise SystemExit(main())
