"""클립 목록 창 — 담아 둔 구간을 보고, 고치고, 내보낸다.

플레이어와 같은 프로세스의 다른 창이다(자막 에디터와 같은 결).
위젯은 libadwaita 1.1 · GTK 4.6 범위만 쓴다 — 22.04 를 나중에 맞출 때 다시 쓰지 않으려고.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..log import get as get_logger  # noqa: E402
from .model import Clip, ClipList, fmt, fmt_span  # noqa: E402
from .probe import ffmpeg_available  # noqa: E402
from .runner import ExportJob, ExportRunner  # noqa: E402

log = get_logger("clip.dialog")


class ClipWindow(Adw.ApplicationWindow):
    """담은 클립 목록. 플레이어(parent)의 재생 위치와 소스를 가져다 쓴다."""

    def __init__(self, parent, clips: ClipList) -> None:
        super().__init__(application=parent.get_application(), transient_for=parent,
                         default_width=560, default_height=560, title="클립")
        self.player_window = parent
        self.clips = clips
        self.runner = ExportRunner(
            on_progress=lambda *a: GLib.idle_add(self._on_progress, *a),
            on_done=lambda r: GLib.idle_add(self._on_done, r),
            on_error=lambda m: GLib.idle_add(self._on_error, m),
        )
        self._chooser: Gtk.FileChooserNative | None = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        self._add_btn = Gtk.Button(label="현재 구간 담기")
        self._add_btn.connect("clicked", lambda *_: self._add_current())
        header.pack_start(self._add_btn)
        root.append(header)

        self._toasts = Adw.ToastOverlay()
        root.append(self._toasts)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
                       vexpand=True)
        self._toasts.set_child(body)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                 css_classes=["boxed-list"], valign=Gtk.Align.START)
        scroll.set_child(self._list)
        body.append(scroll)

        self._summary = Gtk.Label(xalign=0, css_classes=["dim-label"])
        body.append(self._summary)

        body.append(self._build_options())

        self._progress = Gtk.ProgressBar(show_text=True, visible=False)
        body.append(self._progress)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        self._cancel_btn = Gtk.Button(label="취소", visible=False)
        self._cancel_btn.connect("clicked", lambda *_: self.runner.cancel())
        actions.append(self._cancel_btn)
        self._export_btn = Gtk.Button(label="내보내기",
                                      css_classes=["suggested-action"])
        self._export_btn.connect("clicked", lambda *_: self._choose_output())
        actions.append(self._export_btn)
        body.append(actions)

        self.set_content(root)
        self.refresh()

    # ── 구성 ─────────────────────────────────────────────────────────────
    def _build_options(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        mode = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode.append(Gtk.Label(label="자르기", xalign=0, width_chars=7))
        self._fast = Gtk.CheckButton(label="빠르게")
        self._exact = Gtk.CheckButton(label="정확히", group=self._fast)
        self._fast.set_active(True)
        for button in (self._fast, self._exact):
            button.connect("toggled", lambda *_: self._sync_hint())
            mode.append(button)
        box.append(mode)

        join = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        join.append(Gtk.Label(label="결과", xalign=0, width_chars=7))
        self._join = Gtk.CheckButton(label="하나로 합치기")
        self._split = Gtk.CheckButton(label="조각별로 저장", group=self._join)
        self._join.set_active(True)
        join.append(self._join)
        join.append(self._split)
        box.append(join)

        self._hint = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        box.append(self._hint)
        return box

    # ── 목록 ─────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        for index, clip in enumerate(self.clips):
            self._list.append(self._row(index, clip))
        count = len(self.clips)
        self._summary.set_label(
            f"{count}개 · 모두 {fmt_span(self.clips.total_duration())}"
            if count else "담은 클립이 없다 — 재생 화면에서 K 를 누르면 담긴다")
        self._export_btn.set_sensitive(count > 0 and not self.runner.running)
        self._sync_hint()

    def _row(self, index: int, clip: Clip) -> Gtk.Widget:
        row = Gtk.ListBoxRow(activatable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)

        goto = Gtk.Button(label=fmt(clip.start), css_classes=["flat"],
                          tooltip_text="이 지점으로 이동")
        goto.connect("clicked", lambda *_, c=clip: self._goto(c))
        box.append(goto)

        span = Gtk.Label(label=f"~ {fmt(clip.end)} · {fmt_span(clip.duration)}",
                         css_classes=["dim-label"], width_chars=16, xalign=0)
        box.append(span)

        title = Gtk.Entry(text=clip.title, placeholder_text="제목(선택)", hexpand=True)
        title.connect("changed", lambda entry, c=clip: setattr(c, "title", entry.get_text()))
        box.append(title)

        for icon, delta, tip in (("go-up-symbolic", -1, "위로"),
                                 ("go-down-symbolic", 1, "아래로")):
            button = Gtk.Button(icon_name=icon, css_classes=["flat"], tooltip_text=tip)
            button.connect("clicked", lambda *_, i=index, d=delta: self._move(i, d))
            box.append(button)

        remove = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"],
                            tooltip_text="삭제")
        remove.connect("clicked", lambda *_, i=index: self._remove(i))
        box.append(remove)

        row.set_child(box)
        return row

    def _goto(self, clip: Clip) -> None:
        self.player_window.player.seek_absolute(clip.start)

    def _move(self, index: int, delta: int) -> None:
        self.clips.move(index, delta)
        self.refresh()

    def _remove(self, index: int) -> None:
        self.clips.remove(index)
        self.refresh()

    def _add_current(self) -> None:
        if self.player_window.add_clip():
            self.refresh()

    # ── 내보내기 ─────────────────────────────────────────────────────────
    def _sync_hint(self) -> None:
        if self.clips.empty:
            self._hint.set_label("")
            return
        if self._exact.get_active():
            job = self._job(Path("/tmp/x.mkv"))
            minutes = job.estimated_seconds() / 60
            span = f"{minutes:.0f}분" if minutes >= 1 else f"{job.estimated_seconds():.0f}초"
            self._hint.set_label(
                f"프레임 단위로 정확하다. 다시 인코딩하므로 대략 {span} 걸린다")
        else:
            self._hint.set_label(
                "즉시 끝난다. 시작·끝이 가까운 장면 경계로 조금 밀린다")

    def _job(self, output: Path) -> ExportJob:
        return ExportJob(
            source=Path(self.player_window.current_path),
            clips=list(self.clips),
            output=output,
            mode="encode" if self._exact.get_active() else "copy",
            join=self._join.get_active(),
            audio_track=self.player_window.current_audio_index(),
        )

    def _choose_output(self) -> None:
        if not ffmpeg_available():
            self._toast("ffmpeg 가 없다. `sudo apt install ffmpeg` 로 설치해라")
            return
        source = self.player_window.current_path
        if not source:
            self._toast("재생 중인 영상이 없다")
            return
        source = Path(source)
        chooser = Gtk.FileChooserNative(
            title="내보낼 위치", transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        chooser.set_current_name(f"{source.stem}-클립{source.suffix or '.mkv'}")
        chooser.connect("response", self._on_output_chosen)
        chooser.show()
        self._chooser = chooser          # 참조를 놓으면 대화상자가 바로 닫힌다

    def _on_output_chosen(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        target = None
        if response == Gtk.ResponseType.ACCEPT:
            gfile = chooser.get_file()
            target = gfile.get_path() if gfile is not None else None
        chooser.destroy()
        self._chooser = None
        if target:
            self._start(Path(target))

    def _start(self, output: Path) -> None:
        job = self._job(output)
        self._progress.set_fraction(0.0)
        self._progress.set_text("준비 중")
        self._progress.set_visible(True)
        self._cancel_btn.set_visible(True)
        self._export_btn.set_sensitive(False)
        if not self.runner.start(job):
            self._reset_progress()

    def _on_progress(self, seconds: float, total: float, step: str) -> None:
        self._progress.set_fraction(min(1.0, seconds / total) if total else 0.0)
        self._progress.set_text(f"{step} · {fmt_span(seconds)} / {fmt_span(total)}")
        return False

    def _on_done(self, result) -> None:
        self._reset_progress()
        if len(result.paths) == 1:
            self._toast(f"저장했다 — {result.paths[0].name}")
        else:
            self._toast(f"{len(result.paths)}개 파일로 저장했다")
        log.info("내보내기 완료: %s", ", ".join(p.name for p in result.paths))
        return False

    def _on_error(self, message: str) -> None:
        self._reset_progress()
        self._toast(message)
        return False

    def _reset_progress(self) -> None:
        self._progress.set_visible(False)
        self._cancel_btn.set_visible(False)
        self._export_btn.set_sensitive(not self.clips.empty)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))
