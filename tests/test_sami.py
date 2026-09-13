# -*- coding: utf-8 -*-
"""SAMI 분리 회귀 테스트.

고정하는 것: 한·영 통합 SAMI 를 클래스별로 나누면 P3(겹침)·P4(0초 큐)가 사라진다.
근거: docs/research/2026-09-13-mpv-playback-path-tests.md §3
"""

import re
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.subtitle.detect import detect  # noqa: E402
from bora.subtitle.sami import (  # noqa: E402
    Cue,
    language_of,
    looks_like_sami,
    parse,
    split_to_files,
    to_srt,
)

_TS_RE = re.compile(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)")


def setup_module(_module) -> None:
    if not (FIXTURES / "sample_cp949.smi").exists():
        sys.path.insert(0, str(FIXTURES))
        import make_fixtures

        make_fixtures.build()


def _durations(srt: str) -> list[int]:
    out = []
    for m in _TS_RE.finditer(srt):
        a = int(m[1]) * 3600000 + int(m[2]) * 60000 + int(m[3]) * 1000 + int(m[4])
        b = int(m[5]) * 3600000 + int(m[6]) * 60000 + int(m[7]) * 1000 + int(m[8])
        out.append(b - a)
    return out


def test_bilingual_sami_splits_into_two_tracks(tmp_path: Path) -> None:
    raw = (FIXTURES / "sample_cp949.smi").read_bytes()
    tracks = split_to_files(raw, detect(raw).encoding, tmp_path)
    assert [t.lang for t in tracks] == ["ko", "en"], "한국어 트랙이 먼저 와야 한다(기본 선택 대상)"
    assert all(t.path.exists() for t in tracks)


def test_no_zero_length_cue(tmp_path: Path) -> None:
    """P4 회귀 — 같은 시각의 SYNC 가 이어져도 큐 길이가 0이 되면 안 된다."""
    raw = (FIXTURES / "sample_cp949.smi").read_bytes()
    for track in split_to_files(raw, detect(raw).encoding, tmp_path):
        durations = _durations(track.path.read_text(encoding="utf-8"))
        assert durations, f"{track.lang}: 큐가 하나도 없다"
        assert all(d > 0 for d in durations), f"{track.lang}: 0초 큐가 있다 {durations}"


def test_korean_track_has_no_english(tmp_path: Path) -> None:
    """P3 회귀 — 한국어 트랙에 영어 줄이 섞이면 안 된다."""
    raw = (FIXTURES / "sample_cp949.smi").read_bytes()
    ko = [t for t in split_to_files(raw, detect(raw).encoding, tmp_path) if t.lang == "ko"][0]
    body = ko.path.read_text(encoding="utf-8")
    assert "First subtitle line" not in body
    assert "첫 번째 자막입니다." in body


def test_terminator_cue_is_not_emitted() -> None:
    """`&nbsp;` 단독 큐는 '자막을 지워라'는 신호지 자막이 아니다."""
    cues = [Cue(1000, "안녕하세요"), Cue(3000, "\xa0"), Cue(5000, "다음")]
    srt = to_srt(cues)
    assert "\xa0" not in srt
    assert srt.count(" --> ") == 2


def test_single_class_sami_is_not_split(tmp_path: Path) -> None:
    """클래스가 하나뿐이면 나눌 이유가 없다 — 원본을 그대로 쓰는 편이 낫다."""
    raw = (FIXTURES / "mid_cp949.smi").read_bytes()
    assert split_to_files(raw, detect(raw).encoding, tmp_path) == []


def test_language_mapping_prefers_style_lang() -> None:
    raw = (FIXTURES / "sample_cp949.smi").read_bytes()
    _cues, langs = parse(raw.decode("cp949"))
    assert language_of("KRCC", langs) == "ko"
    assert language_of("ENCC", langs) == "en"
    # STYLE 에 없으면 클래스 이름 관례로 떨어진다
    assert language_of("KRCC", {}) == "ko"
    assert language_of("ZZCC", {}) == "zzcc"


@pytest.mark.parametrize(
    "name,expected",
    [("sample_cp949.smi", True), ("mid_cp949.smi", True), ("plain_cp949.srt", False)],
)
def test_looks_like_sami(name: str, expected: bool) -> None:
    assert looks_like_sami((FIXTURES / name).read_bytes()) is expected
