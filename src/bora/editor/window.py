"""자막 에디터 창.

플레이어와 **같은 프로세스, 다른 창**이다. 재생 위치를 바로 읽고 쓸 수 있고,
영상 위에 얹지 않아 전체화면에서도 방해되지 않는다(기획서 v0.2 §4).

위젯은 libadwaita 1.1 범위만 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..log import get as get_logger  # noqa: E402
from ..subtitle.model import SubtitleDocument, ms_to_srt, srt_to_ms  # noqa: E402
from ..subtitle.writer import save_srt, target_path  # noqa: E402

log = get_logger("editor")


class EditorWindow(Adw.ApplicationWindow):
    """자막 한 파일을 편집한다. 플레이어(parent)의 재생 위치를 가져다 쓴다."""

    def __init__(self, parent, document: SubtitleDocument,
                 save_to: Path | None = None) -> None:
        super().__init__(application=parent.get_application(), transient_for=parent,
                         default_width=560, default_height=620, title="자막 편집")
        self.player_window = parent
        self.doc = document
        # 읽은 곳과 저장할 곳이 다를 수 있다 — 분리 트랙은 캐시에서 읽고 영상 옆에 저장한다.
        self.save_to = Path(save_to) if save_to else (
            target_path(document.source) if document.source else None)
        self.index = 0
        self._syncing = False           # 위젯 갱신 중에 콜백이 되먹임하지 않게

        self._toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(root)
        self.set_content(self._toasts)

        root.append(self._build_header())
        root.append(self._build_current_cue())
        root.append(self._build_bulk())
        root.append(self._build_list())

        self.follow_playback()

    # ── 구성 ─────────────────────────────────────────────────────────────
    def _build_header(self) -> Gtk.Widget:
        header = Adw.HeaderBar()
        name = self.save_to.name if self.save_to else "(새 자막)"
        self._title = Adw.WindowTitle(title="자막 편집", subtitle=name)
        header.set_title_widget(self._title)

        save = Gtk.Button(label="저장", css_classes=["suggested-action"])
        save.connect("clicked", lambda *_: self.save())
        header.pack_end(save)

        self._undo_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="되돌리기",
                                    sensitive=False)
        self._undo_btn.connect("clicked", lambda *_: self.undo())
        header.pack_start(self._undo_btn)
        return header

    def _build_current_cue(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=12, margin_bottom=8, margin_start=12, margin_end=12)

        self._where = Gtk.Label(xalign=0, css_classes=["dim-label"])
        box.append(self._where)

        # 시각 — 직접 입력도 되고, 현재 재생 위치를 박을 수도 있다
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._start_entry = Gtk.Entry(max_width_chars=13, tooltip_text="시작 (00:00:00,000)")
        self._start_entry.connect("activate", lambda *_: self._commit_time("start"))
        start_now = Gtk.Button(icon_name="media-playback-start-symbolic",
                               tooltip_text="현재 재생 위치를 시작으로 (I)")
        start_now.connect("clicked", lambda *_: self.stamp("start"))
        times.append(Gtk.Label(label="시작"))
        times.append(self._start_entry)
        times.append(start_now)

        self._end_entry = Gtk.Entry(max_width_chars=13, tooltip_text="끝 (00:00:00,000)")
        self._end_entry.connect("activate", lambda *_: self._commit_time("end"))
        end_now = Gtk.Button(icon_name="media-playback-stop-symbolic",
                             tooltip_text="현재 재생 위치를 끝으로 (O)")
        end_now.connect("clicked", lambda *_: self.stamp("end"))
        times.append(Gtk.Label(label="끝", margin_start=8))
        times.append(self._end_entry)
        times.append(end_now)
        box.append(times)

        self._text_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                       top_margin=6, bottom_margin=6,
                                       left_margin=6, right_margin=6)
        self._text_view.get_buffer().connect("changed", self._on_text_changed)
        frame = Gtk.Frame(child=self._text_view, height_request=80)
        box.append(frame)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prev_btn = Gtk.Button(label="이전 줄")
        prev_btn.connect("clicked", lambda *_: self.select(self.index - 1))
        next_btn = Gtk.Button(label="다음 줄")
        next_btn.connect("clicked", lambda *_: self.select(self.index + 1))
        jump = Gtk.Button(label="이 줄로 이동", tooltip_text="영상을 이 큐 시작으로 보낸다")
        jump.connect("clicked", lambda *_: self.seek_to_cue())
        follow = Gtk.Button(label="현재 자막 잡기", tooltip_text="재생 위치의 큐를 고른다")
        follow.connect("clicked", lambda *_: self.follow_playback())
        for w in (prev_btn, next_btn, jump, follow):
            nav.append(w)
        box.append(nav)
        return box

    def _build_bulk(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_start=12, margin_end=12, margin_bottom=8)
        box.append(Gtk.Label(label="밀기(초)"))
        adj = Gtk.Adjustment(value=-2.0, lower=-600, upper=600, step_increment=0.1,
                             page_increment=1)
        self._shift_spin = Gtk.SpinButton(adjustment=adj, digits=1, numeric=True)
        box.append(self._shift_spin)

        from_here = Gtk.Button(label="이 줄부터 뒤로")
        from_here.set_tooltip_text("중간부터 어긋나는 자막에 쓴다")
        from_here.connect("clicked", lambda *_: self.shift(from_current=True))
        box.append(from_here)

        whole = Gtk.Button(label="전체")
        whole.connect("clicked", lambda *_: self.shift(from_current=False))
        box.append(whole)

        take_delay = Gtk.Button(label="싱크값 가져오기")
        take_delay.set_tooltip_text("플레이어에서 맞춰 둔 자막 싱크를 밀기 값으로 가져온다")
        take_delay.connect("clicked", lambda *_: self.take_player_delay())
        box.append(take_delay)
        return box

    def _build_list(self) -> Gtk.Widget:
        self._store = Gtk.StringList()
        self._list = Gtk.ListBox(css_classes=["boxed-list"])
        self._list.connect("row-selected", self._on_row_selected)
        scroll = Gtk.ScrolledWindow(vexpand=True, margin_start=12, margin_end=12,
                                    margin_bottom=12, child=self._list)
        self._reload_list()
        return scroll

    def _reload_list(self) -> None:
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        for i, cue in enumerate(self.doc.cues):
            first = cue.text.splitlines()[0] if cue.text else ""
            label = Gtk.Label(xalign=0, margin_top=6, margin_bottom=6,
                              margin_start=8, margin_end=8,
                              label=f"{i + 1}. {ms_to_srt(cue.start_ms)}  {first[:40]}")
            self._list.append(label)

    # ── 동작 ─────────────────────────────────────────────────────────────
    @property
    def player(self):
        return self.player_window.player

    def position_ms(self) -> int:
        return int((self.player.time_pos or 0) * 1000)

    def follow_playback(self) -> None:
        """지금 재생 위치의 큐를 고른다. 없으면 직전 큐."""
        index = self.doc.cue_at(self.position_ms())
        if index is None:
            self.toast("자막이 비어 있다")
            return
        self.select(index)

    def select(self, index: int) -> None:
        if not self.doc.cues:
            return
        self.index = max(0, min(len(self.doc.cues) - 1, index))
        self._sync_widgets()

    def _sync_widgets(self) -> None:
        cue = self.doc.cues[self.index]
        self._syncing = True
        self._start_entry.set_text(ms_to_srt(cue.start_ms))
        self._end_entry.set_text(ms_to_srt(cue.end_ms))
        self._text_view.get_buffer().set_text(cue.text)
        self._syncing = False
        self._where.set_label(
            f"{self.index + 1} / {len(self.doc.cues)} 번째 줄 · 길이 {cue.duration_ms / 1000:.1f}초"
            f" · 재생 위치 {ms_to_srt(self.position_ms())}")
        self._undo_btn.set_sensitive(self.doc.can_undo())
        row = self._list.get_row_at_index(self.index)
        if row is not None:
            self._list.select_row(row)

    def stamp(self, which: str) -> None:
        """지금 재생 위치를 이 큐의 시작 또는 끝으로 박는다 — 이 에디터의 핵심."""
        if not self.doc.cues:
            return
        ms = self.position_ms()
        if which == "start":
            self.doc.set_start(self.index, ms)
        else:
            self.doc.set_end(self.index, ms)
        self._after_edit(f"{'시작' if which == 'start' else '끝'}을 {ms_to_srt(ms)} 으로")

    def _commit_time(self, which: str) -> None:
        entry = self._start_entry if which == "start" else self._end_entry
        try:
            ms = srt_to_ms(entry.get_text())
        except ValueError as exc:
            self.toast(str(exc))
            self._sync_widgets()            # 잘못된 값은 되돌린다
            return
        if which == "start":
            self.doc.set_start(self.index, ms)
        else:
            self.doc.set_end(self.index, ms)
        self._after_edit("시각 수정")

    def _on_text_changed(self, buffer: Gtk.TextBuffer) -> None:
        if self._syncing or not self.doc.cues:
            return
        start, end = buffer.get_bounds()
        self.doc.cues[self.index].text = buffer.get_text(start, end, False)
        self.doc.dirty = True

    def shift(self, from_current: bool) -> None:
        delta = int(self._shift_spin.get_value() * 1000)
        if from_current:
            self.doc.shift_from(self.index, delta)
            what = f"{self.index + 1}번째 줄부터"
        else:
            self.doc.shift_all(delta)
            what = "전체"
        self._after_edit(f"{what} {delta / 1000:+.1f}초 밀기")

    def take_player_delay(self) -> None:
        """플레이어에서 맞춰 둔 sub-delay 를 밀기 값으로 가져온다.

        delay 는 파일 시각에 얹히는 별도 오프셋이라, 파일에 굳히면 delay 는 0 으로 되돌려야
        두 번 밀리지 않는다(기획서 v0.2 §8-1 실측).
        """
        delay = self.player.sub_delay
        if abs(delay) < 0.001:
            self.toast("플레이어 자막 싱크가 0이다")
            return
        self._shift_spin.set_value(delay)
        self.toast(f"싱크 {delay:+.1f}초를 가져왔다. 밀기를 누르면 파일에 반영된다")

    def seek_to_cue(self) -> None:
        if self.doc.cues:
            self.player.seek_absolute(self.doc.cues[self.index].start_ms / 1000)

    def undo(self) -> None:
        if self.doc.undo():
            self._after_edit("되돌렸다", snapshot=False)

    def _after_edit(self, message: str, snapshot: bool = True) -> None:
        self._reload_list()
        self._sync_widgets()
        self.toast(message)

    def _on_row_selected(self, _list, row) -> None:
        if row is not None and row.get_index() != self.index:
            self.select(row.get_index())

    # ── 저장 ─────────────────────────────────────────────────────────────
    def save(self) -> None:
        if self.save_to is None:
            self.toast("저장할 곳이 없다")
            return
        try:
            dest, backup = save_srt(self.doc.to_srt(), self.save_to, self.save_to)
        except OSError as exc:
            log.exception("자막 저장 실패")
            self.toast(f"저장 실패: {exc}")
            return
        self.doc.dirty = False
        note = f"저장: {dest.name}" + (f" (백업 {backup.name})" if backup else "")
        self.toast(note)
        # 저장한 파일을 플레이어에 다시 물려 방금 고친 결과가 화면에 바로 보이게 한다.
        self.player_window.reload_subtitle(dest)

    def toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))
        log.debug("에디터: %s", text)
