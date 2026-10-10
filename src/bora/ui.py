"""OS 공통 화면 기준. GTK4/libadwaita 1.1에서 사용할 수 있는 API만 쓴다.

일반 위젯은 Adwaita 스타일을 따른다. 직접 그리는 문서 태그와 영상 안내만 여기서
보완한다. 최신 accent API/CSS 변수 대신 GTK4 초기 버전의 named color를 사용한다.
"""
from gi.repository import Gdk, Gtk

WINDOW_WIDTH = 960
WINDOW_HEIGHT = 700
PANEL_WIDTH = 320
STUDY_WIDTH = 340
NOTE_INITIAL_HEIGHT = 230

MEDIA_HINT_CSS = (
    b"label { color: white; background: rgba(0,0,0,0.85); "
    b"padding: 20px; border-radius: 12px; }")


def _color(context, name: str, fallback: str):
    found, color = context.lookup_color(name)
    if found:
        return color
    color = Gdk.RGBA()
    color.parse(fallback)
    return color


def update_note_colors(view: Gtk.TextView, buffer: Gtk.TextBuffer, manager) -> None:
    """색상 속성만 변경한다. 버퍼 내용·선택·수정 플래그에는 손대지 않는다."""
    context = view.get_style_context()
    dark = manager.get_dark()
    foreground = _color(context, "view_fg_color", "#ffffff" if dark else "#202020")
    link = _color(context, "accent_color", "#99c1f1" if dark else "#1a5fb4")
    # 고대비에서는 일반 본문 대비를 사용한다. 링크는 기존 밑줄로 구분한다.
    if manager.get_high_contrast():
        link = foreground
    code = Gdk.RGBA()
    code.red, code.green, code.blue = foreground.red, foreground.green, foreground.blue
    code.alpha = 0.18 if manager.get_high_contrast() else 0.08
    tags = buffer.get_tag_table()
    tags.lookup("stamp").set_property("foreground-rgba", link)
    tags.lookup("bullet").set_property("foreground-rgba", link)
    tags.lookup("quote").set_property("foreground-rgba", foreground)
    tags.lookup("code").set_property("background-rgba", code)
