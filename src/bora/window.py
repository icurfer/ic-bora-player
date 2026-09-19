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
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .glarea import MpvGLArea  # noqa: E402
from . import log as logmod  # noqa: E402
from .log import get as get_logger  # noqa: E402
from .player import Player  # noqa: E402
from . import desktop as desktop_setup  # noqa: E402
from .clip import ClipList, ClipWindow  # noqa: E402
from .clip.timeline import TimelineView  # noqa: E402
from .clip.model import DEFAULT_SPAN, Clip  # noqa: E402
from .editor import EditorWindow  # noqa: E402
from .notes import NoteDocument, NotePanel  # noqa: E402
from .state import Pin, State  # noqa: E402
from .stt import MODELS as STT_MODELS, ExtractRunner, Extraction, ensure_ready  # noqa: E402
from .subtitle.loader import SUB_SUFFIXES, Plan, prepare_for_video  # noqa: E402
from .tracks import track_label  # noqa: E402


log = get_logger("window")


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class BoraWindow(Adw.ApplicationWindow):
    # 전체화면에서 헤더바·컨트롤을 감추는 동작
    UI_HIDE_DELAY = 3          # 초 — 마우스를 멈추고 이만큼 지나면 감춘다
    UI_TRANSITION_MS = 250     # 접히고 펴지는 시간

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, default_width=960, default_height=560, title="Bora")

        self.player = Player()
        self._seeking = False          # 사용자가 슬라이더를 잡고 있는 동안은 갱신하지 않는다
        self._plan: Plan | None = None
        self._current: Path | None = None
        self._cache_base = Path(GLib.get_user_cache_dir()) / "bora"
        self._track_buttons: list[Gtk.CheckButton] = []
        self._hide_ui_id = 0            # 전체화면에서 UI 를 감출 타이머
        self.state = State()
        self._resume_toast: Adw.Toast | None = None
        self._save_state_id = 0
        self._editor: EditorWindow | None = None
        self._clips = ClipList()
        self._clip_window: ClipWindow | None = None
        self._notes_open = False
        self._stt: ExtractRunner | None = None
        self._stt_bar: Gtk.ProgressBar | None = None
        self._last_toast_title: str | None = None

        # 하위 메뉴 팝오버. 부모는 하단 메뉴 버튼에 붙인다.
        self._sub_popover = Gtk.Popover()
        self._audio_popover = Gtk.Popover()
        self._more_popover = Gtk.Popover()
        self._pin_popover = Gtk.Popover()
        self._stt_popover = Gtk.Popover()
        self._log_popover = Gtk.Popover()

        self._toasts = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(root)
        self.set_content(self._toasts)

        # 전체화면에서 바가 툭 사라지면 거칠다. Revealer 로 미끄러지듯 접는다.
        # (Gtk.Revealer 는 GTK 4.0 부터라 22.04 에서도 그대로 돈다.)
        self._header = self._build_header()
        self._header_revealer = Gtk.Revealer(
            child=self._header,
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            transition_duration=self.UI_TRANSITION_MS,
            reveal_child=True,
        )
        root.append(self._header_revealer)

        self._video = MpvGLArea(self.player)
        # 지운 구간을 지날 때 덮는 검은 판. 편집기들이 그러듯 "여기는 빠진다"를
        # 재생 중에 눈으로 보여 준다. CSS 없이 직접 칠한다(프로바이더를 늘리지 않으려고).
        self._blackout = Gtk.DrawingArea(can_target=False, visible=False)
        self._blackout.set_draw_func(self._draw_blackout)
        self._video_stack = Gtk.Overlay()
        self._video_stack.set_child(self._video)
        self._video_stack.add_overlay(self._blackout)

        # 영상 | 메모. 메모를 접으면 영상이 전부 차지한다.
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                                vexpand=True, resize_start_child=True,
                                shrink_start_child=False, shrink_end_child=False)
        self._paned.set_start_child(self._video_stack)
        self._notes = NotePanel(self)
        self._paned.set_end_child(self._notes)
        self._notes.set_visible(False)          # 기본은 접어 둔다
        root.append(self._paned)

        self._controls = self._build_controls()
        self._controls_revealer = Gtk.Revealer(
            child=self._controls,
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=self.UI_TRANSITION_MS,
            reveal_child=True,
        )
        root.append(self._controls_revealer)

        # 편집 타임라인 — **접힌 상태가 기본**이다. 그냥 볼 때 화면을 빼앗으면 안 된다
        # (이 앱은 여전히 플레이어다 — 기획서 v0.5 §2).
        self._timeline = TimelineView(on_seek=self._on_timeline_seek,
                                      on_changed=self._on_timeline_changed,
                                      on_scrub=self._on_timeline_scrub,
                                      on_position=self._on_timeline_position)
        self._edit_revealer = Gtk.Revealer(
            child=self._build_edit_area(),
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=self.UI_TRANSITION_MS,
            reveal_child=False,
        )
        root.append(self._edit_revealer)
        self._preview = False           # 미리보기 중이면 잘린 자리를 건너뛴다

        self._apply_settings()

        # 재생 위치는 폴링으로 갱신한다. mpv 의 time-pos 변화를 구독하면 초당 수십 번
        # 메인 루프로 넘어와 UI 가 불필요하게 바빠진다.
        GLib.timeout_add(250, self._tick)
        # 이어보기 기록. 매초 쓸 이유가 없다(기획서 v0.2 §8-4 실측).
        GLib.timeout_add_seconds(30, self._remember_position)

        # 창 자체에 붙인다 — 헤더바·컨트롤 위에 떨궈도 받아야 한다.
        self._setup_drop_target(self)
        self._setup_keys()
        self._setup_motion()
        self._setup_context_menu()
        self.connect("notify::fullscreened", self._on_fullscreen_changed)
        self.connect("close-request", self._on_close)

    # ── 입력 ─────────────────────────────────────────────────────────────
    def _setup_drop_target(self, widget: Gtk.Widget) -> None:
        """창 어디에 떨궈도 열리게 한다. 영상과 자막을 함께 떨구는 것도 받는다."""
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop)
        widget.add_controller(target)

    def _on_drop(self, _target, value, _x, _y) -> bool:
        files = [Path(f.get_path()) for f in value.get_files() if f.get_path()]
        if not files:
            return False
        self.open_dropped(files)
        return True

    def open_dropped(self, files: list[Path]) -> bool:
        """떨어진 파일들을 영상/자막으로 갈라 연다.

        자막만 떨구면 지금 재생 중인 영상에 붙인다 — 자막 이름이 다를 때의 구제 수단이다.
        """
        videos = [f for f in files if f.suffix.lower() not in SUB_SUFFIXES]
        subs = [f for f in files if f.suffix.lower() in SUB_SUFFIXES]
        if videos:
            self.open_path(videos[0], subs[0] if subs else None)
            return True
        if subs and self._current is not None:
            self.open_path(self._current, subs[0])
            return True
        if subs:
            self.toast("영상을 먼저 연 뒤에 자막을 떨궈라")
        return False

    def _setup_keys(self) -> None:
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        # CAPTURE — 창이 포커스 위젯보다 **먼저** 키를 본다.
        # 기본값 BUBBLE 이면 포커스된 버튼이 Space 를 삼켜 버튼이 눌린다
        # (실제로 파일 열기 버튼에 포커스가 있어 Space 가 파일 탐색기를 열었다).
        # 플레이어는 어디에 포커스가 있든 Space 가 일시정지여야 한다 — mpv·VLC 도 그렇다.
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.add_controller(keys)

    def _typing(self) -> bool:
        """글자를 치고 있는 중인가 — 그렇다면 단축키로 가로채면 안 된다.

        메모 패널(TextView)과 클립 제목·검색 같은 입력칸이 **같은 창 안에** 있다.
        CAPTURE 로 먼저 받는 대가로, 여기서 직접 비켜 줘야 한다.
        """
        focus = self.get_focus()
        return isinstance(focus, (Gtk.Editable, Gtk.TextView))

    def _on_key(self, _c, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        if state & Gdk.ModifierType.CONTROL_MASK and not self._typing():
            shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            if keyval in (Gdk.KEY_e, Gdk.KEY_E):
                self.toggle_edit()
                return True
            if keyval in (Gdk.KEY_z, Gdk.KEY_Z) and self.editing:
                self.redo_edit() if shift else self.undo_edit()
                return True
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        if self._typing():
            return False
        if self.editing:
            # 타임라인이 펴져 있을 때만 편집 키가 이긴다. 접혀 있으면 S 는 그대로 정지다.
            if keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self.split_clip()
                return True
            if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
                self.delete_clip()
                return True
        handlers = {
            Gdk.KEY_space: self.toggle_pause,
            Gdk.KEY_s: self.stop,
            Gdk.KEY_f: self.toggle_fullscreen,
            Gdk.KEY_F11: self.toggle_fullscreen,
            Gdk.KEY_Escape: lambda: self.set_fullscreen(False),
            Gdk.KEY_Left: lambda: self.player.seek_relative(-5),
            Gdk.KEY_Right: lambda: self.player.seek_relative(5),
            Gdk.KEY_Down: lambda: self._nudge_volume(-5),
            Gdk.KEY_Up: lambda: self._nudge_volume(5),
            Gdk.KEY_o: self.choose_file,
            Gdk.KEY_c: lambda: self.take_screenshot(True),
            Gdk.KEY_C: lambda: self.take_screenshot(False),   # Shift+C — 자막 없이
            Gdk.KEY_e: self.open_editor,
            Gdk.KEY_m: self.toggle_notes,
            Gdk.KEY_a: self.cycle_loop,
            Gdk.KEY_F5: lambda: self._set_loop_edge("a"),
            Gdk.KEY_F6: lambda: self._set_loop_edge("b"),
            Gdk.KEY_p: lambda: self.add_pin(),
            Gdk.KEY_r: lambda: self._nudge_sub_pos(-5),     # 위로
            Gdk.KEY_R: lambda: self._nudge_sub_pos(5),      # Shift+R — 아래로
            Gdk.KEY_P: self._show_pin_menu,
            Gdk.KEY_k: lambda: self.add_clip(),
            Gdk.KEY_K: self.show_clips,          # Shift+K — 클립 목록
            Gdk.KEY_bracketleft: lambda: self._nudge_sub_delay(-0.1),
            Gdk.KEY_bracketright: lambda: self._nudge_sub_delay(0.1),
            Gdk.KEY_comma: lambda: self._nudge_speed(-0.25),
            Gdk.KEY_period: lambda: self._nudge_speed(0.25),
        }
        handler = handlers.get(keyval)
        if handler is None:
            return False
        handler()
        return True

    def _nudge_volume(self, delta: float) -> None:
        self.player.volume = self.player.volume + delta
        self._vol_scale.set_value(self.player.volume)

    def _nudge_speed(self, delta: float) -> None:
        self.player.speed = self.player.speed + delta
        self.state.settings.speed = self.player.speed
        self.toast(f"재생 속도 {self.player.speed:g}x")

    def _nudge_sub_delay(self, delta: float) -> None:
        self.player.sub_delay = self.player.sub_delay + delta
        self.toast(f"자막 싱크 {self.player.sub_delay:+.1f}초")
        if hasattr(self, "_sync_spin"):
            self._sync_spin.set_value(self.player.sub_delay)

    # ── 전체화면 ─────────────────────────────────────────────────────────
    # 전체화면인데 헤더바·컨트롤이 계속 떠 있으면 영상을 가린다.
    # 평소에는 감추고, 마우스를 움직이면 잠깐 보여준 뒤 다시 감춘다.
    # ── 우클릭 메뉴 ──────────────────────────────────────────────────────
    # 항목마다 단축키를 같이 보여준다. 전체화면에서 바를 감춘 동안에도 조작할 수 있어야 한다.
    def _setup_context_menu(self) -> None:
        """영상 위젯에 붙인다.

        ⚠ 창(self)에 붙이면 안 된다. `set_pointing_to` 의 좌표는 **팝오버 부모 위젯의 좌표계**인데
        Adw.ApplicationWindow 는 내용물을 한 번 더 감싸고 있어서 제스처 좌표와 어긋난다.
        그러면 메뉴가 클릭한 자리가 아니라 좌상단에 뜬다(전체화면에서는 화면 밖으로 밀려 안 보인다).
        제스처와 팝오버를 **같은 위젯**에 붙여야 좌표계가 일치한다.
        """
        self._menu_popover = Gtk.Popover(has_arrow=False, position=Gtk.PositionType.BOTTOM)
        self._menu_popover.set_parent(self._video)
        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_right_click)
        self._video.add_controller(gesture)

    def _on_right_click(self, _gesture, _n: int, x: float, y: float) -> None:
        menu = self._build_context_menu()
        self._menu_popover.set_child(self._scrollable_menu(menu))

        # 메뉴가 화면 밖으로 나가지 않게 가리키는 점을 안쪽으로 당긴다.
        # position=BOTTOM 은 클릭 지점을 **가로 중앙**으로 삼으므로, 오른쪽 끝에서 열면
        # 절반이 잘려 나가 눌러도 안 열리는 것처럼 보였다.
        #
        # ⚠ 크기는 **자식**에서 잰다. 팝오버 자신은 아직 realize 되지 않아 0 을 준다 —
        #    0 으로 clamp 하면 아무것도 보정되지 않는다(처음에 그렇게 짰다가 헛돌았다).
        _minimum, natural = menu.get_preferred_size()
        width = natural.width
        height = min(natural.height, max(240, int(self.get_height() * 0.72)))
        view_w, view_h = self._video.get_width(), self._video.get_height()

        half = width / 2
        at_x = min(max(x, half), max(half, view_w - half)) if view_w else x
        # 아래로 펼 자리가 없으면 위로 편다.
        below = view_h - y
        if view_h and below < height and y > below:
            self._menu_popover.set_position(Gtk.PositionType.TOP)
            at_y = max(y, min(height, view_h))
        else:
            self._menu_popover.set_position(Gtk.PositionType.BOTTOM)
            at_y = min(y, max(0, view_h - height)) if view_h else y

        # ⚠ `Gdk.Rectangle(x=..., y=...)` 처럼 생성자 키워드로 주면 **조용히 무시되어 (0,0)** 이 된다.
        #    (boxed 구조체라 PyGObject 가 키워드를 필드에 넣어 주지 않는다.)
        #    메뉴가 클릭한 자리가 아니라 좌상단에 뜨던 진짜 원인이었다. 필드에 직접 대입해야 한다.
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(at_x), int(at_y), 1, 1
        self._menu_popover.set_pointing_to(rect)
        self._menu_popover.popup()
        log.debug("우클릭 메뉴: 클릭 (%d, %d) → 표시 (%d, %d), 메뉴 %dx%d, 영상 %dx%d",
                  int(x), int(y), int(at_x), int(at_y), width, height, view_w, view_h)

    def _build_context_menu(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        play_label = "재생" if self.player.paused else "일시정지"
        items = [
            (play_label, "Space", self.toggle_pause),
            ("정지 (처음으로)", "S", self.stop),
            (None, None, None),
            ("5초 뒤로", "←", lambda: self.player.seek_relative(-5)),
            ("5초 앞으로", "→", lambda: self.player.seek_relative(5)),
            (None, None, None),
            ("자막 싱크 -0.1초", "[", lambda: self._nudge_sub_delay(-0.1)),
            ("자막 싱크 +0.1초", "]", lambda: self._nudge_sub_delay(0.1)),
            (None, None, None),
            ("전체화면 나가기" if self.is_fullscreen() else "전체화면", "F", self.toggle_fullscreen),
            ("구간 반복", "A", self.cycle_loop),
            ("핀 꽂기 (제목 입력)", "P", lambda: self.add_pin()),
            ("핀만 꽂기", "Shift+P", lambda: self.add_pin(write_title=False)),
            ("핀 목록", "", self._show_pin_menu),
            (None, None, None),
            ("편집 타임라인", "Ctrl+E", self.toggle_edit),
            ("이 구간 클립으로 담기", "K", lambda: self.add_clip()),
            ("클립 목록", "Shift+K", self.show_clips),
            (None, None, None),
            ("학습 메모", "M", self.toggle_notes),
            ("자막 편집", "E", self.open_editor),
            ("스크린샷 저장", "C", lambda: self.take_screenshot(True)),
            ("파일 열기", "O", self.choose_file),
        ]
        for label, accel, handler in items:
            if label is None:
                box.append(Gtk.Separator(margin_top=3, margin_bottom=3))
                continue
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            row.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            row.append(Gtk.Label(label=accel, css_classes=["dim-label"], xalign=1))
            button = Gtk.Button(child=row, has_frame=False)
            button.connect("clicked", self._on_menu_item, handler)
            box.append(button)
        return box

    def _on_menu_item(self, _button, handler) -> None:
        self._menu_popover.popdown()
        handler()

    def _setup_motion(self) -> None:
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    def _on_motion(self, _controller, _x, _y) -> None:
        if self.is_fullscreen():
            self._reveal_ui()

    def _reveal_ui(self) -> None:
        """UI 를 보이고, 잠시 뒤 다시 감추도록 예약한다."""
        self._show_chrome(True)
        self._cancel_hide()
        self._hide_ui_id = GLib.timeout_add_seconds(self.UI_HIDE_DELAY, self._hide_ui)

    def _hide_ui(self) -> bool:
        self._hide_ui_id = 0
        # 자막 메뉴를 열어 둔 채로 감추면 조작을 뺏는다.
        busy = self._sub_popover.get_visible() or self._menu_popover.get_visible()
        if self.is_fullscreen() and not busy:
            self._show_chrome(False)
        return False

    def _cancel_hide(self) -> None:
        if self._hide_ui_id:
            GLib.source_remove(self._hide_ui_id)
            self._hide_ui_id = 0

    def _show_chrome(self, visible: bool) -> None:
        self._header_revealer.set_reveal_child(visible)
        self._controls_revealer.set_reveal_child(visible)
        # 전체화면에서 영상을 가리지 않게 메모도 함께 접는다(내용은 그대로 있다).
        if self.is_fullscreen():
            self._notes.set_visible(visible and self._notes_open)
        # 감출 때는 마우스 커서도 같이 감춘다(영상 위에 남으면 거슬린다).
        self.set_cursor(None if visible else Gdk.Cursor.new_from_name("none", None))

    @property
    def chrome_visible(self) -> bool:
        return self._header_revealer.get_reveal_child()

    def set_fullscreen(self, on: bool) -> None:
        """요청만 한다. 실제 반영은 'fullscreened' 상태 변화에서 처리한다.

        `fullscreen()` 은 비동기다 — 부른 직후에는 아직 전체화면이 아니다.
        게다가 사용자가 제목표시줄·창 관리자 단축키로 바꾸면 이 함수는 아예 불리지 않는다.
        그래서 **상태를 구독**해야 어느 경로로 바뀌든 UI 가 일관되게 따라간다.
        """
        if on:
            self.fullscreen()
        else:
            self.unfullscreen()

    def _on_fullscreen_changed(self, *_args) -> None:
        on = self.is_fullscreen()
        log.debug("전체화면 상태 변화: %s", on)
        self._fs_button.set_icon_name(
            "view-restore-symbolic" if on else "view-fullscreen-symbolic")
        if on:
            self._reveal_ui()          # 들어가자마자 감추지 않고 잠깐 보여준다
        else:
            self._cancel_hide()
            self._show_chrome(True)
        # 창 크기가 바뀌었다. auto-render 를 꺼 뒀으므로 직접 다시 그리지 않으면
        # 다음 프레임이 올 때까지 검은 화면이 남는다(일시정지 중이면 영영 남는다).
        self._video.queue_render()

    def toggle_fullscreen(self) -> None:
        self.set_fullscreen(not self.is_fullscreen())

    # ── 구성 ─────────────────────────────────────────────────────────────
    def _build_header(self) -> Gtk.Widget:
        """제목·열기·상태만 둔다.

        기능 버튼은 전부 하단 메뉴로 내렸다 — 헤더에 여섯 개까지 늘자 무엇이 무엇인지 알기
        어려웠고, 전체화면에서 헤더를 감추면 손이 닿지 않았다. 하단 바는 재생 중에도 늘 보이는 자리다.
        """
        header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="Bora", subtitle="")
        header.set_title_widget(self._title)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="파일 열기 (O)")
        open_btn.connect("clicked", lambda *_: self.choose_file())
        header.pack_start(open_btn)

        self._status = Gtk.Label(label="", css_classes=["dim-label"])
        header.pack_end(self._status)

        return header

    # ── 더보기 메뉴 ──────────────────────────────────────────────────────
    SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
    ASPECTS = (("원본", "-1"), ("16:9", "16:9"), ("4:3", "4:3"), ("2.35:1", "2.35:1"))

    def _rebuild_more_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)

        box.append(Gtk.Label(label="재생 속도", xalign=0, css_classes=["dim-label"]))
        speeds = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
        current = round(self.player.speed, 2)
        for value in self.SPEEDS:
            btn = Gtk.ToggleButton(label=f"{value:g}x", active=abs(current - value) < 0.01)
            btn.connect("toggled", self._on_speed_toggled, value)
            speeds.append(btn)
        box.append(speeds)

        box.append(Gtk.Separator(margin_top=4))
        box.append(Gtk.Label(label="화면 비율", xalign=0, css_classes=["dim-label"]))
        aspects = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, homogeneous=True)
        for label, ratio in self.ASPECTS:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda _b, r=ratio: self.player.set_aspect(r))
            aspects.append(btn)
        box.append(aspects)

        zoom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        zoom_row.append(Gtk.Label(label="확대"))
        zoom = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, draw_value=False)
        zoom.set_range(-1.0, 1.0)
        zoom.set_value(self.player.zoom)
        zoom.connect("value-changed", lambda sc: setattr(self.player, "zoom", sc.get_value()))
        zoom_row.append(zoom)
        box.append(zoom_row)

        box.append(Gtk.Separator(margin_top=4))
        box.append(Gtk.Label(label="자막 크기", xalign=0, css_classes=["dim-label"]))
        size_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        adj = Gtk.Adjustment(value=self.player.sub_font_size or 55, lower=20, upper=120,
                             step_increment=2, page_increment=10)
        spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        spin.connect("value-changed", self._on_sub_size_changed)
        size_row.append(spin)
        box.append(size_row)

        # 글꼴 — Gtk.FontDialogButton 은 4.10+ 라 쓰지 않는다(22.04 는 GTK 4.6).
        # 시스템에 있는 글꼴 이름을 직접 고르게 한다.
        font_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        font_row.append(Gtk.Label(label="글꼴"))
        fonts = self._font_choices()
        self._font_drop = Gtk.DropDown.new_from_strings(fonts)
        current_font = self.player.sub_font or ""
        if current_font in fonts:
            self._font_drop.set_selected(fonts.index(current_font))
        self._font_drop.connect("notify::selected", self._on_font_changed)
        self._font_drop.set_hexpand(True)
        font_row.append(self._font_drop)
        box.append(font_row)

        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        color_row.append(Gtk.Label(label="색"))
        for label, value in (("흰색", "#FFFFFFFF"), ("노랑", "#FFFFFF00"), ("연두", "#FFCCFF66")):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._on_sub_color, value)
            color_row.append(btn)
        box.append(color_row)

        pos_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pos_row.append(Gtk.Label(label="자막 위치"))
        pos = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, draw_value=False,
                        tooltip_text="왼쪽이 화면 위 (R / Shift+R)")
        pos.set_range(self.player.SUB_POS_MIN, self.player.SUB_POS_MAX)
        pos.set_value(self.player.sub_pos)
        pos.add_mark(self.player.SUB_POS_DEFAULT, Gtk.PositionType.BOTTOM, None)
        pos.connect("value-changed", self._on_sub_pos_changed)
        pos_row.append(pos)
        self._sub_pos_scale = pos
        box.append(pos_row)

        box.append(Gtk.Separator(margin_top=4))
        shots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        with_subs = Gtk.Button(label="스크린샷 (자막 포함)")
        with_subs.connect("clicked", lambda *_: self.take_screenshot(True))
        shots.append(with_subs)
        no_subs = Gtk.Button(label="자막 없이")
        no_subs.connect("clicked", lambda *_: self.take_screenshot(False))
        shots.append(no_subs)
        box.append(shots)

        box.append(Gtk.Separator(margin_top=4))
        default_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="기본 영상 플레이어", xalign=0, hexpand=True)
        default_row.append(label)
        self._default_switch = Gtk.Switch(active=desktop_setup.is_default(), valign=Gtk.Align.CENTER)
        self._default_switch.connect("state-set", self._on_default_toggled)
        default_row.append(self._default_switch)
        box.append(default_row)
        if desktop_setup.app_info() is None:
            hint = Gtk.Label(label="먼저 앱 등록이 필요하다: scripts/install-desktop.sh",
                             xalign=0, wrap=True, css_classes=["dim-label"])
            box.append(hint)
            self._default_switch.set_sensitive(False)

        recent = self.state.recent_items()
        if recent:
            box.append(Gtk.Separator(margin_top=4))
            box.append(Gtk.Label(label=f"최근 파일 {len(recent)}개", xalign=0,
                                 css_classes=["dim-label"]))
            for item in recent[:8]:
                btn = Gtk.Button(label=item.title, has_frame=False)
                btn.set_tooltip_text(item.path)
                btn.connect("clicked", self._on_recent_clicked, item.path)
                box.append(btn)
        self._more_popover.set_child(box)

    def _on_speed_toggled(self, button: Gtk.ToggleButton, value: float) -> None:
        if button.get_active():
            self.player.speed = value
            self.state.settings.speed = value
            self.toast(f"재생 속도 {value:g}x")

    # 국내 자막에 흔히 쓰는 글꼴을 앞에 두고, 시스템에 실제로 있는 것만 보여 준다.
    PREFERRED_FONTS = ("Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "NanumBarunGothic",
                       "Pretendard", "Malgun Gothic", "Sans")

    def _font_choices(self) -> list[str]:
        available = set()
        try:
            ctx = self.get_pango_context()
            available = {f.get_name() for f in ctx.list_families()}
        except Exception:       # 글꼴 목록을 못 얻어도 기능 자체는 살아 있어야 한다
            log.debug("글꼴 목록을 얻지 못했다")
        names = [f for f in self.PREFERRED_FONTS if not available or f in available]
        return names or ["Sans"]

    def _on_font_changed(self, drop: Gtk.DropDown, _param) -> None:
        model = drop.get_model()
        index = drop.get_selected()
        if model is None or index == Gtk.INVALID_LIST_POSITION:
            return
        name = model.get_string(index)
        self.player.set_sub_style(font=name)
        self.state.settings.sub_font = name
        self.toast(f"자막 글꼴: {name}")

    def _on_sub_pos_changed(self, scale: Gtk.Scale) -> None:
        self.player.sub_pos = scale.get_value()
        self.state.settings.sub_pos = self.player.sub_pos

    def _nudge_sub_pos(self, delta: float) -> None:
        """R = 위로, Shift+R = 아래로. 강의 슬라이드와 겹칠 때 바로 피한다."""
        self.player.sub_pos = self.player.sub_pos + delta
        self.state.settings.sub_pos = self.player.sub_pos
        self.toast(f"자막 위치 {self.player.sub_pos:.0f}")
        if hasattr(self, "_sub_pos_scale"):
            self._sub_pos_scale.set_value(self.player.sub_pos)

    def _on_sub_color(self, _button, value: str) -> None:
        self.player.set_sub_style(color=value)
        self.state.settings.sub_color = value

    def _on_sub_size_changed(self, spin: Gtk.SpinButton) -> None:
        size = int(spin.get_value())
        self.player.set_sub_style(size=size)
        self.state.settings.sub_font_size = size

    def _on_default_toggled(self, _switch, enable: bool) -> bool:
        """기본 영상 플레이어를 Bora 로 하거나, 이전 프로그램으로 되돌린다."""
        if enable:
            # 바꾸기 전 값을 기억해 둬야 나중에 정확히 되돌릴 수 있다.
            snapshot = desktop_setup.snapshot_defaults()
            if snapshot:
                self.state.settings.previous_defaults = snapshot
        ok, message = desktop_setup.set_default(
            enable, self.state.settings.previous_defaults)
        self.state.save()
        self.toast(message)
        if not ok:
            return True         # 실패하면 스위치를 되돌린다
        return False

    def _on_recent_clicked(self, _button, path: str) -> None:
        self._more_popover.popdown()
        self.open_path(Path(path))

    # ── 학습 메모 ────────────────────────────────────────────────────────
    def toggle_notes(self, show: bool | None = None) -> None:
        want = (not self._notes_open) if show is None else bool(show)
        if want and self._current is None:
            self.toast("영상을 먼저 열어라")
            want = False
        self._notes_open = want
        self._notes.set_visible(want)
        if want:
            if self._notes.doc is None or self._notes.doc.path != NoteDocument.path_for(self._current):
                self._notes.load_for(self._current, self._current.stem)
            self._notes.set_visible(True)
            # 처음 열 때 절반쯤 차지하게 둔다
            if self._paned.get_position() <= 0:
                self._paned.set_position(max(360, self.get_width() - 380))
            self._notes.focus_editor()
        else:
            self._notes.save()
        log.debug("메모 패널: %s", want)

    # ── 자막 편집 ────────────────────────────────────────────────────────
    def open_editor(self) -> EditorWindow | None:
        """자막 에디터를 연다. 이미 열려 있으면 그 창을 앞으로 가져온다."""
        if self._editor is not None:
            self._editor.follow_playback()
            self._editor.present()
            return self._editor

        chosen = self._editor_source()
        if chosen is None:
            self.toast("편집할 자막이 없다. 자막 파일을 먼저 열어라")
            return None
        source, save_to = chosen
        try:
            from .subtitle.model import SubtitleDocument

            document = SubtitleDocument.load(source)
        except Exception as exc:
            log.exception("자막을 읽지 못했다: %s", source)
            self.toast(f"자막을 읽지 못했다: {exc}")
            return None
        if not document.cues:
            self.toast("자막에 편집할 줄이 없다")
            return None

        # 편집 중에는 멈춰 두는 편이 낫다 — 시각을 박는 작업이다.
        if not self.player.paused:
            self.toggle_pause()

        self._editor = EditorWindow(self, document, save_to=save_to)
        self._editor.connect("close-request", self._on_editor_closed)
        self._editor.present()
        return self._editor

    def _editor_source(self) -> tuple[Path, Path] | None:
        """(읽을 파일, 저장할 파일).

        전처리로 분리한 트랙이 있으면 **지금 선택된 트랙**을 편집한다(기획서 v0.2 §8-3).
        ⚠ 그 트랙은 캐시 폴더에 있다. 거기에 저장하면 사용자가 찾을 수 없으므로,
           저장은 **영상 옆 `<영상이름>.<언어>.srt`** 로 한다.
        """
        if self._plan is None or self._current is None:
            return None

        if self._plan.tracks:
            chosen = self._plan.tracks[0]
            selected = self.player.sub_id
            for track in self.player.sub_tracks:
                if track.get("id") != selected:
                    continue
                name = track.get("external-filename")
                if not name:
                    break
                for candidate in self._plan.tracks:
                    if str(candidate.path) == name:
                        chosen = candidate
                        break
                break
            save_to = self._current.with_suffix(f".{chosen.lang}.srt")
            return chosen.path, save_to

        source = self._plan.source
        return source, source

    def _on_editor_closed(self, *_args) -> bool:
        self._editor = None
        return False

    def reload_subtitle(self, path: Path) -> None:
        """에디터가 저장한 파일을 다시 물린다. 방금 고친 결과가 화면에 바로 보인다."""
        self.player.reload_sub(path)
        GLib.timeout_add(300, self._refresh_subtitle_menu_once)
        self.toast("자막을 다시 읽었다")

    def take_screenshot(self, include_subs: bool = True) -> Path | None:
        base = self.state.settings.screenshot_dir or GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_PICTURES) or str(Path.home())
        stem = self._current.stem if self._current else "bora"
        name = f"{stem}-{_fmt_time(self.player.time_pos).replace(':', '')}.png"
        try:
            path = self.player.screenshot(Path(base) / "bora" / name, include_subs)
        except Exception as exc:
            log.warning("스크린샷 실패: %s", exc)
            self.toast(f"스크린샷 실패: {exc}")
            return None
        self.toast(f"스크린샷 저장: {path}")
        return path

    # ── 텍스트 추출 ──────────────────────────────────────────────────────
    def _offer_extract(self) -> None:
        if self._current is None or self._plan is not None or self._stt is not None:
            return
        ready, _hint = ensure_ready()
        title = "자막이 없다 — 음성에서 만들까요?" if ready else "자막이 없다 (음성 추출 미설치)"
        self._last_toast_title = title      # 로그·검증에서 확인할 수 있게 남긴다
        toast = Adw.Toast(title=title, timeout=10)
        toast.set_button_label("추출" if ready else "안내")
        toast.connect("button-clicked", lambda *_: self._show_extract_menu())
        self._toasts.add_toast(toast)

    def _show_extract_menu(self) -> None:
        self._popup_submenu(self._stt_popover, self._rebuild_extract_menu)

    def _rebuild_extract_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10,
                      width_request=320)
        ready, hint = ensure_ready()

        if self._stt is not None and self._stt.running:
            box.append(Gtk.Label(label="추출 중", xalign=0))
            self._stt_bar = Gtk.ProgressBar(show_text=True, text="준비 중")
            box.append(self._stt_bar)
            cancel = Gtk.Button(label="취소", css_classes=["destructive-action"])
            cancel.connect("clicked", lambda *_: self._cancel_extract())
            box.append(cancel)
            self._stt_popover.set_child(box)
            return

        if not ready:
            label = Gtk.Label(label=hint, xalign=0, wrap=True, css_classes=["dim-label"])
            box.append(label)
            self._stt_popover.set_child(box)
            return

        box.append(Gtk.Label(label="음성에서 자막 만들기", xalign=0))
        box.append(Gtk.Label(
            label="영상은 건드리지 않는다. 결과는 영상 옆 .srt 로 저장되고 바로 붙는다.\n"
                  "끝나면 자막 편집기로 고칠 수 있다.",
            xalign=0, wrap=True, css_classes=["dim-label"]))
        box.append(Gtk.Separator(margin_top=4))

        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_row.append(Gtk.Label(label="모델"))
        names = [f"{name} — {note} ({size})" for name, note, size in STT_MODELS]
        self._stt_model = Gtk.DropDown.new_from_strings(names)
        self._stt_model.set_selected(2)          # small
        self._stt_model.set_hexpand(True)
        model_row.append(self._stt_model)
        box.append(model_row)

        lang_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lang_row.append(Gtk.Label(label="언어"))
        self._stt_lang = Gtk.DropDown.new_from_strings(["한국어", "영어", "자동 감지"])
        self._stt_lang.set_hexpand(True)
        lang_row.append(self._stt_lang)
        box.append(lang_row)

        start = Gtk.Button(label="추출 시작", css_classes=["suggested-action"])
        start.connect("clicked", lambda *_: self.start_extract())
        box.append(start)
        self._stt_popover.set_child(box)

    def start_extract(self) -> bool:
        if self._current is None or (self._stt is not None and self._stt.running):
            return False
        ready, hint = ensure_ready()
        if not ready:
            self.toast(hint.splitlines()[0])
            return False

        model = STT_MODELS[self._stt_model.get_selected()][0] if hasattr(self, "_stt_model") else "small"
        lang = ["ko", "en", ""][self._stt_lang.get_selected()] if hasattr(self, "_stt_lang") else "ko"
        output = self._current.with_suffix(f".{lang or 'auto'}.srt")

        self._stt = ExtractRunner(
            on_progress=lambda *a: GLib.idle_add(self._on_extract_progress, *a),
            on_done=lambda *a: GLib.idle_add(self._on_extract_done, *a),
            on_error=lambda m: GLib.idle_add(self._on_extract_error, m),
        )
        if not self._stt.start(Extraction(self._current, output, model, lang)):
            self._stt = None
            return False
        self._main_popover.popdown()
        self.toast(f"자막 추출 시작 ({model}) — 시간이 걸린다")
        self._rebuild_extract_menu()
        return True

    def _cancel_extract(self) -> None:
        if self._stt is not None:
            self._stt.cancel()

    def _on_extract_progress(self, seconds: float, total: float, cues: int) -> bool:
        if self._stt_bar is not None:
            fraction = (seconds / total) if total else 0.0
            self._stt_bar.set_fraction(max(0.0, min(1.0, fraction)))
            self._stt_bar.set_text(f"{_fmt_time(seconds)} / {_fmt_time(total)} · {cues}줄")
        self._status.set_label(f"자막 추출 {int((seconds / total * 100) if total else 0)}% · {cues}줄")
        return False

    def _on_extract_done(self, path: Path, cues: int) -> bool:
        self._stt = None
        self._stt_bar = None
        self.toast(f"자막 {cues}줄을 만들었다 — {path.name}")
        self._status.set_label("")
        # 만든 자막을 바로 물린다. 어긋나면 자막 편집기로 고칠 수 있다.
        if self._current is not None:
            self.open_path(self._current, path)
        return False

    def _on_extract_error(self, message: str) -> bool:
        self._stt = None
        self._stt_bar = None
        self._status.set_label("")
        self.toast(f"자막 추출: {message}")
        return False

    # ── 구간 반복 · 핀 ───────────────────────────────────────────────────
    def cycle_loop(self) -> None:
        """A -> B -> 해제. 버튼 하나로 끝낸다(곰·KMP 는 키 두 개를 쓴다)."""
        now = self.player.time_pos or 0.0
        a, b = self.player.loop_a, self.player.loop_b
        if a is None:
            self.player.set_loop(now, None)
            self.toast(f"구간 시작 {_fmt_time(now)} — 끝점을 정하려면 다시 누른다")
        elif b is None:
            if now <= a + 0.3:
                self.toast("끝점이 시작점보다 뒤여야 한다")
                return
            self.player.set_loop(a, now)
            self.toast(f"구간 반복 {_fmt_time(a)} ~ {_fmt_time(now)}")
        else:
            self.player.clear_loop()
            self.toast("구간 반복 해제")
        self._sync_loop_button()

    def _set_loop_edge(self, which: str) -> None:
        """F5=시작, F6=끝. 곰·KMP 를 쓰던 사람에게 익숙한 방식이다."""
        now = self.player.time_pos or 0.0
        a, b = self.player.loop_a, self.player.loop_b
        if which == "a":
            self.player.set_loop(now, b)
            self.toast(f"구간 시작 {_fmt_time(now)}")
        else:
            if a is None:
                self.toast("시작점을 먼저 정해라 (F5)")
                return
            if now <= a + 0.3:
                self.toast("끝점이 시작점보다 뒤여야 한다")
                return
            self.player.set_loop(a, now)
            self.toast(f"구간 반복 {_fmt_time(a)} ~ {_fmt_time(now)}")
        self._sync_loop_button()

    def _sync_loop_button(self) -> None:
        a, b = self.player.loop_a, self.player.loop_b
        if a is not None and b is not None:
            self._loop_btn.set_tooltip_text(
                f"구간 반복 중 {_fmt_time(a)} ~ {_fmt_time(b)} — 누르면 해제")
            self._loop_btn.add_css_class("suggested-action")
        else:
            if a is not None:
                self._loop_btn.set_tooltip_text(
                    f"시작 {_fmt_time(a)} — 끝점을 정하려면 다시 누른다")
            else:
                self._loop_btn.set_tooltip_text("구간 반복 (A)")
            self._loop_btn.remove_css_class("suggested-action")

    # ── 편집 타임라인 (기획서 v0.5) ──────────────────────────────────────
    def _build_edit_area(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      margin_start=6, margin_end=6, margin_bottom=6)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        def tool(icon, tip, handler, label=""):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip) if not label else \
                Gtk.Button(label=label, tooltip_text=tip)
            button.connect("clicked", lambda *_: handler())
            bar.append(button)
            return button

        tool("edit-cut-symbolic", "재생헤드에서 자르기 (S)", self.split_clip)
        self._del_btn = tool("user-trash-symbolic", "선택한 구간 지우기/되살리기 (Delete)",
                             self.delete_clip)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self._undo_btn = tool("edit-undo-symbolic", "되돌리기 (Ctrl+Z)", self.undo_edit)
        self._redo_btn = tool("edit-redo-symbolic", "다시 실행 (Ctrl+Shift+Z)", self.redo_edit)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        tool("zoom-out-symbolic", "축소", lambda: self._timeline.zoom(1 / 1.6))
        tool("zoom-in-symbolic", "확대", lambda: self._timeline.zoom(1.6))
        tool("zoom-fit-best-symbolic", "전체 보기", self._timeline.zoom_fit)

        self._edit_summary = Gtk.Label(xalign=0, hexpand=True,
                                       css_classes=["dim-label"])
        bar.append(self._edit_summary)

        self._preview_btn = Gtk.ToggleButton(label="미리보기",
                                             tooltip_text="남은 구간만 이어서 재생한다")
        self._preview_btn.connect("toggled", self._on_preview_toggled)
        bar.append(self._preview_btn)
        export = Gtk.Button(label="내보내기", css_classes=["suggested-action"])
        export.connect("clicked", lambda *_: self.export_timeline())
        bar.append(export)

        box.append(bar)
        box.append(self._timeline)
        return box

    @property
    def editing(self) -> bool:
        return self._edit_revealer.get_reveal_child()

    def toggle_edit(self) -> None:
        """타임라인을 펴고 접는다 (Ctrl+E)."""
        if self.editing:
            if not self._confirm_discard_edit():
                return
            self._edit_revealer.set_reveal_child(False)
            self._preview_btn.set_active(False)
            self._timeline.unload()
            self._blackout.set_visible(False)
            return
        if self._current is None:
            self.toast("영상을 먼저 열어라")
            return
        duration = self.player.duration or 0.0
        if duration <= 0:
            self.toast("영상 길이를 아직 모른다 — 잠시 뒤에 다시")
            return
        self._timeline.load(self._current, duration)
        self._timeline.set_position(self.player.time_pos or 0.0)
        # 재생헤드는 프레임 클록에 맞춰 스스로 따라간다 — 창의 250ms 폴링에 얹으면 끊긴다.
        self._timeline.follow(lambda: self.player.time_pos)
        self._edit_revealer.set_reveal_child(True)
        self._sync_edit_bar()
        self.toast("편집: S 자르기 · Delete 지우기 · Ctrl+Z 되돌리기")

    def _confirm_discard_edit(self) -> bool:
        """편집 중이면 한 번 묻는다. 지금은 토스트로 알리고 접지 않는다.

        v0.4 와 달리 작업이 길어질 수 있어 말없이 버리면 안 된다(기획서 v0.5 §4-2).
        """
        model = self._timeline.model
        if model is None or not model.dirty:
            return True
        if getattr(self, "_edit_close_asked", False):
            self._edit_close_asked = False
            return True
        self._edit_close_asked = True
        self.toast("편집한 내용이 사라진다 — 접으려면 한 번 더 누르고, 남기려면 내보내라")
        return False

    def split_clip(self) -> None:
        if not self.editing:
            return
        if self._timeline.split_here():
            self._sync_edit_bar()
        else:
            self.toast("여기서는 자를 수 없다 (구간 경계에 너무 가깝다)")

    def delete_clip(self) -> None:
        if not self.editing:
            return
        if not self._timeline.delete_selected():
            self.toast("지울 구간을 먼저 고르라 (타임라인에서 클릭)")
            return
        self._sync_edit_bar()

    def undo_edit(self) -> None:
        if self.editing and not self._timeline.undo():
            self.toast("되돌릴 것이 없다")

    def redo_edit(self) -> None:
        if self.editing and not self._timeline.redo():
            self.toast("다시 실행할 것이 없다")

    def _on_timeline_seek(self, seconds: float, scrub: bool = False) -> None:
        self.player.seek_absolute(seconds)

    def _on_timeline_scrub(self, seconds: float) -> None:
        """경계를 끄는 동안 그 프레임을 보여 준다 — 이게 돼야 감이 잡힌다(T3)."""
        self.player.seek_absolute(seconds)

    def _draw_blackout(self, _area, cr, width: int, height: int) -> None:
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.55)
        cr.select_font_face("sans")
        cr.set_font_size(15)
        label = "삭제된 구간"
        extents = cr.text_extents(label)
        cr.move_to((width - extents.width) / 2, (height + extents.height) / 2)
        cr.show_text(label)

    def _on_timeline_position(self, seconds: float) -> None:
        """재생헤드가 지운 구간에 있으면 화면을 검게 덮는다.

        미리보기는 **건너뛰는** 쪽이라(결과물 확인) 여기서는 손대지 않는다.
        일반 재생에서는 지워진 자리를 그대로 지나가되 검게 보여 준다 — 무엇이 빠졌는지
        재생하면서 확인할 수 있어야 한다.
        """
        model = self._timeline.model
        if model is None:
            return
        index = model.index_at(seconds)
        cut = index >= 0 and not model[index].enabled
        want = cut and not self._preview
        if want != self._blackout.get_visible():
            self._blackout.set_visible(want)

    def _on_timeline_changed(self) -> None:
        self._sync_edit_bar()
        # 지금 있는 자리가 방금 지워졌을 수도 있다 — 덮개를 바로 맞춘다.
        position = self.player.time_pos
        if position is not None:
            self._on_timeline_position(position)

    def _sync_edit_bar(self) -> None:
        model = self._timeline.model
        if model is None:
            return
        kept = len(model.enabled_clips())
        self._edit_summary.set_label(
            f"구간 {kept}/{len(model)} · 결과 {_fmt_time(model.output_duration())}")
        self._undo_btn.set_sensitive(model.can_undo)
        self._redo_btn.set_sensitive(model.can_redo)

    def _on_preview_toggled(self, button: Gtk.ToggleButton) -> None:
        self._preview = button.get_active()
        model = self._timeline.model
        if self._preview and model is not None:
            first = model.enabled_clips()
            if not first:
                self.toast("남은 구간이 없다")
                button.set_active(False)
                return
            self.player.seek_absolute(first[0].start)
            self.player.paused = False

    def _preview_step(self) -> None:
        """잘린 자리에 들어서면 다음 구간으로 건너뛴다.

        mpv 의 ab-loop 은 구간이 하나뿐이라 쓸 수 없다. 경계에서 순간 끊기지만
        **결과 확인용으로는 충분하다** — 내보낸 파일은 끊기지 않는다(실측 D).
        """
        model = self._timeline.model
        if model is None:
            return
        now = self.player.time_pos
        if now is None:
            return
        target = model.next_enabled_start(now)
        if target is not None and abs(target - now) > 0.05:
            self.player.seek_absolute(target)

    def export_timeline(self) -> None:
        """타임라인의 남은 구간을 클립 목록으로 옮겨 기존 내보내기 창에 넘긴다."""
        model = self._timeline.model
        if model is None:
            return
        kept = model.enabled_clips()
        if not kept:
            self.toast("남은 구간이 없다")
            return
        self._clips.clear()
        for clip in kept:
            self._clips.add(Clip(clip.start, clip.end, clip.title))
        self.show_clips()

    # ── 클립 (기획서 v0.4) ───────────────────────────────────────────────
    @property
    def current_path(self) -> Path | None:
        """지금 재생 중인 파일. 클립 창이 내보낼 원본으로 쓴다."""
        return self._current

    def current_audio_index(self) -> int | None:
        """선택된 오디오 트랙의 **0-기반 순번**.

        mpv 의 트랙 id 는 1-기반이고 모든 종류를 통틀어 매기지만,
        ffmpeg 의 `0:a:N` 은 오디오 스트림만 따로 0부터 센다. 그 변환이다.
        """
        for index, track in enumerate(self.player.audio_tracks):
            if track.get("selected"):
                return index
        return None

    def add_clip(self) -> bool:
        """구간을 클립 목록에 담는다.

        A-B 구간이 잡혀 있으면 그것을, 없으면 현재 위치부터 30초를 담는다
        (핀처럼 가볍게 누를 수 있어야 한다 — 구간은 목록 창에서 고친다).
        """
        if self._current is None:
            self.toast("재생 중인 영상이 없다")
            return False
        a, b = self.player.loop_a, self.player.loop_b
        if a is not None and b is not None:
            clip = Clip(a, b)
        else:
            start = self.player.time_pos or 0.0
            end = min(start + DEFAULT_SPAN, self.player.duration or start + DEFAULT_SPAN)
            clip = Clip(start, end)
        if not clip.valid:
            self.toast("구간이 너무 짧다")
            return False
        self._clips.add(clip)
        self.toast(f"클립 담음 — {clip.label()} ({len(self._clips)}개)")
        log.info("클립 담음: %.1f~%.1f", clip.start, clip.end)
        if self._clip_window is not None:
            self._clip_window.refresh()
        return True

    def show_clips(self) -> None:
        """클립 목록 창을 연다. 이미 열려 있으면 앞으로 가져온다."""
        if self._clip_window is not None:
            self._clip_window.refresh()
            self._clip_window.present()
            return
        window = ClipWindow(self, self._clips)
        window.connect("close-request", self._on_clip_window_closed)
        self._clip_window = window
        window.present()

    def _on_clip_window_closed(self, _window) -> bool:
        self._clip_window = None
        return False

    def add_pin(self, label: str = "", write_title: bool = True) -> Pin | None:
        """핀을 꽂는다. 구간이 잡혀 있으면 **구간 핀**, 아니면 시점 핀.

        `write_title` 이면 메모를 열고 그 줄 끝에 커서를 둔다 — 바로 제목을 칠 수 있다.
        이 앱을 쓰는 이유가 "타이핑이 손글씨보다 빠르기 때문"이라, 제목 입력도 키보드로 이어져야 한다.
        """
        if self._current is None:
            return None
        a, b = self.player.loop_a, self.player.loop_b
        if a is not None and b is not None:
            pin = Pin(start=a, end=b, label=label)
            note = f"구간 핀 {_fmt_time(a)} ~ {_fmt_time(b)}"
        else:
            now = self.player.time_pos or 0.0
            pin = Pin(start=now, label=label)
            note = f"핀 {_fmt_time(now)}"
        self.state.add_pin(self._current, pin)
        # 메모에도 남긴다 — 핀과 메모가 따로 놀면 되돌아볼 때 둘을 맞춰 봐야 한다.
        try:
            if self._notes.append_pin(pin.start, pin.end, label):
                note += " · 메모에 남김"
                if write_title and not label:
                    # 패널을 열고 커서를 그 줄 끝에 둔다. 이어서 치면 그대로 제목이 된다.
                    if not self._notes_open:
                        self.toggle_notes(True)
                    self._notes.focus_editor()
                    note += " — 이어서 제목을 입력하세요"
        except Exception as exc:            # 메모 실패가 핀을 막으면 안 된다
            log.warning("핀을 메모에 남기지 못했다: %s", exc)
        self.toast(note)
        log.debug("%s", note)
        return pin

    def goto_pin(self, pin: Pin) -> None:
        """시점 핀이면 그 자리로, 구간 핀이면 그 구간을 반복한다."""
        if pin.is_range:
            self.player.set_loop(pin.start, pin.end)
            self.toast(f"구간 반복 {_fmt_time(pin.start)} ~ {_fmt_time(pin.end)}")
        else:
            self.player.clear_loop()
            self.toast(f"{_fmt_time(pin.start)} 로 이동")
        self.player.seek_absolute(pin.start)
        self._sync_loop_button()

    def _show_pin_menu(self) -> None:
        self._popup_submenu(self._pin_popover, self._rebuild_pin_menu)

    def _rebuild_pin_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10,
                      width_request=300)
        pins = self.state.pins_for(self._current) if self._current else []
        if not pins:
            box.append(Gtk.Label(label="꽂아 둔 핀이 없다", css_classes=["dim-label"]))
        for index, pin in enumerate(pins):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            if pin.is_range:
                text = f"{_fmt_time(pin.start)} ~ {_fmt_time(pin.end)}  ({pin.length:.0f}초 반복)"
            else:
                text = _fmt_time(pin.start)
            go = Gtk.Button(label=f"{text}  {pin.label}".rstrip(), has_frame=False, hexpand=True)
            go.connect("clicked", self._on_pin_clicked, pin)
            row.append(go)
            drop = Gtk.Button(icon_name="user-trash-symbolic", has_frame=False,
                              tooltip_text="핀 지우기")
            drop.connect("clicked", self._on_pin_removed, index)
            row.append(drop)
            box.append(row)
        self._pin_popover.set_child(box)

    def _on_pin_clicked(self, _button, pin: Pin) -> None:
        self._pin_popover.popdown()
        self.goto_pin(pin)

    def _on_pin_removed(self, _button, index: int) -> None:
        if self._current is not None and self.state.remove_pin(self._current, index):
            self._rebuild_pin_menu()
            self.toast("핀을 지웠다")

    # ── 하나로 모은 메뉴 (하단 바) ───────────────────────────────────────
    def _scrollable_menu(self, box: Gtk.Widget) -> Gtk.Widget:
        """메뉴가 창보다 길면 **팝오버가 아예 뜨지 않는다.** 스크롤로 감싼다.

        항목을 하나씩 더하다 보니 메뉴 높이가 767px 이 되어 창(560px)을 넘었고,
        그 순간부터 버튼을 눌러도 아무 일도 일어나지 않았다. 기능이 자라면 또 넘으므로
        길이에 상관없이 뜨도록 만든다.
        """
        available = max(240, int(self.get_height() * 0.72))
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_height=True,
            propagate_natural_width=True,
            max_content_height=available,
        )
        scroller.set_child(box)
        return scroller

    def _menu_row(self, label: str, accel: str, handler, subtitle: str = "") -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        text.append(Gtk.Label(label=label, xalign=0))
        if subtitle:
            text.append(Gtk.Label(label=subtitle, xalign=0, css_classes=["dim-label"]))
        row.append(text)
        if accel:
            row.append(Gtk.Label(label=accel, css_classes=["dim-label"], xalign=1))
        button = Gtk.Button(child=row, has_frame=False)
        button.connect("clicked", lambda _b: self._run_menu_item(handler))
        return button

    def _run_menu_item(self, handler) -> None:
        self._main_popover.popdown()
        handler()

    def _rebuild_main_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      margin_top=8, margin_bottom=8, margin_start=8, margin_end=8,
                      width_request=300)

        box.append(self._menu_row("자막", "", self._show_subtitle_menu,
                                  self._plan.summary() if self._plan else "자막 없음"))
        audio = self.player.audio_tracks
        box.append(self._menu_row("오디오 트랙", "", self._show_audio_menu,
                                  f"{len(audio)}개" if audio else "없음"))
        box.append(Gtk.Separator(margin_top=4, margin_bottom=4))

        box.append(self._menu_row("학습 메모", "M", self.toggle_notes,
                                  "열려 있다" if self._notes_open else "영상 옆 .md 에 기록"))
        ready, _hint = ensure_ready()
        box.append(self._menu_row("음성에서 자막 만들기", "", self._show_extract_menu,
                                  "준비됨" if ready else "설치 필요"))
        box.append(self._menu_row("자막 편집", "E", self.open_editor,
                                  "재생 위치를 그 줄에 박는다"))
        box.append(Gtk.Separator(margin_top=4, margin_bottom=4))

        box.append(self._menu_row("화면·속도·자막 모양", "", self._show_more_menu,
                                  f"{self.player.speed:g}x"))
        pins = self.state.pins_for(self._current) if self._current else []
        box.append(self._menu_row("핀 목록", "", self._show_pin_menu,
                                  f"{len(pins)}개" if pins else "꽂은 핀 없음"))
        box.append(self._menu_row(
            "편집 타임라인", "Ctrl+E", self.toggle_edit,
            "접는다" if self.editing else "자르고 지워서 남길 것을 만든다"))
        box.append(self._menu_row(
            "클립 목록", "Shift+K", self.show_clips,
            f"{len(self._clips)}개 담김" if self._clips else "담아 둔 구간"))
        box.append(self._menu_row("스크린샷", "C", lambda: self.take_screenshot(True)))
        box.append(self._menu_row("파일 열기", "O", self.choose_file))
        box.append(self._menu_row(
            "로그", "", self._show_log_menu,
            dict((l[0], l[1]) for l in logmod.LEVELS).get(logmod.level_name(), "")))

        recent = self.state.recent_items()
        if recent:
            box.append(Gtk.Separator(margin_top=4, margin_bottom=4))
            box.append(Gtk.Label(label="최근 파일", xalign=0, margin_start=6,
                                 css_classes=["dim-label"]))
            for item in recent[:5]:
                box.append(self._menu_row(item.title, "",
                                          lambda p=item.path: self.open_path(Path(p))))
        self._main_popover.set_child(self._scrollable_menu(box))

    # ── 로그 ─────────────────────────────────────────────────────────────
    def _log_file_target(self) -> Path:
        """로그를 남길 파일. 설정 폴더에 둔다 — 지워도 앱에 지장이 없다."""
        return self.state.dir / "bora.log"

    def _show_log_menu(self) -> None:
        self._popup_submenu(self._log_popover, self._rebuild_log_menu)

    def _rebuild_log_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10,
                      width_request=300)
        box.append(Gtk.Label(label="얼마나 자세히 남길까", xalign=0,
                             css_classes=["dim-label"]))
        current = logmod.level_name()
        group = None
        for name, title, hint in logmod.LEVELS:
            button = Gtk.CheckButton(label=f"{title} — {hint}")
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.set_active(name == current)
            button.connect("toggled", self._on_log_level, name)
            box.append(button)

        box.append(Gtk.Separator(margin_top=4, margin_bottom=4))
        to_file = Gtk.CheckButton(label="파일로도 남기기")
        to_file.set_active(bool(logmod.log_file_path()))
        to_file.connect("toggled", self._on_log_to_file)
        box.append(to_file)
        where = logmod.log_file_path() or str(self._log_file_target())
        box.append(Gtk.Label(label=where, xalign=0, wrap=True, selectable=True,
                             css_classes=["dim-label"]))
        self._log_popover.set_child(box)

    def _on_log_level(self, button: Gtk.CheckButton, name: str) -> None:
        if not button.get_active():
            return
        self.state.settings.log_level = logmod.set_level(name)
        self.state.save()
        self.toast(f"로그: {dict((l[0], l[1]) for l in logmod.LEVELS)[name]}")

    def _on_log_to_file(self, button: Gtk.CheckButton) -> None:
        want = button.get_active()
        self.state.settings.log_to_file = want
        if want:
            path = logmod.add_log_file(str(self._log_file_target()))
            self.toast(f"로그를 파일에도 남긴다 — {path}" if path else "로그 파일을 열지 못했다")
        else:
            # 핸들러를 떼는 것까지는 하지 않는다 — 이미 열린 파일을 닫는 경계가 지저분하고,
            # 다음 실행부터 안 남기면 충분하다. 그 사실을 사용자에게 그대로 말한다.
            self.toast("다음 실행부터 파일에 남기지 않는다")
        self.state.save()

    def _popup_submenu(self, popover: Gtk.Popover, build) -> None:
        """하위 메뉴를 메뉴 버튼 자리에 띄운다."""
        build()
        if popover.get_parent() is None:
            popover.set_parent(self._menu_button)
            popover.set_position(Gtk.PositionType.TOP)
        popover.popup()

    def _show_subtitle_menu(self) -> None:
        self._popup_submenu(self._sub_popover, self._rebuild_subtitle_menu)

    def _show_audio_menu(self) -> None:
        self._popup_submenu(self._audio_popover, self._rebuild_audio_menu)

    def _show_more_menu(self) -> None:
        self._popup_submenu(self._more_popover, self._rebuild_more_menu)

    def _rebuild_audio_menu(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        tracks = self.player.audio_tracks
        if not tracks:
            box.append(Gtk.Label(label="오디오 트랙 없음", css_classes=["dim-label"]))
            self._audio_popover.set_child(box)
            return

        box.append(Gtk.Label(label=f"오디오 {len(tracks)}개", xalign=0, css_classes=["dim-label"]))
        box.append(Gtk.Separator())
        group = None
        for track in tracks:
            btn = Gtk.CheckButton(label=track_label(track))
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            if track.get("selected"):
                btn.set_active(True)
            btn.connect("toggled", self._on_audio_toggled, track["id"])
            box.append(btn)
        self._audio_popover.set_child(box)

    def _on_audio_toggled(self, button: Gtk.CheckButton, track_id) -> None:
        if button.get_active():
            self.player.audio_id = track_id

    def _rebuild_subtitle_menu(self) -> None:
        """자막 트랙 목록과 싱크 조절을 다시 그린다."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)

        info = self._plan.summary() if self._plan else "자막 없음"
        label = Gtk.Label(label=info, xalign=0, css_classes=["dim-label"])
        if self._plan:
            label.set_tooltip_text(self._plan.detect.reason)
        box.append(label)

        tracks = self.player.sub_tracks
        self._track_buttons = []
        if tracks:
            box.append(Gtk.Separator())
            box.append(Gtk.Label(label=f"자막 {len(tracks)}개", xalign=0, css_classes=["dim-label"]))
            group = None
            none_btn = Gtk.CheckButton(label="끄기")
            none_btn.connect("toggled", self._on_track_toggled, None)
            group = none_btn
            box.append(none_btn)
            self._track_buttons.append(none_btn)
            for track in tracks:
                btn = Gtk.CheckButton(label=track_label(track))
                btn.set_group(group)
                if track.get("selected"):
                    btn.set_active(True)
                btn.connect("toggled", self._on_track_toggled, track["id"])
                box.append(btn)
                self._track_buttons.append(btn)
            if not any(t.get("selected") for t in tracks):
                none_btn.set_active(True)

        box.append(Gtk.Separator())
        sync_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_row.append(Gtk.Label(label="싱크(초)"))
        # Adw.SpinRow 는 1.4+ 라 쓰지 않는다. Gtk.SpinButton 은 4.0 부터 있다.
        adj = Gtk.Adjustment(value=self.player.sub_delay, lower=-60, upper=60,
                             step_increment=0.1, page_increment=1.0)
        self._sync_spin = Gtk.SpinButton(adjustment=adj, digits=1, numeric=True)
        self._sync_spin.connect("value-changed",
                                lambda sb: setattr(self.player, "sub_delay", sb.get_value()))
        sync_row.append(self._sync_spin)
        box.append(sync_row)

        self._sub_popover.set_child(box)

    def _on_track_toggled(self, button: Gtk.CheckButton, track_id) -> None:
        if not button.get_active():
            return
        self.player.sub_id = track_id if track_id is not None else False

    def _build_controls(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)

        self._play_btn = Gtk.Button(icon_name="media-playback-start-symbolic",
                                    tooltip_text="재생/일시정지 (Space)")
        self._play_btn.connect("clicked", lambda *_: self.toggle_pause())
        box.append(self._play_btn)

        # 정지: 처음으로 되돌리고 멈춘다. 파일은 열어 둔다(국내 플레이어 관례).
        self._stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic",
                                    tooltip_text="정지 — 처음으로 (S)")
        self._stop_btn.connect("clicked", lambda *_: self.stop())
        box.append(self._stop_btn)

        self._pos_label = Gtk.Label(label="--:--", width_chars=6)
        box.append(self._pos_label)

        self._seek = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True,
                               draw_value=False, tooltip_text="탐색 (좌/우 화살표 5초)")
        self._seek.set_range(0, 1)
        self._seek.connect("change-value", self._on_seek)
        box.append(self._seek)

        self._dur_label = Gtk.Label(label="--:--", width_chars=6)
        box.append(self._dur_label)

        vol = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, draw_value=False, width_request=100)
        vol.set_range(0, 100)
        vol.set_value(self.player.volume)
        vol.connect("value-changed", lambda s: setattr(self.player, "volume", s.get_value()))
        self._vol_scale = vol
        vol.set_tooltip_text("볼륨 (위/아래 화살표)")
        box.append(Gtk.Image(icon_name="audio-volume-high-symbolic"))
        box.append(vol)

        # 구간 반복 — 누를 때마다 A -> B -> 해제 순환. 강의에서 안 들리는 대목을 되돌려 듣는 동작이다.
        self._loop_btn = Gtk.Button(icon_name="media-playlist-repeat-symbolic",
                                    tooltip_text="구간 반복 (A) — 한 번 더 누르면 끝점, 또 누르면 해제")
        self._loop_btn.connect("clicked", lambda *_: self.cycle_loop())
        box.append(self._loop_btn)

        self._pin_btn = Gtk.Button(icon_name="starred-symbolic",
                                   tooltip_text="핀 꽂기 (P) — 메모에 남기고 제목을 이어서 입력한다. "
                                                "Shift+P 는 조용히 꽂기만")
        self._pin_btn.connect("clicked", lambda *_: self.add_pin())
        box.append(self._pin_btn)

        # 이 버튼은 **창 맨 아래**에 있다. 기본값(direction=down, position=bottom)이면
        # 메뉴가 아래로 열려 화면 밖으로 나간다 — 눌러도 아무 일도 안 일어나는 것처럼 보인다.
        # 하위 메뉴들은 _popup_submenu 에서 TOP 을 명시했는데 여기만 빠져 있었다.
        self._menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                           direction=Gtk.ArrowType.UP,
                                           tooltip_text="메뉴 — 자막·오디오·메모·화면")
        self._main_popover = Gtk.Popover(position=Gtk.PositionType.TOP)
        self._menu_button.set_popover(self._main_popover)
        self._main_popover.connect("show", lambda *_: self._rebuild_main_menu())
        box.append(self._menu_button)

        self._fs_button = Gtk.Button(icon_name="view-fullscreen-symbolic",
                                     tooltip_text="전체화면 (F)")
        self._fs_button.connect("clicked", lambda *_: self.toggle_fullscreen())
        box.append(self._fs_button)

        return box

    # ── 설정·기록 ────────────────────────────────────────────────────────
    def _apply_settings(self) -> None:
        st = self.state.settings
        # 설정에 값이 있으면 명령줄·환경변수보다 이긴다. 비어 있으면 건드리지 않는다
        # (그래야 `--debug` 로 띄운 세션이 설정 때문에 조용해지지 않는다).
        if st.log_level:
            logmod.set_level(st.log_level)
        if st.log_to_file and not logmod.log_file_path():
            logmod.add_log_file(str(self._log_file_target()))
        self.player.speed = st.speed
        self.player.volume = st.volume
        self.player.set_sub_style(font=st.sub_font, size=st.sub_font_size,
                                  color=st.sub_color, pos=st.sub_pos)

    def _remember_position(self) -> bool:
        """지금 보고 있는 위치를 기록한다. 30초마다, 그리고 파일 전환·종료 때."""
        if self._current is not None:
            pos, dur = self.player.time_pos, self.player.duration
            if pos is not None and dur:
                self.state.note_playback(self._current, pos, dur,
                                         title=self._current.name)
                self.state.save()
        return True

    def _offer_resume(self, path: Path) -> None:
        """이어볼 위치가 있으면 토스트로 묻는다. 몇 초 안에 답이 없으면 처음부터 본다."""
        position = self.state.resume_for(path)
        if position is None:
            return
        title = f"{_fmt_time(position)} 부터 이어 볼까요?"
        self._last_toast_title = title
        toast = Adw.Toast(title=title, timeout=8)
        toast.set_button_label("이어보기")
        toast.connect("button-clicked", lambda *_: self.player.seek_absolute(position))
        self._toasts.add_toast(toast)

    # ── 동작 ─────────────────────────────────────────────────────────────
    def open_path(self, path: Path | str, subtitle: Path | None = None) -> None:
        path = Path(path)
        self._remember_position()          # 넘어가기 전에 지금 파일 위치를 남긴다
        try:
            self._plan = prepare_for_video(path, self._cache_base, subtitle)
        except Exception as exc:                    # 자막 준비 실패가 재생을 막으면 안 된다
            self._plan = None
            log.exception("자막 준비 실패: %s", path)
            self.toast(f"자막을 읽지 못했다: {exc}")
        if self._notes_open:
            self._notes.save()
        self.player.clear_loop()        # 다른 영상에 앞 파일의 구간이 남으면 안 된다
        self.player.open(path, self._plan)
        self._current = path
        if self._notes_open:
            self._notes.load_for(path, path.stem)
        self._title.set_title(path.name)
        self._title.set_subtitle(str(path.parent))
        # 트랙 주입 직후에는 track_list 가 아직 안 채워져 있을 수 있다. 한 박자 뒤에 그린다.
        GLib.timeout_add(300, self._refresh_subtitle_menu_once)
        if self._plan is not None:
            self.toast(f"자막: {self._plan.summary()}")
        else:
            # 자막이 없는 강의는 메모·검색·질의가 반쪽이 된다. 만들 수 있다고 알려 준다.
            GLib.timeout_add_seconds(2, lambda: (self._offer_extract(), False)[1])
        # 길이를 알아야 이어볼지 판단할 수 있다. 파일이 열린 뒤에 묻는다.
        GLib.timeout_add(600, lambda: (self._offer_resume(path), False)[1])

    def _refresh_subtitle_menu_once(self) -> bool:
        self._rebuild_subtitle_menu()
        self._rebuild_audio_menu()
        return False

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

    def stop(self) -> None:
        self.player.stop()
        self._sync_play_button()
        self._seek.set_value(0)
        self._pos_label.set_label("00:00")

    def toast(self, text: str) -> None:
        self._last_toast_title = text      # 마지막 알림 — 로그·검증에서 확인할 수 있게 남긴다
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
        if self.editing and pos is not None and self._preview:
            self._preview_step()
        self._sync_play_button()
        a, b = self.player.loop_a, self.player.loop_b
        if a is not None and b is not None:
            self._status.set_label(f"구간 반복 {_fmt_time(a)} ~ {_fmt_time(b)}")
        elif a is not None:
            self._status.set_label(f"구간 시작 {_fmt_time(a)} — 끝점 대기")
        else:
            hw = self.player.hwdec_current
            self._status.set_label("" if hw == "no" else f"하드웨어 디코딩: {hw}")
        return True

    def _on_close(self, *_args) -> bool:
        if self._stt is not None:
            self._stt.cancel()
        self._notes.save()
        self._remember_position()
        self.state.settings.speed = self.player.speed
        self.state.settings.volume = self.player.volume
        self.state.settings.sub_font_size = self.player.sub_font_size
        self.state.settings.sub_font = self.player.sub_font
        self.state.settings.sub_color = self.player.sub_color
        self.state.settings.sub_pos = self.player.sub_pos
        self.state.save()
        self.player.close()
        return False
