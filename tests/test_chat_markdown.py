"""응답 원본과 표시를 분리하고, 표와 코드의 내용 및 이스케이프를 확인한다."""
from gi.repository import Gtk

from bora.ai.markdown import MarkdownView, inline


def children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def test_heading_emphasis_table_and_code_preserve_raw_buffer():
    raw = '# 활성함수\n**핵심**과 `ReLU`\n\n| 종류 | 음수 |\n|---|---|\n| ReLU | 0 |\n| Leaky | 작은 기울기 |\n\n```python\nx = "**원본** <tag>"\n```'
    buffer = Gtk.TextBuffer()
    buffer.set_text(raw)
    view = MarkdownView(buffer)
    blocks = list(children(view))
    labels = [w for w in blocks if isinstance(w, Gtk.Label)]
    assert labels[0].get_text() == '활성함수'
    assert labels[1].get_text() == '핵심과 ReLU'
    assert '<b>핵심</b>' in labels[1].get_label()
    table = next(w for w in blocks if isinstance(w, Gtk.Grid))
    assert [w.get_text() for w in children(table)] == ['종류', '음수', 'ReLU', '0', 'Leaky', '작은 기울기']
    assert labels[-1].get_text() == 'x = "**원본** <tag>"'
    assert buffer.get_text(*buffer.get_bounds(), True) == raw


def test_response_markup_cannot_inject_pango():
    assert inline('<span size="999999">가짜</span> & **실제**') == (
        '&lt;span size=&quot;999999&quot;&gt;가짜&lt;/span&gt; &amp; <b>실제</b>')


def test_streaming_unclosed_fence_keeps_literal_code():
    buffer = Gtk.TextBuffer()
    buffer.set_text('```\n**코드 중간**')
    view = MarkdownView(buffer)
    assert view.get_first_child().get_text() == '**코드 중간**'
