"""libmpv 가 그리는 GtkGLArea.

`set_auto_render(False)` 로 두고, libmpv 가 "새 프레임 있다"고 알릴 때만 다시 그린다.
research 3 의 스파이크에서 이 구조로 1080p 드랍 0 을 확인했다.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .player import Player  # noqa: E402
from .util.gl import current_fbo  # noqa: E402


class MpvGLArea(Gtk.GLArea):
    def __init__(self, player: Player) -> None:
        super().__init__(hexpand=True, vexpand=True)
        self._player = player
        self._ready = False
        self.set_auto_render(False)
        self.connect("realize", self._on_realize)
        self.connect("render", self._on_render)
        self.connect("resize", self._on_resize)
        self.connect("unrealize", self._on_unrealize)

    def _on_realize(self, area: Gtk.GLArea) -> None:
        area.make_current()
        if area.get_error() is not None:
            return
        self._player.attach_render_context(self._request_render)
        self._ready = True

    def _request_render(self) -> None:
        # libmpv 스레드에서 불린다. GTK 를 직접 건드리면 안 되므로 메인 루프로 넘긴다.
        GLib.idle_add(self.queue_render, priority=GLib.PRIORITY_HIGH)

    def _on_render(self, area: Gtk.GLArea, _ctx) -> bool:
        if not self._ready:
            return True
        scale = area.get_scale_factor()
        self._player.render(area.get_width() * scale, area.get_height() * scale, current_fbo())
        return True

    def _on_resize(self, _area: Gtk.GLArea, _w: int, _h: int) -> None:
        """크기가 바뀌면 즉시 다시 그린다.

        `set_auto_render(False)` 라 GTK 가 알아서 다시 그려 주지 않는다. libmpv 는 '새 프레임이
        있을 때만' update_cb 를 부르므로, 일시정지 중이거나 프레임 사이에 창 크기가 바뀌면
        **검은 화면이 그대로 남는다.** 전체화면을 오갈 때 실제로 이 증상이 났다.
        """
        if self._ready:
            self.queue_render()

    def _on_unrealize(self, _area: Gtk.GLArea) -> None:
        self._ready = False
