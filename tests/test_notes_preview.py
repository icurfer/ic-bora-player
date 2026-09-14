# -*- coding: utf-8 -*-
"""마크다운 라이브 프리뷰 회귀 테스트.

`#` 같은 마크업을 감추고 스타일만 보여 주되, **편집 중인 줄은 원본을 드러낸다**.
그래야 고칠 수 있다. 파일 내용은 절대 바뀌지 않는다 — 보이는 것만 다르다.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from bora.notes.panel import NotePanel  # noqa: E402

SAMPLE = """# 큰 제목
## 작은 제목
**굵게** 와 *기울임* 와 `코드`
- 목록 항목
> 인용문
## [00:12:34] 타임스탬프
"""


@pytest.fixture
def panel():
    """창 없이 버퍼만 있는 패널. 태그 계산만 검증한다."""
    p = NotePanel.__new__(NotePanel)
    Gtk.Box.__init__(p, orientation=Gtk.Orientation.VERTICAL)
    p.window = object()
    p.doc = None
    p._save_id = 0
    p._loading = False
    p._last_line = -1
    p._buffer = Gtk.TextBuffer()
    p._make_tags()
    return p


def tags_at(panel, offset: int) -> set[str]:
    it = panel._buffer.get_iter_at_offset(offset)
    return {t.get_property("name") for t in it.get_tags()}


def prepare(panel, text: str = SAMPLE, cursor_line: int = 0):
    panel._buffer.set_text(text)
    ok, it = panel._buffer.get_iter_at_line(cursor_line)
    if ok:
        panel._buffer.place_cursor(it)
    panel._retag()
    return text


def test_heading_marks_are_hidden(panel) -> None:
    text = prepare(panel, cursor_line=5)
    assert "hidden" in tags_at(panel, 0)            # '#'
    assert "h1" in tags_at(panel, 2)                # 본문
    assert "hidden" not in tags_at(panel, 2)


def test_heading_levels_get_different_scale(panel) -> None:
    prepare(panel, cursor_line=5)
    assert "h1" in tags_at(panel, 2)
    assert "h2" in tags_at(panel, SAMPLE.index("작은 제목"))


def test_editing_line_reveals_markup(panel) -> None:
    """커서가 간 줄은 원본이 보여야 고칠 수 있다."""
    prepare(panel, cursor_line=2)                    # '**굵게**' 줄
    at = SAMPLE.index("**굵게**")
    assert "hidden" not in tags_at(panel, at)
    assert "bold" in tags_at(panel, at + 2)          # 스타일은 그대로 적용


def test_non_editing_line_hides_markup(panel) -> None:
    prepare(panel, cursor_line=0)                    # 커서는 첫 줄
    at = SAMPLE.index("**굵게**")
    assert "hidden" in tags_at(panel, at)
    assert "bold" in tags_at(panel, at + 2)


def test_inline_styles(panel) -> None:
    prepare(panel, cursor_line=0)
    assert "italic" in tags_at(panel, SAMPLE.index("*기울임*") + 1)
    assert "code" in tags_at(panel, SAMPLE.index("`코드`") + 1)


def test_bullet_is_marked_but_not_hidden(panel) -> None:
    """목록 기호는 감추지 않는다 — 파일에 그대로 있고, 보이는 편이 낫다."""
    prepare(panel, cursor_line=0)
    at = SAMPLE.index("- 목록")
    assert "bullet" in tags_at(panel, at)
    assert "hidden" not in tags_at(panel, at)


def test_quote_mark_is_hidden(panel) -> None:
    prepare(panel, cursor_line=0)
    at = SAMPLE.index("> 인용문")
    assert {"hidden", "quote"} <= tags_at(panel, at)


def test_timestamp_always_visible(panel) -> None:
    """타임스탬프는 어느 줄이든 표시된다 — 클릭 대상이기 때문이다."""
    prepare(panel, cursor_line=0)
    at = SAMPLE.index("[00:12:34]")
    assert "stamp" in tags_at(panel, at)
    assert "hidden" not in tags_at(panel, at)


def test_buffer_text_is_unchanged(panel) -> None:
    """가장 중요한 회귀 — 보이는 것만 바뀌고 파일 내용은 그대로다.

    ⚠ 반드시 **저장에 쓰이는 경로**(`_text()`)로 확인해야 한다. 버퍼를 직접
       `get_text(..., True)` 로 읽으면 통과하는데 저장은 다른 경로를 타서 `#` 이
       빠진 적이 있다. 테스트는 실제로 쓰이는 길을 지나야 한다.
    """
    prepare(panel, cursor_line=1)
    assert panel._text() == SAMPLE
    assert "# 큰 제목" in panel._text()
    assert "**굵게**" in panel._text()


def test_hidden_markup_still_saved(panel) -> None:
    """마크업이 감춰진 줄에서도 원본이 그대로 나와야 한다."""
    prepare(panel, "# 제목\n**굵게**\n", cursor_line=5)   # 어느 줄도 편집 중이 아니다
    assert panel._text() == "# 제목\n**굵게**\n"


def test_plain_text_gets_no_tags(panel) -> None:
    prepare(panel, "그냥 줄글입니다\n", cursor_line=5)
    assert tags_at(panel, 3) == set()


def test_asterisk_without_pair_is_left_alone(panel) -> None:
    """곱하기 기호 같은 홑 별표를 마크업으로 오해하면 안 된다."""
    prepare(panel, "2 * 3 = 6\n", cursor_line=5)
    assert tags_at(panel, 2) == set()
