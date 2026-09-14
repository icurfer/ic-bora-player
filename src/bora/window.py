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
from .log import get as get_logger  # noqa: E402
from .player import Player  # noqa: E402
from . import desktop as desktop_setup  # noqa: E402
from .editor import EditorWindow  # noqa: E402
from .state import State  # noqa: E402
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
        self._last_toast_title: str | None = None

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
        root.append(self._video)

        self._controls = self._build_controls()
        self._controls_revealer = Gtk.Revealer(
            child=self._controls,
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=self.UI_TRANSITION_MS,
            reveal_child=True,
        )
        root.append(self._controls_revealer)

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
        self.add_controller(keys)

    def _on_key(self, _c, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        handlers = {
            Gdk.KEY_space: self.toggle_pause,
            Gdk.KEY_p: self.toggle_pause,
            Gdk.KEY_s: self.stop,
            Gdk.KEY_f: self.toggle_fullscreen,
            Gdk.KEY_F11: self.toggle_fullscreen,
            Gdk.KEY_Escape: lambda: self.set_fullscreen(False),
            Gdk.KEY_Left: lambda: self.player.seek_relative(-5),
            Gdk.KEY_Right: lambda: self.player.seek_relative(5),
            Gdk.KEY_Down: lambda: self._nudge_volume(-5),
            Gdk.KEY_Up: lambda: self._nudge_volume(5),
            Gdk.KEY_bracketleft: lambda: self._nudge_sub_delay(-0.1),
            Gdk.KEY_bracketright: lambda: self._nudge_sub_delay(0.1),
            Gdk.KEY_o: self.choose_file,
            Gdk.KEY_c: lambda: self.take_screenshot(True),
            Gdk.KEY_C: lambda: self.take_screenshot(False),   # Shift+C — 자막 없이
            Gdk.KEY_e: self.open_editor,
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
        self._menu_popover.set_child(self._build_context_menu())
        # 클릭한 점을 가리키게 한다. 폭·높이 1 짜리 사각형이면 그 지점에 붙는다.
        #
        # ⚠ `Gdk.Rectangle(x=..., y=...)` 처럼 생성자 키워드로 주면 **조용히 무시되어 (0,0)** 이 된다.
        #    (boxed 구조체라 PyGObject 가 키워드를 필드에 넣어 주지 않는다.)
        #    메뉴가 클릭한 자리가 아니라 좌상단에 뜨던 진짜 원인이었다. 필드에 직접 대입해야 한다.
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._menu_popover.set_pointing_to(rect)
        self._menu_popover.popup()
        log.debug("우클릭 메뉴: (%d, %d)", int(x), int(y))

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
        header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="Bora", subtitle="")
        header.set_title_widget(self._title)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="파일 열기 (O)")
        open_btn.connect("clicked", lambda *_: self.choose_file())
        header.pack_start(open_btn)

        self._status = Gtk.Label(label="", css_classes=["dim-label"])
        header.pack_end(self._status)

        # 자막 메뉴 — Adw.Dialog/PreferencesDialog 는 1.5+ 라 쓰지 않는다.
        # MenuButton + Popover 는 GTK 4.0 부터 있어 22.04 에서도 그대로 돈다.
        self._sub_button = Gtk.MenuButton(icon_name="media-view-subtitles-symbolic",
                                          tooltip_text="자막 — 트랙 선택·싱크 (싱크: [ , ])")
        self._sub_popover = Gtk.Popover()
        self._sub_button.set_popover(self._sub_popover)
        self._rebuild_subtitle_menu()
        header.pack_end(self._sub_button)

        # 오디오 트랙 — 영화에 코멘터리나 더빙이 따로 들어 있는 경우가 많다
        self._audio_button = Gtk.MenuButton(icon_name="audio-x-generic-symbolic",
                                            tooltip_text="오디오 트랙")
        self._audio_popover = Gtk.Popover()
        self._audio_button.set_popover(self._audio_popover)
        self._rebuild_audio_menu()
        header.pack_end(self._audio_button)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic",
                              tooltip_text="자막 편집 (E) — 재생 위치를 그 줄에 박는다")
        edit_btn.connect("clicked", lambda *_: self.open_editor())
        header.pack_end(edit_btn)

        self._more_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                           tooltip_text="속도·화면·스크린샷·최근 파일")
        self._more_popover = Gtk.Popover()
        self._more_button.set_popover(self._more_popover)
        self._more_popover.connect("show", lambda *_: self._rebuild_more_menu())
        self._rebuild_more_menu()
        header.pack_end(self._more_button)
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

        self._fs_button = Gtk.Button(icon_name="view-fullscreen-symbolic",
                                     tooltip_text="전체화면 (F)")
        self._fs_button.connect("clicked", lambda *_: self.toggle_fullscreen())
        box.append(self._fs_button)

        return box

    # ── 설정·기록 ────────────────────────────────────────────────────────
    def _apply_settings(self) -> None:
        st = self.state.settings
        self.player.speed = st.speed
        self.player.volume = st.volume
        self.player.set_sub_style(font=st.sub_font, size=st.sub_font_size, color=st.sub_color)

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
        self.player.open(path, self._plan)
        self._current = path
        self._title.set_title(path.name)
        self._title.set_subtitle(str(path.parent))
        # 트랙 주입 직후에는 track_list 가 아직 안 채워져 있을 수 있다. 한 박자 뒤에 그린다.
        GLib.timeout_add(300, self._refresh_subtitle_menu_once)
        if self._plan is not None:
            self.toast(f"자막: {self._plan.summary()}")
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
        self._sync_play_button()
        hw = self.player.hwdec_current
        self._status.set_label("" if hw == "no" else f"하드웨어 디코딩: {hw}")
        return True

    def _on_close(self, *_args) -> bool:
        self._remember_position()
        self.state.settings.speed = self.player.speed
        self.state.settings.volume = self.player.volume
        self.state.settings.sub_font_size = self.player.sub_font_size
        self.state.settings.sub_font = self.player.sub_font
        self.state.settings.sub_color = self.player.sub_color
        self.state.save()
        self.player.close()
        return False
