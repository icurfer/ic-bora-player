"""Adw.Application — 창 하나를 띄우고 명령행으로 받은 파일을 연다."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from . import APP_ID  # noqa: E402
from .window import BoraWindow  # noqa: E402


class BoraApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._pending: list[Path] = []

    def do_activate(self) -> None:
        window = self.props.active_window or BoraWindow(self)
        window.present()
        if self._pending:
            paths, self._pending = self._pending, []
            self._open_in(window, paths)

    def do_open(self, files, n_files: int, _hint: str) -> None:
        self._pending = [Path(f.get_path()) for f in files[:n_files] if f.get_path()]
        self.do_activate()

    @staticmethod
    def _open_in(window: BoraWindow, paths: list[Path]) -> None:
        if not paths:
            return
        # 인자가 둘 이상이면 두 번째는 자막으로 본다 (research 4 §4 — 포털이 영상과 자막을
        # 서로 다른 디렉터리에 노출하므로 sub-auto 로는 찾지 못한다).
        subtitle = paths[1] if len(paths) > 1 else None
        window.open_path(paths[0], subtitle)
