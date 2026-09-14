# -*- coding: utf-8 -*-
"""학습 메모 문서 회귀 테스트 (기획서 v0.3 §6 N1~N5 의 파일 쪽).

가장 중요한 것: **메모 파일이 평문 마크다운이고, 밖에서 고친 것을 말없이 덮지 않는다.**
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.notes.model import NoteDocument, format_stamp, parse_stamps  # noqa: E402


def _video(tmp_path: Path, name: str = "lecture.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x00" * 8)
    return path


# ── 타임스탬프 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("seconds,expected", [
    (0, "[00:00:00]"), (None, "[00:00:00]"), (754.3, "[00:12:34]"),
    (3725, "[01:02:05]"), (-5, "[00:00:00]"),
])
def test_format_stamp(seconds, expected) -> None:
    assert format_stamp(seconds) == expected


def test_parse_stamps_handles_both_forms() -> None:
    stamps = parse_stamps("## [00:12:34] 합의\n본문 [1:05] 참고")
    assert [s.seconds for s in stamps] == [754.0, 65.0]


def test_parse_stamps_ignores_plain_text() -> None:
    assert parse_stamps("괄호 없는 12:34 와 [abc] 는 아니다") == []


# ── 경로 ─────────────────────────────────────────────────────────────────
def test_paths_sit_next_to_video(tmp_path: Path) -> None:
    """N5 — 영상 옆 평문 마크다운. 앱 밖에서도 찾을 수 있어야 한다."""
    video = _video(tmp_path)
    assert NoteDocument.path_for(video) == tmp_path / "lecture.md"
    assert NoteDocument.assets_dir_for(video) == tmp_path / "lecture.assets"


# ── 읽기·쓰기 ────────────────────────────────────────────────────────────
def test_new_note_starts_with_title(tmp_path: Path) -> None:
    doc = NoteDocument.load_for(_video(tmp_path), "분산시스템 3주차")
    assert doc.text.startswith("# 분산시스템 3주차")


def test_save_and_reload(tmp_path: Path) -> None:
    """N2·N4 — 저장되고, 다시 열면 그대로 있다."""
    video = _video(tmp_path)
    doc = NoteDocument.load_for(video)
    doc.text += "## [00:12:34] 합의 알고리즘\nRaft 는 리더를 먼저 뽑는다\n"
    assert doc.save() is True

    again = NoteDocument.load_for(video)
    assert "Raft 는 리더를 먼저 뽑는다" in again.text
    assert again.dirty is False


def test_saved_file_is_plain_markdown(tmp_path: Path) -> None:
    """N5 — Bora 없이 읽힌다."""
    video = _video(tmp_path)
    doc = NoteDocument.load_for(video, "강의")
    doc.text = "# 강의\n\n## [00:00:10] 시작\n내용\n"
    doc.save()
    body = (tmp_path / "lecture.md").read_text(encoding="utf-8")
    assert body == "# 강의\n\n## [00:00:10] 시작\n내용\n"


def test_save_is_noop_when_unchanged(tmp_path: Path) -> None:
    doc = NoteDocument.load_for(_video(tmp_path))
    doc.save()
    assert doc.save() is False


def test_save_adds_trailing_newline(tmp_path: Path) -> None:
    video = _video(tmp_path)
    doc = NoteDocument.load_for(video)
    doc.text = "끝에 줄바꿈이 없다"
    doc.save()
    assert (tmp_path / "lecture.md").read_text(encoding="utf-8").endswith("\n")


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    doc = NoteDocument.load_for(_video(tmp_path))
    doc.text += "내용"
    doc.save()
    assert not list(tmp_path.glob("*.tmp"))


def test_detects_outside_change(tmp_path: Path) -> None:
    """밖에서 고친 메모를 말없이 덮으면 안 된다."""
    video = _video(tmp_path)
    doc = NoteDocument.load_for(video)
    doc.text += "우리 편집\n"
    doc.save()
    assert doc.changed_outside() is False

    time.sleep(0.02)
    (tmp_path / "lecture.md").write_text("밖에서 고친 내용\n", encoding="utf-8")
    assert doc.changed_outside() is True


def test_unreadable_note_falls_back_to_new(tmp_path: Path) -> None:
    """읽기 실패가 앱을 막으면 안 된다."""
    video = _video(tmp_path)
    note = tmp_path / "lecture.md"
    note.mkdir()                    # 파일이 아니라 폴더 — 읽기 실패를 만든다
    doc = NoteDocument.load_for(video, "제목")
    assert doc.text.startswith("# 제목")


def test_heading_for_puts_cursor_after_space(tmp_path: Path) -> None:
    """N1 — `## [00:12:34] ` 뒤에 바로 이어 쓸 수 있어야 한다."""
    doc = NoteDocument.load_for(_video(tmp_path))
    assert doc.heading_for(754.3) == "## [00:12:34] "
    assert doc.heading_for(754.3, "제목 있음") == "## [00:12:34] 제목 있음\n"
