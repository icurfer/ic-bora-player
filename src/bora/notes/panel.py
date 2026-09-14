"""메모 패널 — 영상 옆에서 받아 적는다.

**타이핑 흐름을 끊지 않는 것이 최우선이다**(기획서 v0.3 §3-2). 사용자가 이 기능을 원한 이유가
"타이핑이 손글씨보다 빠르기 때문"이라, 일시정지·타임스탬프·저장이 전부 키보드로 끝나야 한다.

위젯은 libadwaita 1.1 범위만 쓴다. GtkSourceView 는 이 머신에 없어 쓰지 않는다(기획서 §8-1).
"""

from __future__ import annotations

import re
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
        self._last_line = -1

        self.append(self._build_toolbar())

        self._buffer = Gtk.TextBuffer()
        self._buffer.connect("changed", self._on_changed)
        self._buffer.connect("mark-set", self._on_mark_set)
        self._make_tags()

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
        """버퍼의 **원본** 내용.

        ⚠ 세 번째 인자(`include_hidden_chars`)는 반드시 True 여야 한다. 라이브 프리뷰가
           마크업 문자(`#`, `**`)에 invisible 태그를 붙이는데, False 로 읽으면 **그 문자가
           빠진 채로 돌아온다** — 그대로 저장하면 파일에서 `#` 이 사라진다(실제로 겪었다).
           보이는 것만 바뀌어야 하고 파일 내용은 절대 손대지 않는다.
        """
        start, end = self._buffer.get_bounds()
        return self._buffer.get_text(start, end, True)

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

    def append_pin(self, start: float, end: float | None = None, label: str = "") -> bool:
        """핀을 메모 끝에 한 줄로 남긴다.

        패널이 닫혀 있어도 남겨야 한다 — 나중에 열었을 때 핀과 메모가 따로 놀면
        되돌아볼 때 둘을 맞춰 봐야 한다. 문서가 아직 없으면 지금 연다.
        """
        if self.doc is None:
            if self.window._current is None:
                return False
            self.load_for(self.window._current, self.window._current.stem)
        line = self.doc.pin_heading(start, end, label)

        end_iter = self._buffer.get_end_iter()
        prefix = "" if end_iter.starts_line() else "\n"
        self._buffer.insert(end_iter, prefix + line)
        # 커서를 그 줄 끝에 둔다 — 패널이 열려 있으면 바로 제목을 칠 수 있다.
        self._buffer.place_cursor(self._buffer.get_end_iter())
        self._retag()
        # 패널이 닫혀 있으면 자동 저장 타이머가 돌 일이 없다. 바로 저장한다.
        if not self.get_visible():
            self.save()
        else:
            self._schedule_autosave()
        log.debug("핀을 메모에 남겼다: %s", line.strip())
        return True

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

    # ── 라이브 프리뷰 ────────────────────────────────────────────────────
    # `#` 같은 마크업 문자를 그대로 보여 주면 메모하기 불편하다. 커서가 없는 줄은
    # 마크업을 **감추고** 스타일만 보여 주고, 커서가 간 줄은 원본을 드러낸다
    # (Obsidian 의 라이브 프리뷰와 같은 방식). 파일 내용은 손대지 않는다 — 보이는 것만 다르다.
    HEADING_SCALES = {1: 1.7, 2: 1.35, 3: 1.15, 4: 1.05, 5: 1.0, 6: 1.0}
    _INLINE = (
        ("bold", re.compile(r"(\*\*)(?!\s)(.+?)(?<!\s)(\*\*)")),
        ("italic", re.compile(r"(?<!\*)(\*)(?!\s|\*)(.+?)(?<!\s|\*)(\*)(?!\*)")),
        ("code", re.compile(r"(`)([^`\n]+)(`)")),
        ("strike", re.compile(r"(~~)(.+?)(~~)")),
    )
    _BULLET = re.compile(r"^(\s*)([-*+])(\s+)")
    _QUOTE = re.compile(r"^(>\s?)")

    def _make_tags(self) -> None:
        b = self._buffer
        b.create_tag(self.STAMP_TAG, foreground="#7a5af8",
                     underline=Pango.Underline.SINGLE)
        b.create_tag("hidden", invisible=True)          # 마크업 문자를 감춘다
        for level, scale in self.HEADING_SCALES.items():
            b.create_tag(f"h{level}", scale=scale, weight=Pango.Weight.BOLD,
                         pixels_above_lines=10, pixels_below_lines=4)
        b.create_tag("bold", weight=Pango.Weight.BOLD)
        b.create_tag("italic", style=Pango.Style.ITALIC)
        b.create_tag("code", family="monospace", background="#00000014")
        b.create_tag("strike", strikethrough=True)
        b.create_tag("quote", style=Pango.Style.ITALIC, foreground="#6b7280",
                     left_margin=28)
        b.create_tag("bullet", foreground="#7a5af8", weight=Pango.Weight.BOLD)

    def _cursor_line(self) -> int:
        it = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        return it.get_line()

    def _hide(self, start: int, end: int) -> None:
        """마크업 문자를 감춘다. 길이가 0이면 아무 일도 하지 않는다."""
        if end <= start:
            return
        a = self._buffer.get_iter_at_offset(start)
        b = self._buffer.get_iter_at_offset(end)
        self._buffer.apply_tag_by_name("hidden", a, b)

    def _style(self, name: str, start: int, end: int) -> None:
        if end <= start:
            return
        a = self._buffer.get_iter_at_offset(start)
        b = self._buffer.get_iter_at_offset(end)
        self._buffer.apply_tag_by_name(name, a, b)

    def _retag(self) -> None:
        """전체를 다시 칠한다. 커서가 있는 줄만 마크업을 드러낸다."""
        text = self._text()
        start, end = self._buffer.get_bounds()
        for name in ("hidden", "bold", "italic", "code", "strike", "quote", "bullet",
                     self.STAMP_TAG, *[f"h{i}" for i in self.HEADING_SCALES]):
            self._buffer.remove_tag_by_name(name, start, end)

        editing = self._cursor_line()
        offset = 0
        for lineno, line in enumerate(text.split("\n")):
            reveal = (lineno == editing)        # 편집 중인 줄은 원본을 보여 준다
            self._retag_line(line, offset, reveal)
            offset += len(line) + 1

        # 타임스탬프는 어느 줄이든 늘 표시한다 — 클릭 대상이기 때문이다.
        for stamp in parse_stamps(text):
            self._style(self.STAMP_TAG, stamp.start, stamp.end)

    def _retag_line(self, line: str, base: int, reveal: bool) -> None:
        body_start = base

        heading = re.match(r"^(#{1,6})(\s+)", line)
        if heading:
            level = len(heading.group(1))
            marks = heading.end()
            self._style(f"h{level}", base, base + len(line))
            if not reveal:
                self._hide(base, base + marks)
            body_start = base + marks
        else:
            quote = self._QUOTE.match(line)
            if quote:
                self._style("quote", base, base + len(line))
                if not reveal:
                    self._hide(base, base + quote.end())
                body_start = base + quote.end()
            else:
                bullet = self._BULLET.match(line)
                if bullet:
                    # 목록 기호는 감추지 않는다 — 파일에 그대로 있어야 하고, 보이는 편이 낫다.
                    self._style("bullet", base + len(bullet.group(1)),
                                base + len(bullet.group(1)) + 1)
                    body_start = base + bullet.end()

        for name, pattern in self._INLINE:
            for m in pattern.finditer(line):
                if base + m.start() < body_start:
                    continue
                self._style(name, base + m.start(2), base + m.end(2))
                if not reveal:
                    self._hide(base + m.start(1), base + m.end(1))
                    self._hide(base + m.start(3), base + m.end(3))

    def _on_mark_set(self, _buffer, _iter, mark: Gtk.TextMark) -> None:
        """커서가 다른 줄로 가면 다시 칠한다 — 편집 중인 줄만 원본을 드러내야 한다."""
        if self._loading or mark.get_name() != "insert":
            return
        line = self._cursor_line()
        if line == self._last_line:
            return
        self._last_line = line
        # 태그 변경이 mark-set 안에서 일어나면 커서가 흔들린다. 한 박자 뒤로 미룬다.
        GLib.idle_add(self._retag_idle)

    def _retag_idle(self) -> bool:
        if not self._loading:
            self._retag()
        return False

    # ── 타임스탬프 ───────────────────────────────────────────────────────

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
        if stamp.is_range:
            # `[A] ~ [B]` 표기를 누르면 그 구간을 반복한다 — 핀에서 넣은 구간이다.
            self.window.player.set_loop(stamp.seconds, stamp.range_end)
            self.window.player.seek_absolute(stamp.seconds)
            self.window._sync_loop_button()
            self.window.toast(
                f"구간 반복 {format_stamp(stamp.seconds)} ~ {format_stamp(stamp.range_end)}")
            log.debug("메모에서 구간 반복: %.1f ~ %.1f", stamp.seconds, stamp.range_end)
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
