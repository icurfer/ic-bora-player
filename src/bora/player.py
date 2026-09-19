"""libmpv 래퍼.

재생·디코딩·렌더는 전부 libmpv 에 맡긴다(기획서 §3-3). 이 파일은 그 위에 얇은 껍질만 씌운다.

실측으로 확인한 것(research 3):
- 콜백 타입 이름은 `mpv.MpvGlGetProcAddressFn` 이다. 인터넷 예제에 흔한
  `OpenGlCbGetProcAddrFn` 은 옛 이름이라 AttributeError 가 난다.
- `hwdec='auto-safe'` 가 실제로 고르는 것은 환경마다 다르다(lab 에서는 vulkan).
  특정 백엔드를 기대하지 말고 `hwdec_current` 를 읽어서 표시한다.
"""

from __future__ import annotations

import locale
from pathlib import Path
from typing import Callable

import mpv

from .log import debug_enabled, get as get_logger, mpv_log_handler
from .subtitle.sami import Track
from .util.gl import get_proc_address

log = get_logger("player")


def _force_c_numeric() -> None:
    """libmpv 는 LC_NUMERIC 이 C 가 아니면 초기화를 거부한다
    ("Non-C locale detected. This is not supported.").

    GTK 가 `setlocale(LC_ALL, "")` 을 부르면 ko_KR 로 바뀌므로, mpv 를 만들기 직전에
    되돌린다. 숫자 표기만 C 로 두는 것이라 UI 한글 표시에는 영향이 없다.
    (Celluloid 도 Flatpak 매니페스트에 `LC_NUMERIC=C` 를 박아 같은 문제를 피한다.)
    """
    try:
        locale.setlocale(locale.LC_NUMERIC, "C")
    except locale.Error:
        pass


class Player:
    """libmpv 인스턴스 하나와 그 렌더 컨텍스트를 소유한다."""

    def __init__(self, debug: bool | None = None, vo: str = "libmpv") -> None:
        """vo 는 기본이 'libmpv' — GLArea 렌더 컨텍스트로 직접 그린다.

        ⚠ vo='libmpv' 는 렌더 컨텍스트가 붙어야 디코딩이 진행된다. 창 없이 로직만 시험할 때는
        vo='null' 을 준다(대신 스크린샷처럼 렌더 결과가 필요한 기능은 동작하지 않는다).
        """
        _force_c_numeric()
        debug = debug_enabled() if debug is None else debug
        options = dict(
            vo=vo,                  # 렌더 컨텍스트로 직접 그린다
            hwdec="auto-safe",
            keep_open="yes",        # 끝나도 창을 닫지 않는다
            audio_pitch_correction=True,   # 속도를 바꿔도 목소리 음정이 유지된다
            osc=False,              # 자체 OSD 컨트롤을 쓰지 않는다. UI 는 우리가 그린다
            input_default_bindings=False,
        )
        if debug:
            # libmpv 로그를 파이썬 로거로 끌어온다 — 자막이 왜 저렇게 나오는지는
            # mpv 가 무엇을 열고 어떤 코드페이지를 썼는지 봐야 안다.
            options.update(log_handler=mpv_log_handler, loglevel="v")
        else:
            options.update(really_quiet=True)
        self._mpv = mpv.MPV(**options)
        log.debug("libmpv %s 시작 (debug=%s)", self._mpv.mpv_version, debug)
        self._ctx: mpv.MpvRenderContext | None = None
        self._update_cb: Callable[[], None] | None = None

    # ── 렌더 컨텍스트 ────────────────────────────────────────────────────
    def attach_render_context(self, on_update: Callable[[], None]) -> None:
        """GL 컨텍스트가 현재(current)인 상태에서 불러야 한다 — GLArea 의 realize 시점."""
        if self._ctx is not None:
            return
        self._update_cb = on_update
        self._ctx = mpv.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": mpv.MpvGlGetProcAddressFn(get_proc_address)},
        )
        self._ctx.update_cb = self._on_update

    def _on_update(self) -> None:
        if self._update_cb is not None:
            self._update_cb()

    def render(self, width: int, height: int, fbo: int) -> None:
        """GLArea 의 render 시그널에서 부른다. flip_y 를 주지 않으면 화면이 뒤집힌다."""
        if self._ctx is None:
            return
        self._ctx.render(flip_y=True, opengl_fbo={"w": width, "h": height, "fbo": fbo})

    # ── 재생 ─────────────────────────────────────────────────────────────
    def open(self, path: Path | str, plan=None) -> None:
        """영상을 연다. plan 이 있으면 자막 설정을 함께 적용한다.

        순서가 중요하다 — sub-codepage 와 sub-auto 는 파일을 열기 **전에** 정해야 하고,
        분리 트랙 주입(sub-add)은 파일이 열린 **뒤**여야 한다.
        """
        if plan is None:
            self._mpv.sub_auto = "fuzzy"
            self._mpv.sub_codepage = "auto"
            self._mpv.sub_stretch_durations = False
            self._set_sub_filters([])
        else:
            # 분리 트랙을 쓸 때는 원본 자막이 자동으로 붙지 않게 막는다(중복 트랙 방지).
            self._mpv.sub_auto = "no" if plan.split else "fuzzy"
            self._mpv.sub_codepage = plan.codepage or "auto"
            self._mpv.sub_stretch_durations = bool(plan.fallback_stretch)
            self._set_sub_filters(plan.sub_filters)

        log.info("열기: %s (codepage=%s, sub-auto=%s, 필터=%d개)",
                 Path(path).name, self._mpv.sub_codepage, self._mpv.sub_auto,
                 len(plan.sub_filters) if plan else 0)
        self._mpv.play(str(path))

        if plan is not None and plan.tracks:
            self._mpv.wait_until_playing(timeout=10)
            for index, track in enumerate(plan.tracks):
                # 첫 트랙(한국어가 앞에 오도록 정렬돼 있다)을 기본 선택한다.
                self.add_sub(track, select=(index == 0))

    def _set_sub_filters(self, patterns: list[str]) -> None:
        """`--sub-filter-regex` 를 갈아 끼운다. 빈 목록이면 필터를 끈다."""
        self._mpv.sub_filter_regex = list(patterns)
        self._mpv.sub_filter_regex_enable = bool(patterns)

    # ── 구간 반복 (A-B) ──────────────────────────────────────────────────
    # mpv 에 내장돼 있다(ab-loop-a / ab-loop-b). 직접 타이머로 되감는 것보다 정확하다
    # — 실측: 10~13초를 설정하면 그 안에서 정확히 맴돈다.
    OFF = "no"

    @property
    def loop_a(self) -> float | None:
        value = self._mpv.ab_loop_a
        return None if value in (None, self.OFF) else float(value)

    @property
    def loop_b(self) -> float | None:
        value = self._mpv.ab_loop_b
        return None if value in (None, self.OFF) else float(value)

    def set_loop(self, a: float | None, b: float | None) -> None:
        self._mpv.ab_loop_a = self.OFF if a is None else float(a)
        self._mpv.ab_loop_b = self.OFF if b is None else float(b)
        log.debug("구간 반복: %s ~ %s", a, b)

    def clear_loop(self) -> None:
        self.set_loop(None, None)

    @property
    def looping(self) -> bool:
        return self.loop_a is not None and self.loop_b is not None

    # ── 재생 속도 · 화면 ─────────────────────────────────────────────────
    SPEED_MIN, SPEED_MAX = 0.25, 4.0

    @property
    def speed(self) -> float:
        return float(self._mpv.speed or 1.0)

    @speed.setter
    def speed(self, value: float) -> None:
        value = max(self.SPEED_MIN, min(self.SPEED_MAX, float(value)))
        self._mpv.speed = value
        log.debug("재생 속도: %.2fx", value)

    def set_aspect(self, ratio: str) -> None:
        """'-1' 이면 원본. '16:9' '4:3' 같은 문자열도 mpv 가 그대로 받는다."""
        self._mpv.video_aspect_override = ratio
        log.debug("화면 비율: %s", ratio)

    @property
    def zoom(self) -> float:
        """mpv 의 video-zoom 은 로그 스케일이다(0 = 원본, 1 = 두 배)."""
        return float(self._mpv.video_zoom or 0.0)

    @zoom.setter
    def zoom(self, value: float) -> None:
        self._mpv.video_zoom = max(-2.0, min(2.0, float(value)))

    def screenshot(self, path: Path | str, include_subs: bool = True) -> Path:
        """지금 화면을 파일로 저장한다.

        'subtitles' 는 자막까지 포함한 화면, 'video' 는 영상만.
        (실측: vo=libmpv 렌더 경로에서도 동작한다.)
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._mpv.screenshot_to_file(str(path), includes="subtitles" if include_subs else "video")
        log.info("스크린샷: %s (자막 %s)", path, "포함" if include_subs else "제외")
        return path

    # ── 자막 모양 ────────────────────────────────────────────────────────
    def set_sub_style(self, font: str = "", size: int = 0, color: str = "",
                      pos: float | None = None) -> None:
        """국내 자막은 글자가 작아 안 보이는 일이 잦다. 크기를 키울 수 있어야 한다."""
        if font:
            self._mpv.sub_font = font
        if size:
            self._mpv.sub_font_size = int(size)
        if color:
            self._mpv.sub_color = color
        if pos is not None:
            self.sub_pos = pos

    # 자막 세로 위치. 0 = 화면 위, 100 = 기본(아래), 150 = 더 아래.
    # 강의 영상은 하단에 슬라이드 글자가 있어 자막이 겹치는 일이 잦다 — 위로 올릴 수 있어야 한다.
    SUB_POS_MIN, SUB_POS_MAX, SUB_POS_DEFAULT = 0, 150, 100

    @property
    def sub_pos(self) -> float:
        return float(self._mpv.sub_pos if self._mpv.sub_pos is not None else self.SUB_POS_DEFAULT)

    @sub_pos.setter
    def sub_pos(self, value: float) -> None:
        # ⚠ 범위를 벗어나면 mpv 가 TypeError 로 거부한다(실측: 200 은 거부). 여기서 잘라 둔다.
        clamped = max(self.SUB_POS_MIN, min(self.SUB_POS_MAX, float(value)))
        self._mpv.sub_pos = clamped
        log.debug("자막 위치: %.0f", clamped)

    @property
    def sub_font_size(self) -> int:
        return int(self._mpv.sub_font_size or 0)

    @property
    def sub_font(self) -> str:
        return str(self._mpv.sub_font or "")

    @property
    def sub_color(self) -> str:
        return str(self._mpv.sub_color or "")

    @property
    def pitch_correction(self) -> bool:
        return bool(self._mpv.audio_pitch_correction)

    def stop(self) -> None:
        """정지 — 처음으로 되돌리고 멈춘다. 파일은 열어 둔다(자막 트랙도 그대로).

        국내 플레이어의 정지 버튼 관례를 따른다. mpv 의 'stop' 명령은 파일을 닫아 버려서
        쓰지 않는다.
        """
        self.seek_absolute(0)
        self._mpv.pause = True
        log.debug("정지: 처음으로 되돌림")

    def reload_sub(self, path: Path | str | None = None) -> None:
        """자막을 다시 읽는다. path 를 주면 그 파일로 갈아 끼운다.

        실측(기획서 v0.2 §8-2): `sub-reload` 는 약 0.5초 걸리지만 재생은 끊기지 않는다.
        편집할 때마다 부르지 말고 **저장 시점에만** 부른다.
        """
        if path is not None:
            self._mpv.sub_add(str(path), "select")
        else:
            try:
                self._mpv.command("sub-reload")
            except (SystemError, OSError):
                pass
        # 파일에 싱크를 굳혔으면 delay 가 남아 있으면 안 된다 — 두 번 밀린다.
        self._mpv.sub_delay = 0.0
        log.info("자막 다시 읽기: %s", path or "(현재 트랙)")

    def add_sub(self, track: Track, select: bool = False) -> None:
        """분리한 자막 트랙을 주입한다. 제목·언어까지 넘겨야 트랙 메뉴에 제대로 보인다."""
        self._mpv.sub_add(str(track.path), "select" if select else "auto", track.title, track.lang)

    @property
    def sub_tracks(self) -> list[dict]:
        return [t for t in self._mpv.track_list if t.get("type") == "sub"]

    @property
    def audio_tracks(self) -> list[dict]:
        return [t for t in self._mpv.track_list if t.get("type") == "audio"]

    @property
    def audio_id(self):
        return self._mpv.aid

    @audio_id.setter
    def audio_id(self, value) -> None:
        self._mpv.aid = value
        log.debug("오디오 트랙 선택: %s", value)

    @property
    def sub_id(self):
        return self._mpv.sid

    @sub_id.setter
    def sub_id(self, value) -> None:
        self._mpv.sid = value

    @property
    def sub_delay(self) -> float:
        return float(self._mpv.sub_delay or 0.0)

    @sub_delay.setter
    def sub_delay(self, value: float) -> None:
        self._mpv.sub_delay = round(value, 3)

    @property
    def sub_text(self) -> str | None:
        return self._mpv.sub_text

    def toggle_pause(self) -> None:
        self._mpv.pause = not self._mpv.pause

    def seek_absolute(self, seconds: float) -> None:
        """정확한 위치로 이동한다.

        ⚠ `mpv.seek(x, reference="absolute")` 를 쓰면 안 된다 — python-mpv 1.0.8 의 그 래퍼는
           절대 seek 를 제대로 보내지 못하고 **0 근처로 되감긴다**(2026-09-14 실측:
           9.0초 요청 → 0.80초). 명령을 직접 보내야 한다.
           `absolute+exact` 는 키프레임이 아니라 요청한 지점으로 간다 — 자막 싱크를 맞추는
           도구이므로 정확도가 속도보다 중요하다.
        """
        try:
            self._mpv.command("seek", float(seconds), "absolute+exact")
        except Exception as exc:
            # 삼키기만 하면 왜 안 움직였는지 알 수 없다. 무시하되 남긴다.
            log.debug("seek(절대 %.2fs) 실패: %r", seconds, exc)

    def seek_relative(self, seconds: float) -> None:
        try:
            self._mpv.seek(seconds, reference="relative")
        except Exception as exc:
            log.debug("seek(상대 %+.2fs) 실패: %r", seconds, exc)

    # ── 상태 ─────────────────────────────────────────────────────────────
    @property
    def paused(self) -> bool:
        return bool(self._mpv.pause)

    @paused.setter
    def paused(self, value: bool) -> None:
        """읽기만 되고 쓰기가 안 되면 `toggle_pause()` 로 에둘러야 한다 —
        "지금 상태와 무관하게 재생시켜라"를 쓰려면 이쪽이 맞다."""
        self._mpv.pause = bool(value)

    @property
    def duration(self) -> float | None:
        return self._mpv.duration

    @property
    def time_pos(self) -> float | None:
        return self._mpv.time_pos

    @property
    def volume(self) -> float:
        return float(self._mpv.volume or 0)

    @volume.setter
    def volume(self, value: float) -> None:
        self._mpv.volume = max(0.0, min(130.0, value))

    @property
    def hwdec_current(self) -> str:
        return str(self._mpv.hwdec_current or "no")

    @property
    def media_title(self) -> str | None:
        return self._mpv.media_title

    def observe(self, name: str, handler: Callable) -> None:
        """mpv 프로퍼티 변화를 구독한다. 콜백은 mpv 스레드에서 불리므로
        UI 를 건드리려면 GLib.idle_add 로 넘겨야 한다."""
        self._mpv.observe_property(name, handler)

    # ── 정리 ─────────────────────────────────────────────────────────────
    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.free()
            except Exception:
                pass
            self._ctx = None
        try:
            self._mpv.terminate()
        except Exception:
            pass
