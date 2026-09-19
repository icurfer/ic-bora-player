"""하단 타임라인 — 보면서 자르고 붙인다 (기획서 v0.5).

`Gtk.DrawingArea` 에 직접 그린다. 위젯을 수십 개 쌓는 것보다 빠르고, 필름스트립처럼
연속된 그림을 다루기에 맞다. GTK 4.0 부터 있으므로 22.04 에서도 돈다.

좌표는 둘뿐이다: **시각(초)** 과 **x(px)**. `_x_of()` / `_time_of()` 가 그 사이를 옮긴다.
보이는 범위(`view_start`~`view_end`)를 좁히면 확대다.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from ..log import get as get_logger  # noqa: E402
from .model import Timeline, fmt  # noqa: E402
from .thumbs import HEIGHT as THUMB_HEIGHT, ThumbStrip  # noqa: E402

log = get_logger("clip.timeline")

STRIP_TOP = 20          # 눈금 띠의 높이. **여기를 누르면 재생헤드가 움직인다**
                        # (필름스트립 본체를 누르면 구간 선택일 뿐 재생은 끊기지 않는다)
STRIP_HEIGHT = THUMB_HEIGHT
TOTAL_HEIGHT = STRIP_TOP + STRIP_HEIGHT + 6
EDGE_GRAB = 7           # px — 이 안에서 잡으면 경계를 끄는 것으로 본다
MIN_VIEW = 2.0          # 초 — 이보다 더 확대하지 않는다
ZOOM_STEP = 1.25
# 열자마자 이만큼은 뽑아 둔다. 폭을 아직 모를 때도 그림이 채워지기 시작해야 한다.
PREFETCH = 40


class TimelineView(Gtk.DrawingArea):
    """편집 상태(`Timeline`)를 그리고, 마우스 조작을 그 모델에 옮긴다.

    위젯은 모델을 **바꾸기만** 하고 무엇을 할지는 바깥이 정한다 —
    `on_seek`(재생헤드 이동), `on_changed`(편집됨), `on_scrub`(끄는 동안 그 프레임 보여주기).
    """

    def __init__(self, on_seek=None, on_changed=None, on_scrub=None,
                 on_position=None) -> None:
        super().__init__(content_height=TOTAL_HEIGHT, hexpand=True)
        self.on_seek = on_seek
        self.on_changed = on_changed
        self.on_scrub = on_scrub
        self.on_position = on_position      # 프레임마다 — 지운 구간인지 바깥이 판단한다

        self.model: Timeline | None = None
        self.thumbs: ThumbStrip | None = None
        self.position = 0.0             # 재생헤드(원본 시각)
        self.selected = -1
        self.view_start = 0.0
        self.view_end = 0.0

        self._drag_kind = ""            # "" | "trim-start" | "trim-end" | "move" | "seek"
        self._drag_index = -1
        self._drag_from = 0.0
        self._pending_request = 0
        self._tiles = [0, 0]
        self._last_tiles = [-1, -1]
        self._tick_id = 0
        self._position_source = None
        self._last_view: tuple | None = None

        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        self.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    # ── 바깥에서 쓰는 것 ─────────────────────────────────────────────────
    def load(self, video: Path, duration: float) -> Timeline:
        if self.thumbs is not None:
            self.thumbs.close()
        self.model = Timeline(duration)
        self.thumbs = ThumbStrip(video, on_ready=lambda *_: self.queue_draw())
        self.position = 0.0
        self.selected = -1
        self.view_start, self.view_end = 0.0, duration or 1.0
        self._last_view = None
        # 첫 요청은 draw 를 기다리지 않는다 — 창이 아직 매핑되지 않았으면 draw 가
        # 불리지 않아 필름스트립이 영영 비어 있게 된다(실제로 그랬다).
        self._request_span(self.view_start, self.view_end, PREFETCH)
        self.queue_draw()
        return self.model

    def unload(self) -> None:
        self.unfollow()
        if self.thumbs is not None:
            self.thumbs.close()
            self.thumbs = None
        self.model = None
        self.queue_draw()

    def set_position(self, seconds: float) -> None:
        if abs(seconds - self.position) < 0.02:
            return
        self.position = seconds
        self.queue_draw()

    def follow(self, source) -> None:
        """재생 위치를 **프레임마다** 읽어 재생헤드를 움직인다.

        창의 250ms 폴링에 얹으면 선이 뚝뚝 끊겨 보인다. 프레임 클록에 맞추면
        화면 주사율대로 흐른다. `source()` 는 지금 위치(초)나 None 을 준다.
        """
        self.unfollow()
        self._position_source = source
        self._tick_id = self.add_tick_callback(self._on_frame)

    def unfollow(self) -> None:
        if self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        self._position_source = None

    def _on_frame(self, _widget, _clock) -> bool:
        if self._position_source is not None:
            now = self._position_source()
            if now is not None:
                self.set_position(now)
                if self.on_position is not None:
                    self.on_position(now)
        return GLib.SOURCE_CONTINUE

    def split_here(self) -> bool:
        if self.model is None:
            return False
        index = self.model.split(self.position)
        if index < 0:
            return False
        self.selected = index
        self._changed()
        return True

    def delete_selected(self) -> bool:
        if self.model is None or self.selected < 0:
            return False
        self.model.toggle(self.selected)
        self._changed()
        return True

    def undo(self) -> bool:
        if self.model is None or not self.model.undo():
            return False
        self.selected = min(self.selected, len(self.model) - 1)
        self._changed()
        return True

    def redo(self) -> bool:
        if self.model is None or not self.model.redo():
            return False
        self.selected = min(self.selected, len(self.model) - 1)
        self._changed()
        return True

    def zoom(self, factor: float, around: float | None = None) -> None:
        if self.model is None:
            return
        pivot = self.position if around is None else around
        span = (self.view_end - self.view_start) / factor
        span = max(MIN_VIEW, min(span, self.model.duration or MIN_VIEW))
        ratio = 0.5
        if self.view_end > self.view_start:
            ratio = (pivot - self.view_start) / (self.view_end - self.view_start)
            ratio = min(max(ratio, 0.0), 1.0)
        self.view_start = pivot - span * ratio
        self.view_end = self.view_start + span
        self._clamp_view()
        self._request_span(self.view_start, self.view_end, PREFETCH)
        self.queue_draw()

    def zoom_fit(self) -> None:
        if self.model is None:
            return
        self.view_start, self.view_end = 0.0, self.model.duration or 1.0
        self.queue_draw()

    # ── 좌표 ─────────────────────────────────────────────────────────────
    def _span(self) -> float:
        return max(0.001, self.view_end - self.view_start)

    def _x_of(self, seconds: float) -> float:
        return (seconds - self.view_start) / self._span() * self.get_width()

    def _time_of(self, x: float) -> float:
        return self.view_start + x / max(1, self.get_width()) * self._span()

    def _clamp_view(self) -> None:
        duration = (self.model.duration if self.model else 0.0) or 1.0
        span = min(self._span(), duration)
        self.view_start = min(max(0.0, self.view_start), duration - span)
        self.view_end = self.view_start + span

    # ── 그리기 ───────────────────────────────────────────────────────────
    def _draw(self, _area, cr, width: int, height: int) -> None:
        cr.set_source_rgb(0.12, 0.12, 0.14)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        if self.model is None or width <= 0:
            return

        self._draw_ruler(cr, width)
        self._request_visible_thumbs(width)
        self._tiles = [0, 0]            # 채운 칸 / 빈 칸 — 왜 안 보이는지 물을 때 쓴다

        top, bottom = STRIP_TOP, STRIP_TOP + STRIP_HEIGHT
        for index, clip in enumerate(self.model):
            x0, x1 = self._x_of(clip.start), self._x_of(clip.end)
            if x1 < -2 or x0 > width + 2:
                continue
            self._draw_clip(cr, index, clip, x0, x1, top, bottom)

        if self._tiles != self._last_tiles:
            self._last_tiles = list(self._tiles)
            log.debug("필름스트립: 채움 %d · 빈칸 %d (폭 %d, 캐시 %d장)",
                      self._tiles[0], self._tiles[1], width,
                      len(self.thumbs._cache) if self.thumbs else 0)

        # 재생헤드 — 맨 위에 그린다
        head = self._x_of(self.position)
        if -2 <= head <= width + 2:
            cr.set_source_rgb(1.0, 0.35, 0.35)
            cr.set_line_width(2)
            cr.move_to(head, 0)
            cr.line_to(head, bottom + 4)
            cr.stroke()

    def _draw_clip(self, cr, index: int, clip, x0: float, x1: float,
                   top: int, bottom: int) -> None:
        cr.save()
        cr.rectangle(x0, top, max(1.0, x1 - x0), bottom - top)
        cr.clip()

        # 필름스트립 — 지운 구간에는 그리지 않는다. 편집기들이 그러듯 검은 자리로 남겨야
        # 무엇이 빠졌는지 한눈에 보인다(반투명으로 덮었더니 그림이 비쳐 헷갈렸다).
        if self.thumbs is not None and clip.enabled:
            # 타일 하나가 덮는 시간만큼은 어긋나도 그 그림을 쓴다 — 격자가 정확히
            # 맞기를 기대하면 반올림 차이로 전부 빈칸이 된다(thumbs.get 주석 참고).
            tolerance = max(1.0, self._span() / max(1, self.get_width()) * THUMB_HEIGHT * 2)
            x = x0
            while x < x1:
                at = self._time_of(x)
                pixbuf = self.thumbs.get(at, tolerance)
                if pixbuf is not None:
                    Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, top)
                    cr.paint()
                    self._tiles[0] += 1
                    x += pixbuf.get_width()
                else:
                    self._tiles[1] += 1
                    cr.set_source_rgb(0.2, 0.2, 0.23)
                    cr.rectangle(x, top, THUMB_HEIGHT * 1.78, bottom - top)
                    cr.fill()
                    x += THUMB_HEIGHT * 1.78
        cr.restore()

        if not clip.enabled:
            # 지운 구간 — 완전히 검은 자리. 목록에서 빼지 않고 남기는 이유는 되살리려고다.
            cr.set_source_rgb(0.0, 0.0, 0.0)
            cr.rectangle(x0, top, max(1.0, x1 - x0), bottom - top)
            cr.fill()
            width = x1 - x0
            if width > 54:
                cr.set_source_rgba(1, 1, 1, 0.45)
                cr.set_font_size(11)
                extents = cr.text_extents("삭제됨")
                cr.move_to(x0 + (width - extents.width) / 2,
                           top + (bottom - top + extents.height) / 2)
                cr.show_text("삭제됨")

        # 테두리 — 선택된 것만 밝게
        chosen = index == self.selected
        if chosen:
            cr.set_source_rgb(0.45, 0.75, 1.0)
            cr.set_line_width(2.5)
        else:
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.set_line_width(1)
        cr.rectangle(x0 + 1, top + 1, max(1.0, x1 - x0 - 2), bottom - top - 2)
        cr.stroke()

    def _draw_ruler(self, cr, width: int) -> None:
        # 눈금 띠에 배경을 깔아 "여기를 누르면 재생헤드가 움직인다"를 드러낸다.
        cr.set_source_rgb(0.18, 0.18, 0.21)
        cr.rectangle(0, 0, width, STRIP_TOP)
        cr.fill()
        span = self._span()
        # 눈금 간격을 보기 좋은 값으로 고른다
        for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
            if span / step <= 12:
                break
        cr.set_source_rgba(1, 1, 1, 0.45)
        cr.set_font_size(10)
        first = int(self.view_start // step) * step
        at = first
        while at <= self.view_end:
            x = self._x_of(at)
            cr.move_to(x, 0)
            cr.line_to(x, 6)
            cr.stroke()
            cr.move_to(x + 3, 12)
            cr.show_text(fmt(at))
            at += step

    def _request_visible_thumbs(self, width: int) -> None:
        """보이는 범위만 요청한다 — 전체를 미리 뽑으면 5분이 걸린다(실측 §5).

        ⚠ **뷰가 바뀌었을 때만 실제로 요청한다.** 요청은 120ms 뒤로 미뤄 두는데
        (스크롤 중 큐가 터지지 않게), 재생헤드가 프레임마다 다시 그리면 그 타이머가
        매번 새로 밀려 영영 발동하지 않는다. 실제로 재생 중에는 한 장도 안 뽑혔다.
        """
        view = (round(self.view_start, 2), round(self.view_end, 2), width)
        if view == self._last_view:
            return
        self._last_view = view
        tile = THUMB_HEIGHT * 1.78
        count = max(1, int(width / tile) + 1)
        self._request_span(self.view_start, self.view_end, count)

    def _request_span(self, start: float, end: float, count: int) -> None:
        if self.thumbs is None or count <= 0:
            return
        # 끝을 살짝 넘겨 요청하면 ffmpeg 이 빈손으로 돌아온다(코드 234). 안쪽으로 접는다.
        limit = max(0.0, (self.model.duration if self.model else end) - 0.5)
        step = max(0.5, (end - start) / count)
        times = [min(start + step * i, limit) for i in range(count + 1)]
        # 연달아 부르면 스크롤 중에 큐가 터진다. 살짝 미뤄 마지막 것만 보낸다.
        if self._pending_request:
            GLib.source_remove(self._pending_request)
        self._pending_request = GLib.timeout_add(
            120, self._flush_request, [t for t in times if t >= 0])

    def _flush_request(self, times: list[float]) -> bool:
        self._pending_request = 0
        if self.thumbs is not None:
            self.thumbs.request(times)
        return False

    # ── 조작 ─────────────────────────────────────────────────────────────
    def _hit(self, x: float) -> tuple[int, str]:
        """그 x 에 무엇이 있나 — (구간 번호, "start"|"end"|"body"|"")."""
        if self.model is None:
            return -1, ""
        for index, clip in enumerate(self.model):
            x0, x1 = self._x_of(clip.start), self._x_of(clip.end)
            if abs(x - x0) <= EDGE_GRAB and index > 0:
                return index, "start"
            if abs(x - x1) <= EDGE_GRAB and index < len(self.model) - 1:
                return index, "end"
            if x0 <= x <= x1:
                return index, "body"
        return -1, ""

    def _on_motion(self, _c, x: float, _y: float) -> None:
        _index, where = self._hit(x)
        name = "ew-resize" if where in ("start", "end") else "default"
        cursor = Gdk.Cursor.new_from_name(name, None)
        if cursor is not None:
            self.set_cursor(cursor)

    def _on_pressed(self, gesture, n_press: int, x: float, y: float) -> None:
        if self.model is None:
            return
        if y < STRIP_TOP:
            # 눈금 띠 — 재생헤드를 옮긴다. 선택은 건드리지 않는다.
            self._seek_to(self._time_of(x))
            return
        index, where = self._hit(x)
        if where == "body":
            self.selected = index
        if n_press == 2 and where == "body":
            # 더블클릭 = 지우기/되살리기. 자주 하는 조작이라 바로 닿게 둔다.
            self.model.toggle(index)
            self._changed()
            return
        self.queue_draw()

    def _on_released(self, _gesture, _n: int, _x: float, _y: float) -> None:
        # 본체를 눌렀다 떼는 것은 **선택**일 뿐이다.
        # 예전에는 여기서 재생헤드를 옮겼는데, 구간을 고르려고 누를 때마다 재생이
        # 그리로 튀었다. 재생헤드는 눈금 띠에서만 옮긴다.
        return

    def _on_drag_begin(self, gesture, x: float, _y: float) -> None:
        if self.model is None:
            return
        _ok, _sx, start_y = (True, x, 0.0)
        gesture_ok, _px, py = gesture.get_start_point()
        if gesture_ok:
            start_y = py
        index, where = self._hit(x)
        self._drag_index = index
        self._drag_from = self._time_of(x)
        if start_y < STRIP_TOP:
            self._drag_kind = "seek"    # 눈금을 끌면 스크럽
        elif where in ("start", "end"):
            self._drag_kind = f"trim-{where}"
            self.model._push()          # 드래그 한 번을 되돌리기 하나로 친다
        elif where == "body":
            self._drag_kind = ""        # 본체를 끄는 것은 선택일 뿐 — 재생을 끊지 않는다
            self.selected = index
        else:
            self._drag_kind = ""

    def _on_drag_update(self, gesture, dx: float, _dy: float) -> None:
        if self.model is None or not self._drag_kind:
            return
        ok, start_x, _ = gesture.get_start_point()
        at = self._time_of((start_x if ok else 0) + dx)
        if self._drag_kind == "trim-start":
            self.model.trim(self._drag_index, start=at, push=False)
        elif self._drag_kind == "trim-end":
            self.model.trim(self._drag_index, end=at, push=False)
        elif self._drag_kind == "seek":
            self._seek_to(at, scrub=True)
        if self.on_scrub and self._drag_kind.startswith("trim"):
            self.on_scrub(at)           # 끄는 동안 그 프레임을 보여 준다
        self.queue_draw()

    def _on_drag_end(self, _gesture, _dx: float, _dy: float) -> None:
        if self._drag_kind.startswith("trim"):
            self._changed()
        self._drag_kind = ""
        self._drag_index = -1

    def _on_scroll(self, controller, dx: float, dy: float) -> bool:
        if self.model is None:
            return False
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            self.zoom(ZOOM_STEP if dy < 0 else 1 / ZOOM_STEP)
        else:
            # 가로 스크롤이 없는 휠 마우스도 있어 세로도 이동으로 받는다
            shift = (dx or dy) * self._span() * 0.12
            self.view_start += shift
            self.view_end += shift
            self._clamp_view()
            self.queue_draw()
        return True

    def _seek_to(self, seconds: float, scrub: bool = False) -> None:
        seconds = min(max(0.0, seconds), self.model.duration if self.model else 0.0)
        self.position = seconds
        self.queue_draw()
        if self.on_seek:
            self.on_seek(seconds, scrub)

    def _changed(self) -> None:
        self.queue_draw()
        if self.on_changed:
            self.on_changed()
