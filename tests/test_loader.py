# -*- coding: utf-8 -*-
"""자막 계획(loader) 회귀 테스트.

특히 **엔티티만 있는 큐**를 잡아내는지 고정한다. 실제 영화 자막에서 2665 큐 중 1332 개가
`&nbsp;` 단독이었고, 그것이 화면에 빈 칸으로 찍혀 "자막이 안 나온다"로 보였다(research 5).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.subtitle.loader import (  # noqa: E402
    EMPTY_CUE_REGEX,
    find_sidecar,
    prepare,
    prepare_for_video,
)

SAMI_TO_SRT = """1
00:00:01,500 --> 00:00:11,481
자막 및 번역팀

2
00:00:11,481 --> 00:00:11,482
&nbsp;

3
00:00:11,482 --> 00:00:16,514
첫 번째 대사

4
00:00:16,514 --> 00:00:16,515
&nbsp;
"""

CLEAN_SRT = """1
00:00:01,000 --> 00:00:03,000
깨끗한 자막

2
00:00:04,000 --> 00:00:06,000
두 번째 줄
"""


def _video_with(tmp_path: Path, name: str, body: str, encoding: str = "utf-8") -> Path:
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"\x00" * 16)
    (tmp_path / name).write_text(body, encoding=encoding)
    return video


def test_entity_only_cues_are_detected(tmp_path: Path) -> None:
    video = _video_with(tmp_path, "movie.srt", SAMI_TO_SRT)
    plan = prepare_for_video(video, tmp_path / "cache")
    assert plan is not None
    assert plan.empty_cue_filter is True
    assert plan.empty_cue_count == 2
    assert plan.sub_filters == [EMPTY_CUE_REGEX]
    assert "빈 큐 2개 정리" in plan.summary()


def test_clean_subtitle_gets_no_filter(tmp_path: Path) -> None:
    """엔티티가 없으면 필터를 켜지 않는다 — 켤 이유가 없다."""
    video = _video_with(tmp_path, "movie.srt", CLEAN_SRT)
    plan = prepare_for_video(video, tmp_path / "cache")
    assert plan is not None
    assert plan.empty_cue_filter is False
    assert plan.sub_filters == []


def test_utf8_bom_is_still_utf8(tmp_path: Path) -> None:
    """BOM 이 붙은 UTF-8 도 UTF-8 로 판정해야 한다(실제 자막에 흔하다)."""
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"\x00" * 16)
    (tmp_path / "movie.srt").write_bytes(b"\xef\xbb\xbf" + CLEAN_SRT.encode("utf-8"))
    plan = prepare_for_video(video, tmp_path / "cache")
    assert plan is not None
    assert plan.detect.encoding == "utf-8"
    assert plan.codepage == "+utf-8"


def test_sidecar_found_with_spaces_and_parens(tmp_path: Path) -> None:
    """실제 파일 이름에는 공백·괄호가 흔하다. glob 특수문자에 걸리면 안 된다."""
    stem = "Inside Out (2015) (1080p BluRay x265 10bit Tigole)"
    video = tmp_path / f"{stem}.mkv"
    video.write_bytes(b"\x00" * 16)
    sub = tmp_path / f"{stem}.srt"
    sub.write_text(CLEAN_SRT, encoding="utf-8")
    assert find_sidecar(video) == sub


def test_sidecar_with_language_suffix(tmp_path: Path) -> None:
    """`movie.ko.smi` 같은 국내 관례도 찾아야 한다."""
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"\x00" * 16)
    sub = tmp_path / "movie.ko.srt"
    sub.write_text(CLEAN_SRT, encoding="utf-8")
    assert find_sidecar(video) == sub


def test_missing_subtitle_returns_none(tmp_path: Path) -> None:
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"\x00" * 16)
    assert prepare_for_video(video, tmp_path / "cache") is None


def test_cache_is_not_beside_the_video(tmp_path: Path) -> None:
    """임시 파일을 원본 폴더에 쓰면 안 된다(읽기 전용 매체일 수 있다)."""
    video = _video_with(tmp_path, "movie.srt", CLEAN_SRT)
    cache = tmp_path / "cache"
    prepare(video, tmp_path / "movie.srt", cache)
    assert not list(tmp_path.glob("*.ko.srt"))
