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


# ── 타임라인 (기획 v0.5) ─────────────────────────────────────────────────
from bora.clip.model import Timeline  # noqa: E402


def test_starts_as_one_whole_clip() -> None:
    """v0.4 와 기본이 반대다 — 전체가 놓여 있고 잘라서 줄인다."""
    t = Timeline(100)
    assert len(t) == 1 and t[0].start == 0 and t[0].end == 100
    assert t.output_duration() == 100
    assert not t.dirty


def test_split_makes_two_touching_clips() -> None:
    t = Timeline(100)
    assert t.split(40) == 1
    assert [(c.start, c.end) for c in t] == [(0, 40), (40, 100)]
    assert t.output_duration() == 100        # 자르기만으로는 길이가 줄지 않는다


def test_split_at_edge_is_refused() -> None:
    """0 길이 구간을 만들지 않는다."""
    t = Timeline(100)
    assert t.split(0) == -1
    assert t.split(100) == -1
    assert t.split(99.99) == -1
    assert len(t) == 1


def test_disabled_clip_leaves_the_result() -> None:
    t = Timeline(100)
    t.split(40)
    t.toggle(0)
    assert t.output_duration() == 60
    assert [c.start for c in t.enabled_clips()] == [40]
    assert len(t) == 2                       # 지운 것도 목록엔 남는다(되살리려고)
    t.toggle(0)
    assert t.output_duration() == 100


def test_trim_moves_the_neighbour_too() -> None:
    """빈틈을 만들지 않는다 — 경계를 끌면 이웃이 같이 준다."""
    t = Timeline(100)
    t.split(40)
    t.trim(1, start=30)
    assert [(c.start, c.end) for c in t] == [(0, 30), (30, 100)]
    t.trim(0, end=50)
    assert [(c.start, c.end) for c in t] == [(0, 50), (50, 100)]


def test_trim_is_clamped_by_neighbours() -> None:
    # 부동소수점 뺄셈이라 정확히 MIN_SPLIT_GAP 이 아니라 그 언저리다. 요지는
    # "이웃이 0 길이로 뭉개지지 않는다" 이므로 그만큼의 여유를 두고 본다.
    from bora.clip.model import MIN_SPLIT_GAP
    floor = MIN_SPLIT_GAP * 0.9

    t = Timeline(100)
    t.split(40)
    t.trim(1, start=-999)                    # 앞 구간을 0 아래로 밀 수 없다
    assert t[0].start == 0 and t[1].start >= floor
    assert t[0].duration >= floor
    t2 = Timeline(100)
    t2.split(40)
    t2.trim(0, end=9999)                     # 뒤 구간을 없앨 수 없다
    assert t2[1].end == 100 and t2[1].duration >= floor


def test_move_reorders_without_changing_source_times() -> None:
    t = Timeline(100)
    t.split(40)
    assert t.move(0, 1) == 1
    assert [(c.start, c.end) for c in t] == [(40, 100), (0, 40)]


def test_source_to_output_skips_cut_parts() -> None:
    t = Timeline(100)
    t.split(40)
    t.toggle(0)                              # 0~40 을 들어낸다
    assert t.source_to_output(40) == 0.0
    assert t.source_to_output(70) == 30.0
    assert t.source_to_output(20) is None    # 잘려 나간 자리


def test_preview_jumps_over_cut_parts() -> None:
    t = Timeline(100)
    t.split(40)
    t.split(70)
    t.toggle(1)                              # 40~70 을 들어낸다
    assert t.next_enabled_start(10) is None  # 살아 있는 구간 안 — 그냥 재생
    assert t.next_enabled_start(50) == 70    # 잘린 자리 — 다음 시작으로 건너뛴다
    assert t.next_enabled_start(95) is None  # 마지막 구간 안


def test_undo_redo_covers_every_edit() -> None:
    t = Timeline(100)
    t.split(40); t.toggle(0); t.move(0, 1)
    assert t.can_undo and not t.can_redo
    for _ in range(3):
        assert t.undo()
    assert [(c.start, c.end) for c in t] == [(0, 100)]
    assert not t.can_undo and t.can_redo
    assert t.redo()
    assert len(t) == 2


def test_undo_restores_a_copy_not_a_reference() -> None:
    """스냅숏이 얕으면 되돌린 뒤 편집이 과거까지 바꾼다."""
    t = Timeline(100)
    t.split(40)
    t.trim(0, end=50)
    t.undo()
    assert t[0].end == 40


def test_dirty_tells_whether_to_ask_on_close() -> None:
    t = Timeline(100)
    assert not t.dirty
    t.split(40)
    assert t.dirty


def test_remove_lets_the_neighbour_absorb() -> None:
    t = Timeline(100)
    t.split(40)
    t.remove(1)
    assert [(c.start, c.end) for c in t] == [(0, 100)]
    assert not t.remove(0)                   # 마지막 하나는 남긴다


# ── 썸네일 조회 (기획 v0.5) ──────────────────────────────────────────────
from bora.clip.thumbs import ThumbStrip, snap  # noqa: E402


def _strip_with(times):
    strip = ThumbStrip(Path("/nonexistent.mkv"))
    for t in times:
        strip._cache[float(t)] = f"thumb@{t:.0f}"
    strip._keys_dirty = True
    return strip


def test_exact_hit() -> None:
    strip = _strip_with([0, 631, 1262])
    assert strip.get(631.0) == "thumb@631"


def test_off_by_rounding_misses_without_tolerance() -> None:
    """이게 실제 버그였다 — 요청 격자는 630.9초 간격인데 그리기는 픽셀 폭으로 걸어
    633 을 찾았고, 화면 전체가 빈칸으로 남았다."""
    strip = _strip_with([0, 631, 1262])
    assert strip.get(633.0) is None


def test_tolerance_uses_the_nearest() -> None:
    strip = _strip_with([0, 631, 1262])
    assert strip.get(633.0, 120) == "thumb@631"
    assert strip.get(1200.0, 120) == "thumb@1262"


def test_tolerance_does_not_reach_too_far() -> None:
    """너무 먼 그림을 끌어다 쓰면 엉뚱한 장면이 보인다."""
    strip = _strip_with([0, 631, 1262])
    assert strip.get(1000.0, 120) is None
    assert strip.get(4000.0, 300) is None


def test_snap_quantises_to_one_second() -> None:
    assert snap(631.4) == 631.0
    assert snap(631.6) == 632.0
    assert snap(-5) == 0.0
