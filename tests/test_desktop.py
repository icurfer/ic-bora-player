# -*- coding: utf-8 -*-
"""기본 영상 플레이어 설정 로직 테스트.

⚠ **실제 시스템 기본값을 바꾸지 않는다.** 사용자 환경을 건드리는 테스트는 만들면 안 된다.
   GIO 호출을 가짜로 갈아 끼워 '무엇을 고르는가' 만 검증한다.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora import desktop  # noqa: E402


class FakeApp:
    def __init__(self, app_id: str, log: list) -> None:
        self._id = app_id
        self._log = log

    def get_id(self) -> str:
        return self._id

    def set_as_default_for_type(self, mime: str) -> None:
        self._log.append((self._id, mime))


@pytest.fixture
def fake(monkeypatch):
    """가짜 GIO 환경. 기록된 호출을 돌려준다."""
    calls: list = []
    state = {"defaults": {m: "vlc_vlc.desktop" for m in desktop.VIDEO_TYPES}}

    monkeypatch.setattr(desktop, "app_info",
                        lambda: FakeApp(desktop.APP_DESKTOP_ID, calls))
    monkeypatch.setattr(desktop, "current_default",
                        lambda mime: state["defaults"].get(mime, ""))
    monkeypatch.setattr(desktop, "_candidates",
                        lambda mime: [FakeApp("vlc_vlc.desktop", calls),
                                      FakeApp("org.gnome.Totem.desktop", calls)])
    return calls, state


def test_enable_sets_bora_for_every_type(fake) -> None:
    calls, _ = fake
    ok, message = desktop.set_default(True)
    assert ok and "Bora" in message
    assert {mime for _id, mime in calls} == set(desktop.VIDEO_TYPES)
    assert all(app_id == desktop.APP_DESKTOP_ID for app_id, _ in calls)


def test_snapshot_records_previous(fake) -> None:
    _calls, _state = fake
    snapshot = desktop.snapshot_defaults()
    assert snapshot["video/mp4"] == "vlc_vlc.desktop"
    assert desktop.APP_DESKTOP_ID not in snapshot.values()


def test_disable_restores_remembered_app(fake) -> None:
    """끄면 기억해 둔 앱으로 정확히 돌아간다."""
    calls, _ = fake
    remembered = {m: "org.gnome.Totem.desktop" for m in desktop.VIDEO_TYPES}
    ok, _message = desktop.set_default(False, remembered)
    assert ok
    assert all(app_id == "org.gnome.Totem.desktop" for app_id, _ in calls)


def test_disable_without_memory_falls_back(fake) -> None:
    """기억이 없으면 다른 후보 중 하나로 되돌린다 — Bora 로 남겨 두지 않는다."""
    calls, _ = fake
    ok, _message = desktop.set_default(False, {})
    assert ok
    assert all(app_id != desktop.APP_DESKTOP_ID for app_id, _ in calls)


def test_enable_without_desktop_file_fails_clearly(monkeypatch) -> None:
    monkeypatch.setattr(desktop, "app_info", lambda: None)
    ok, message = desktop.set_default(True)
    assert not ok
    assert "install-desktop" in message


def test_is_default_checks_main_types(monkeypatch) -> None:
    monkeypatch.setattr(desktop, "current_default", lambda m: desktop.APP_DESKTOP_ID)
    assert desktop.is_default() is True
    monkeypatch.setattr(desktop, "current_default",
                        lambda m: "vlc_vlc.desktop" if m == "video/mp4" else desktop.APP_DESKTOP_ID)
    assert desktop.is_default() is False
