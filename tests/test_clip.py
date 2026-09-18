# -*- coding: utf-8 -*-
"""클립(자르기·이어붙이기) 회귀 테스트 — 기획서 v0.4.

ffmpeg 를 실제로 돌리는 것은 느리고 표본 영상이 필요해 여기서 하지 않는다.
대신 **판단하는 층**을 본다: 구간 정규화, 목록 조작, 그리고 이어붙이기 가능 판정.

마지막 것이 특히 중요하다 — 실측(`docs/research/2026-09-19-…` E)에서 코덱이 다른 조각을
이어붙이면 ffmpeg 이 오류 없이 깨진 파일을 만들었다. 그 방어선이 살아 있는지 본다.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bora.clip.model import Clip, ClipList, fmt, fmt_span  # noqa: E402
from bora.clip.probe import StreamInfo, can_stream_copy  # noqa: E402
from bora.clip.runner import ExportJob, ExportRunner  # noqa: E402


# ── 구간 ─────────────────────────────────────────────────────────────────
def test_reversed_range_is_fixed() -> None:
    """F5/F6 를 거꾸로 누르는 일이 흔하다. 조용히 바로잡는다."""
    clip = Clip(230, 200)
    assert (clip.start, clip.end) == (200, 230)
    assert clip.duration == 30


def test_negative_start_clamped() -> None:
    assert Clip(-5, 10).start == 0.0


def test_too_short_is_invalid() -> None:
    """키프레임 간격(실측 1.0~4.4초)보다 짧은 클립은 실수로 두 번 누른 경우다."""
    assert not Clip(100, 100.2).valid
    assert Clip(100, 101).valid


def test_label_reads_like_a_range() -> None:
    assert Clip(200, 230).label() == "03:20 ~ 03:50 · 30초"
    assert Clip(200, 230, "결론").label() == "03:20 ~ 03:50 · 30초 · 결론"


def test_time_formats() -> None:
    assert fmt(200) == "03:20"
    assert fmt(3800) == "1:03:20"
    assert fmt_span(30) == "30초"
    assert fmt_span(120) == "2분"
    assert fmt_span(95) == "1분 35초"


# ── 목록 ─────────────────────────────────────────────────────────────────
def test_list_keeps_insertion_order() -> None:
    """시각순으로 정렬하지 않는다 — 결론을 먼저 붙이고 싶을 수 있다."""
    clips = ClipList()
    clips.add(Clip(500, 520))
    clips.add(Clip(100, 120))
    assert [c.start for c in clips] == [500, 100]


def test_move_returns_new_index_and_clamps() -> None:
    clips = ClipList()
    for start in (0, 100, 200):
        clips.add(Clip(start, start + 10))
    assert clips.move(0, 1) == 1
    assert [c.start for c in clips] == [100, 0, 200]
    assert clips.move(0, -1) == 0          # 맨 위에서 더 올라가지 않는다
    assert clips.move(2, 1) == 2           # 맨 아래에서 더 내려가지 않는다


def test_remove_and_total() -> None:
    clips = ClipList()
    clips.add(Clip(0, 30))
    clips.add(Clip(100, 145))
    assert clips.total_duration() == 75
    clips.remove(0)
    assert len(clips) == 1 and clips.total_duration() == 45
    clips.remove(99)                       # 범위 밖은 조용히 무시
    assert len(clips) == 1


# ── 이어붙이기 판정 (실측 E 의 방어선) ───────────────────────────────────
HEVC = StreamInfo("hevc", 1920, 1080, "aac", 48000, 8)
H264 = StreamInfo("h264", 1920, 1080, "aac", 48000, 8)
SMALL = StreamInfo("hevc", 1280, 720, "aac", 48000, 8)


def test_same_format_can_copy() -> None:
    assert can_stream_copy([HEVC, HEVC]) is None


def test_single_piece_needs_no_check() -> None:
    assert can_stream_copy([HEVC]) is None


def test_different_codec_is_blocked() -> None:
    """ffmpeg 은 이 조합을 그냥 통과시켜 깨진 파일을 만든다. 우리가 막는다."""
    reason = can_stream_copy([HEVC, H264])
    assert reason and "hevc" in reason and "h264" in reason


def test_different_resolution_is_blocked() -> None:
    assert can_stream_copy([HEVC, SMALL])


def test_unreadable_piece_is_blocked() -> None:
    """판정하지 못한 것을 '괜찮다'로 넘기지 않는다."""
    assert can_stream_copy([HEVC, None])


# ── 작업 ─────────────────────────────────────────────────────────────────
def test_estimate_scales_with_mode() -> None:
    clips = [Clip(0, 600)]
    fast = ExportJob(Path("a.mkv"), clips, Path("o.mkv"), mode="copy")
    exact = ExportJob(Path("a.mkv"), clips, Path("o.mkv"), mode="encode")
    assert exact.estimated_seconds() > fast.estimated_seconds()
    assert 100 < exact.estimated_seconds() < 140      # 실측 5배속 기준 120초


def test_empty_job_is_refused() -> None:
    errors = []
    runner = ExportRunner(on_error=errors.append)
    assert not runner.start(ExportJob(Path("a.mkv"), [], Path("o.mkv")))
    assert errors and "클립" in errors[0]


def test_cut_command_maps_selected_audio_track() -> None:
    """더빙 트랙을 골라 보고 있었다면 그 트랙이 딸려 나가야 한다."""
    runner = ExportRunner()
    job = ExportJob(Path("in.mkv"), [Clip(10, 20)], Path("out.mkv"),
                    mode="copy", audio_track=2)
    command = runner._cut_command(job, job.clips[0], Path("t.mkv"))
    assert "0:a:2?" in command
    assert command.index("-ss") < command.index("-i")   # 앞에 둬야 빠르다
    assert "-c" in command and "copy" in command


def test_encode_command_uses_encoder() -> None:
    runner = ExportRunner()
    job = ExportJob(Path("in.mkv"), [Clip(10, 20)], Path("out.mkv"), mode="encode")
    command = runner._cut_command(job, job.clips[0], Path("t.mkv"))
    assert "libx264" in command and "aac" in command
