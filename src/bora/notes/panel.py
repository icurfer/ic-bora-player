"""메모 패널 — 영상 옆에서 받아 적는다.

**타이핑 흐름을 끊지 않는 것이 최우선이다**(기획서 v0.3 §3-2). 사용자가 이 기능을 원한 이유가
"타이핑이 손글씨보다 빠르기 때문"이라, 일시정지·타임스탬프·저장이 전부 키보드로 끝나야 한다.

위젯은 libadwaita 1.1 범위만 쓴다. GtkSourceView 는 이 머신에 없어 쓰지 않는다(기획서 §8-1).
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..log import get as get_logger  # noqa: E402
from .model import NoteDocument, format_stamp, parse_stamps  # noqa: E402

log = get_logger("notes.panel")


class NotePanel(Gtk.Box):
    """우측 메모 패널. 플레이어 창(parent)의 재생 위치를 읽고 쓴다."""

    AUTOSAVE_MS = 2000          # 입력이 멈추고 이만큼 지나면 저장한다
    STAMP_TAG = "stamp"

    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                         width_request=320)
        self.window = window
        self.doc: NoteDocument | None = None
        self._save_id = 0
        self._loading = False

        self.append(self._build_toolbar())

        self._buffer = Gtk.TextBuffer()
        self._buffer.connect("changed", self._on_changed)
        self._buffer.create_tag(self.STAMP_TAG,
                                foreground="#7a5af8", underline=Pango.Underline.SINGLE)
        # 제목 줄(## ...)을 살짝 굵게 — 문법 강조는 이 정도만 한다(의존성을 늘리지 않는다)
        self._buffer.create_tag("heading", weight=Pango.Weight.BOLD)

        self._view = Gtk.TextView(
            buffer=self._buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=False,
            top_margin=10, bottom_margin=120, left_margin=10, right_margin=10,
        )
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self._view.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self._view.add_controller(motion)

        scroll = Gtk.ScrolledWindow(child=self._view, vexpand=True, hexpand=True)
        self.append(scroll)
        self.append(self._build_status())

    # ── 구성 ─────────────────────────────────────────────────────────────
    def _build_toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_top=8, margin_bottom=6, margin_start=10, margin_end=10)
        stamp = Gtk.Button(icon_name="document-open-recent-symbolic",
                           tooltip_text="현재 시각 넣기 (Ctrl+T)")
        stamp.connect("clicked", lambda *_: self.insert_stamp())
        bar.append(stamp)

        shot = Gtk.Button(icon_name="camera-photo-symbolic",
                          tooltip_text="화면 넣기 (Ctrl+Shift+S)")
        shot.connect("clicked", lambda *_: self.insert_screenshot())
        bar.append(shot)

        bar.append(Gtk.Label(hexpand=True))

        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="저장 (Ctrl+S)")
        save.connect("clicked", lambda *_: self.save(force=True))
        bar.append(save)

        close = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="메모 닫기 (Ctrl+M)")
        close.connect("clicked", lambda *_: self.window.toggle_notes(False))
        bar.append(close)
        return bar

    def _build_status(self) -> Gtk.Widget:
        self._status = Gtk.Label(xalign=0, margin_start=10, margin_end=10, margin_bottom=6,
                                 css_classes=["dim-label"], ellipsize=Pango.EllipsizeMode.MIDDLE)
        return self._status

    # ── 문서 ─────────────────────────────────────────────────────────────
    def load_for(self, video: Path, title: str = "") -> None:
        """영상이 바뀌면 부른다. 쓰던 메모는 먼저 저장한다."""
        self.save()
        self.doc = NoteDocument.load_for(video, title)
        self._loading = True
        self._buffer.set_text(self.doc.text)
        self._loading = False
        self._retag()
        self._update_status("열림")
        # 이어 쓰기 좋게 끝으로 보낸다
        self._buffer.place_cursor(self._buffer.get_end_iter())

    def _text(self) -> str:
        start, end = self._buffer.get_bounds()
        return self._buffer.get_text(start, end, False)

    def save(self, force: bool = False) -> bool:
        if self.doc is None:
            return False
        self._cancel_autosave()
        self.doc.text = self._text()
        if not force and not self.doc.dirty:
            return False
        if self.doc.changed_outside():
            # 밖에서 고친 것을 말없이 덮지 않는다.
            self._update_status("파일이 밖에서 바뀌었다 — 저장 버튼을 눌러야 덮어쓴다")
            if not force:
                return False
        try:
            saved = self.doc.save()
        except OSError as exc:
            log.warning("메모 저장 실패: %s", exc)
            self._update_status(f"저장 실패: {exc}")
            self.window.toast(f"메모를 저장하지 못했다: {exc}")
            return False
        if saved:
            self._update_status("저장됨")
        return saved

    # ── 편집 ─────────────────────────────────────────────────────────────
    def insert_stamp(self) -> None:
        """현재 재생 위치를 제목으로 넣는다. 재생은 건드리지 않는다."""
        if self.doc is None:
            return
        seconds = self.window.player.time_pos
        text = self.doc.heading_for(seconds)
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        # 줄 중간이면 줄을 바꾸고 넣는다
        if not cursor.starts_line():
            self._buffer.insert(cursor, "\n")
            cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        self._buffer.insert(cursor, text)
        self._view.grab_focus()
        self._retag()

    def insert_screenshot(self) -> None:
        if self.doc is None or self.window._current is None:
            return
        assets = NoteDocument.assets_dir_for(self.window._current)
        name = f"{format_stamp(self.window.player.time_pos).strip('[]').replace(':', '')}.png"
        try:
            path = self.window.player.screenshot(assets / name, include_subs=True)
        except Exception as exc:
            self.window.toast(f"화면을 저장하지 못했다: {exc}")
            return
        rel = f"{assets.name}/{path.name}"
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        self._buffer.insert(cursor, f"\n![{format_stamp(self.window.player.time_pos)}]({rel})\n")
        self._retag()

    def _on_changed(self, _buffer) -> None:
        if self._loading or self.doc is None:
            return
        self._retag()
        self._update_status("편집 중")
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        self._cancel_autosave()
        self._save_id = GLib.timeout_add(self.AUTOSAVE_MS, self._autosave)

    def _cancel_autosave(self) -> None:
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0

    def _autosave(self) -> bool:
        self._save_id = 0
        self.save()
        return False

    # ── 타임스탬프 ───────────────────────────────────────────────────────
    def _retag(self) -> None:
        """타임스탬프와 제목 줄에 태그를 다시 입힌다."""
        text = self._text()
        start, end = self._buffer.get_bounds()
        self._buffer.remove_tag_by_name(self.STAMP_TAG, start, end)
        self._buffer.remove_tag_by_name("heading", start, end)

        for stamp in parse_stamps(text):
            a = self._buffer.get_iter_at_offset(stamp.start)
            b = self._buffer.get_iter_at_offset(stamp.end)
            self._buffer.apply_tag_by_name(self.STAMP_TAG, a, b)

        offset = 0
        for line in text.split("\n"):
            if line.startswith("#"):
                a = self._buffer.get_iter_at_offset(offset)
                b = self._buffer.get_iter_at_offset(offset + len(line))
                self._buffer.apply_tag_by_name("heading", a, b)
            offset += len(line) + 1

    def _stamp_at(self, x: float, y: float):
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, it = self._view.get_iter_at_location(bx, by)
        if not found:
            return None
        offset = it.get_offset()
        for stamp in parse_stamps(self._text()):
            if stamp.start <= offset < stamp.end:
                return stamp
        return None

    def _on_click(self, _gesture, n_press: int, x: float, y: float) -> None:
        stamp = self._stamp_at(x, y)
        if stamp is None:
            return
        self.window.player.seek_absolute(stamp.seconds)
        self.window.toast(f"{format_stamp(stamp.seconds)} 로 이동")
        log.debug("타임스탬프 이동: %.1fs", stamp.seconds)

    def _on_motion(self, _controller, x: float, y: float) -> None:
        cursor = "pointer" if self._stamp_at(x, y) else "text"
        self._view.set_cursor(Gdk.Cursor.new_from_name(cursor, None))

    # ── 상태 ─────────────────────────────────────────────────────────────
    def _update_status(self, note: str) -> None:
        if self.doc is None:
            self._status.set_label("")
            return
        self._status.set_label(f"{self.doc.path.name} · {note}")

    def focus_editor(self) -> None:
        self._view.grab_focus()
