# -*- coding: utf-8 -*-
"""타임라인 그리기 회귀 테스트 — 창 없이 픽셀을 본다.

**왜 이 방식인가**: GUI 시나리오는 백그라운드로 띄운 창이 매핑되지 않아 위젯 폭이 0 이고
`draw` 가 한 번도 불리지 않는다. 그려지는 것은 확인할 방법이 없었다
(`.claude/memory/project_gui_verification_blind_spots.md`).

`Gtk.DrawingArea` 의 draw 함수는 결국 cairo 컨텍스트 하나를 받을 뿐이므로,
`ImageSurface` 에 직접 호출해 픽셀을 검사하면 창 없이도 볼 수 있다.
실제로 "선택한 구간 표시가 보이지 않는다"를 이 방법으로 잡았다 — 테두리는 그려지고
있었지만 1~2px 뿐이라 필름스트립 위에서 묻혔다.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

cairo = pytest.importorskip("cairo")
gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")

from bora.clip.model import Timeline  # noqa: E402
from bora.clip.timeline import (  # noqa: E402
    STRIP_HEIGHT, STRIP_TOP, TOTAL_HEIGHT, TimelineView,
)

WIDTH = 600
MIDDLE_Y = STRIP_TOP + STRIP_HEIGHT // 2


def _view(duration=300.0, cuts=(100.0, 200.0)):
    view = TimelineView()
    view.model = Timeline(duration)
    for at in cuts:
        view.model.split(at)
    view.view_start, view.view_end = 0.0, duration
    # 위젯이 매핑되지 않아도 좌표 변환이 돌게 크기를 고정한다
    view.get_width = lambda: WIDTH
    view.get_height = lambda: TOTAL_HEIGHT
    return view


def _render(view):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, TOTAL_HEIGHT)
    view._draw(None, cairo.Context(surface), WIDTH, TOTAL_HEIGHT)
    return surface


def _pixel(surface, x, y):
    data, stride = surface.get_data(), surface.get_stride()
    blue, green, red, _alpha = data[y * stride + x * 4: y * stride + x * 4 + 4]
    return (red, green, blue)


def _blueness(colour):
    """파랑이 빨강보다 얼마나 앞서나 — 선택 강조는 파란 계열이다."""
    red, _green, blue = colour
    return blue - red


def test_selection_is_visibly_different() -> None:
    """이게 실제 버그였다 — 테두리는 그려졌지만 눈에 띄지 않았다."""
    view = _view()
    view.selected = -1
    plain = _render(view)
    view.selected = 1                       # 100~200초 구간 (x 200~400)
    chosen = _render(view)

    # 위쪽 손잡이가 생긴다
    handle_before = _pixel(plain, 300, STRIP_TOP + 1)
    handle_after = _pixel(chosen, 300, STRIP_TOP + 1)
    assert _blueness(handle_after) > _blueness(handle_before) + 60, \
        f"손잡이가 드러나지 않는다: {handle_before} -> {handle_after}"

    # 구간 안쪽도 파랗게 물든다
    fill_before = _pixel(plain, 300, MIDDLE_Y)
    fill_after = _pixel(chosen, 300, MIDDLE_Y)
    assert _blueness(fill_after) > _blueness(fill_before) + 20, \
        f"채움이 드러나지 않는다: {fill_before} -> {fill_after}"


def test_selection_border_is_thick_enough() -> None:
    """1px 테두리는 필름스트립 위에서 사라진다. 두 픽셀 이상 진해야 한다."""
    view = _view()
    view.selected = 1
    surface = _render(view)
    edge = [_pixel(surface, x, MIDDLE_Y) for x in (201, 202)]
    assert all(_blueness(c) > 60 for c in edge), f"테두리가 얇다: {edge}"


def test_unselected_clips_stay_plain() -> None:
    """선택하지 않은 구간까지 파래지면 구분이 되지 않는다."""
    view = _view()
    view.selected = 1
    surface = _render(view)
    other = _pixel(surface, 100, MIDDLE_Y)          # 첫 번째 구간 (0~100초)
    assert _blueness(other) < 20, f"선택하지 않았는데 강조됐다: {other}"


def test_disabled_clip_is_black() -> None:
    """지운 구간은 검은 자리로 남아야 한다(필름스트립을 비추지 않는다).

    가운데에는 "삭제됨" 글자가 있으므로 글자를 피해 왼쪽을 본다.
    """
    view = _view()
    view.model.set_enabled(1, False)
    view.selected = -1
    surface = _render(view)
    assert _pixel(surface, 230, MIDDLE_Y) == (0, 0, 0)

    # 글자는 실제로 찍혀 있어야 한다 — 가운데 어딘가는 검지 않다
    centre = [_pixel(surface, x, MIDDLE_Y) for x in range(280, 320)]
    assert any(c != (0, 0, 0) for c in centre), "'삭제됨' 글자가 없다"


def test_playhead_is_drawn_red() -> None:
    view = _view()
    view.position = 150.0                            # x = 300
    surface = _render(view)
    red, _green, blue = _pixel(surface, 300, MIDDLE_Y)
    assert red > 200 and blue < 120, f"재생헤드가 빨갛지 않다: {(red, _green, blue)}"


def test_ruler_band_has_its_own_background() -> None:
    """눈금 띠는 누르는 자리다 — 본체와 색이 달라야 알아본다."""
    view = _view()
    surface = _render(view)
    ruler = _pixel(surface, 300, 3)
    body = _pixel(surface, 300, MIDDLE_Y)
    assert ruler != body, f"눈금 띠가 본체와 같다: {ruler}"
