# -*- coding: utf-8 -*-
"""자막 편집·저장 회귀 테스트.

가장 중요한 것: **원본을 잃지 않는다**(기획서 v0.2 §6 의 최대 위험).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.subtitle.model import Cue, SubtitleDocument, ms_to_srt, srt_to_ms  # noqa: E402
from bora.subtitle.writer import backup_path, save_srt, target_path  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

SRT = """1
00:00:02,000 --> 00:00:06,000
첫 줄

2
00:00:08,000 --> 00:00:12,000
둘째 줄
세 번째 줄

3
00:00:14,000 --> 00:00:14,001
&nbsp;
"""


def _doc(tmp_path: Path, body: str = SRT, name: str = "movie.srt") -> SubtitleDocument:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return SubtitleDocument.load(path)


# ── 시각 변환 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,ms", [
    ("00:00:02,000", 2000), ("01:02:03,456", 3723456),
    ("2", 2000), ("1:30", 90000), ("0:00:01,5", 1500),
])
def test_srt_to_ms(text: str, ms: int) -> None:
    assert srt_to_ms(text) == ms


def test_bad_time_is_rejected() -> None:
    for bad in ("아무말", "", "12:xx", "1:2:3:4"):
        with pytest.raises(ValueError):
            srt_to_ms(bad)


def test_ms_to_srt_roundtrip() -> None:
    assert ms_to_srt(3723456) == "01:02:03,456"
    assert srt_to_ms(ms_to_srt(987654)) == 987654


# ── 읽기 ─────────────────────────────────────────────────────────────────
def test_load_srt_skips_empty_cues(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    assert len(doc.cues) == 2               # &nbsp; 큐는 버린다
    assert doc.cues[1].text == "둘째 줄\n세 번째 줄"


def test_load_sami(tmp_path: Path) -> None:
    if not (FIXTURES / "sample_cp949.smi").exists():
        sys.path.insert(0, str(FIXTURES))
        import make_fixtures
        make_fixtures.build()
    doc = SubtitleDocument.load(FIXTURES / "sample_cp949.smi")
    assert doc.encoding == "cp949"
    assert len(doc.cues) >= 2
    assert all(c.duration_ms > 0 for c in doc.cues), "0초 큐가 있으면 안 된다"


# ── 현재 큐 잡기 ─────────────────────────────────────────────────────────
def test_cue_at_inside(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    assert doc.cue_at(3000) == 0
    assert doc.cue_at(9000) == 1


def test_cue_at_gap_returns_previous(tmp_path: Path) -> None:
    """자막이 늦게 뜰 때 '지금 나와야 할 줄'을 고치려면 직전 큐가 잡혀야 한다."""
    doc = _doc(tmp_path)
    assert doc.cue_at(7000) == 0            # 1번과 2번 사이
    assert doc.cue_at(99000) == 1           # 끝 이후
    assert doc.cue_at(0) == 0               # 시작 이전


# ── 편집 ─────────────────────────────────────────────────────────────────
def test_set_start_keeps_minimum_duration(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    doc.set_start(0, 5999)
    assert doc.cues[0].start_ms == 5999
    assert doc.cues[0].duration_ms >= SubtitleDocument.MIN_DURATION_MS


def test_shift_from_only_moves_later_cues(tmp_path: Path) -> None:
    """E2 — 이 줄부터 뒤로 전부 밀기. 앞 줄은 그대로여야 한다."""
    doc = _doc(tmp_path)
    before = doc.cues[0].start_ms
    doc.shift_from(1, -2000)
    assert doc.cues[0].start_ms == before
    assert doc.cues[1].start_ms == 6000


def test_shift_does_not_go_negative(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    doc.shift_all(-999999)
    assert all(c.start_ms >= 0 and c.end_ms >= 0 for c in doc.cues)


def test_undo(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    original = doc.cues[0].start_ms
    doc.set_start(0, 12345)
    assert doc.can_undo()
    assert doc.undo()
    assert doc.cues[0].start_ms == original


def test_insert_and_remove(tmp_path: Path) -> None:
    doc = _doc(tmp_path)
    index = doc.insert_after(0, "새 줄")
    assert doc.cues[index].text == "새 줄"
    doc.remove(index)
    assert len(doc.cues) == 2


# ── 저장 ─────────────────────────────────────────────────────────────────
def test_save_makes_backup_and_keeps_original_content(tmp_path: Path) -> None:
    """E3 — 가장 중요한 회귀. 원본 내용이 .bak 에 그대로 남아야 한다."""
    path = tmp_path / "movie.srt"
    path.write_text(SRT, encoding="utf-8")
    doc = SubtitleDocument.load(path)
    doc.shift_all(-2000)

    dest, backup = save_srt(doc.to_srt(), path)
    assert dest == path
    assert backup is not None and backup.exists()
    assert backup.read_text(encoding="utf-8") == SRT       # 원본 그대로
    assert "00:00:00,000" in dest.read_text(encoding="utf-8")


def test_backup_does_not_overwrite_previous_backup(tmp_path: Path) -> None:
    path = tmp_path / "movie.srt"
    path.write_text(SRT, encoding="utf-8")
    save_srt("첫 저장", path)
    save_srt("둘째 저장", path)
    backups = sorted(p.name for p in tmp_path.glob("movie.srt.bak*"))
    assert len(backups) == 2, backups


def test_sami_is_saved_as_srt_and_original_survives(tmp_path: Path) -> None:
    """E4 — SAMI 원본은 건드리지 않고 .srt 로 저장한다."""
    smi = tmp_path / "movie.smi"
    body = "<SAMI><BODY><SYNC Start=1000><P Class=KRCC>한 줄\n</BODY></SAMI>\n"
    smi.write_bytes(body.encode("cp949"))
    doc = SubtitleDocument.load(smi)

    assert target_path(smi) == tmp_path / "movie.srt"
    dest, backup = save_srt(doc.to_srt(), smi)
    assert dest.suffix == ".srt"
    assert backup is None                       # 새 파일이라 백업할 것이 없다
    assert smi.exists() and smi.read_bytes() == body.encode("cp949")


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "movie.srt"
    path.write_text(SRT, encoding="utf-8")
    save_srt("내용", path)
    assert not list(tmp_path.glob("*.tmp"))


def test_backup_path_numbering(tmp_path: Path) -> None:
    path = tmp_path / "a.srt"
    path.write_text("x", encoding="utf-8")
    first = backup_path(path)
    first.write_text("x", encoding="utf-8")
    assert backup_path(path).name == "a.srt.bak2"


def test_to_srt_is_sorted_and_renumbered(tmp_path: Path) -> None:
    doc = SubtitleDocument([Cue(5000, 6000, "나중"), Cue(1000, 2000, "먼저")])
    body = doc.to_srt()
    assert body.index("먼저") < body.index("나중")
    assert body.startswith("1\n")
