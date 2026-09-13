"""메인 창.

위젯은 **libadwaita 1.1 범위**를 기본으로 쓴다(scope §2-6). 26.04 에서도 같게 동작하므로
지금 비용이 없고, 나중에 22.04 를 맞출 때 이식 비용을 줄인다.
1.4+ API 를 불가피하게 쓰게 되면 그 자리에 `# ADW-1.4+` 주석을 단다.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .glarea import MpvGLArea  # noqa: E402
from .player import Player  # noqa: E402


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class BoraWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, default_width=960, default_height=560, title="Bora")

        self.player = Player()
        self._seeking = False          # 사용자가 슬라이더를 잡고 있는 동안은 갱신하지 않는다

        self._toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(root)
        self.set_content(self._toasts)

        root.append(self._build_header())
        self._video = MpvGLArea(self.player)
        root.append(self._video)
        root.append(self._build_controls())

        # 재생 위치는 폴링으로 갱신한다. mpv 의 time-pos 변화를 구독하면 초당 수십 번
        # 메인 루프로 넘어와 UI 가 불필요하게 바빠진다.
        GLib.timeout_add(250, self._tick)

        self.connect("close-request", self._on_close)

    # ── 구성 ─────────────────────────────────────────────────────────────
    def _build_header(self) -> Gtk.Widget:
        header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="Bora", subtitle="")
        header.set_title_widget(self._title)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="파일 열기")
        open_btn.connect("clicked", lambda *_: self.choose_file())
        header.pack_start(open_btn)

        self._status = Gtk.Label(label="", css_classes=["dim-label"])
        header.pack_end(self._status)
        return header

    def _build_controls(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)

        self._play_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        self._play_btn.connect("clicked", lambda *_: self.toggle_pause())
        box.append(self._play_btn)

        self._pos_label = Gtk.Label(label="--:--", width_chars=6)
        box.append(self._pos_label)

        self._seek = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True,
                               draw_value=False)
        self._seek.set_range(0, 1)
        self._seek.connect("change-value", self._on_seek)
        box.append(self._seek)

        self._dur_label = Gtk.Label(label="--:--", width_chars=6)
        box.append(self._dur_label)

        vol = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, width_request=100)
        vol.set_range(0, 100)
        vol.set_value(self.player.volume)
        vol.connect("value-changed", lambda s: setattr(self.player, "volume", s.get_value()))
        box.append(Gtk.Image(icon_name="audio-volume-high-symbolic"))
        box.append(vol)

        return box

    # ── 동작 ─────────────────────────────────────────────────────────────
    def open_path(self, path: Path | str) -> None:
        path = Path(path)
        self.player.open(path)
        self._title.set_title(path.name)
        self._title.set_subtitle(str(path.parent))

    def choose_file(self) -> None:
        # Gtk.FileDialog 는 4.10+ 라 22.04(GTK 4.6)에 없다. Native 선택기를 쓴다(scope §2-6).
        chooser = Gtk.FileChooserNative(title="영상 파일 열기", transient_for=self,
                                        action=Gtk.FileChooserAction.OPEN)
        chooser.connect("response", self._on_file_chosen)
        chooser.show()
        self._chooser = chooser      # 참조를 놓으면 대화상자가 바로 닫힌다

    def _on_file_chosen(self, chooser: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            gfile = chooser.get_file()
            if gfile is not None:
                self.open_path(gfile.get_path())
        chooser.destroy()
        self._chooser = None

    def toggle_pause(self) -> None:
        self.player.toggle_pause()
        self._sync_play_button()

    def toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))

    # ── 갱신 ─────────────────────────────────────────────────────────────
    def _sync_play_button(self) -> None:
        icon = "media-playback-start-symbolic" if self.player.paused else "media-playback-pause-symbolic"
        self._play_btn.set_icon_name(icon)

    def _on_seek(self, _scale, _scroll, value: float) -> bool:
        self.player.seek_absolute(value)
        return False

    def _tick(self) -> bool:
        duration = self.player.duration
        pos = self.player.time_pos
        if duration:
            self._seek.set_range(0, duration)
            self._dur_label.set_label(_fmt_time(duration))
        if pos is not None and not self._seeking:
            self._seek.set_value(pos)
            self._pos_label.set_label(_fmt_time(pos))
        self._sync_play_button()
        hw = self.player.hwdec_current
        self._status.set_label("" if hw == "no" else f"하드웨어 디코딩: {hw}")
        return True

    def _on_close(self, *_args) -> bool:
        self.player.close()
        return False
