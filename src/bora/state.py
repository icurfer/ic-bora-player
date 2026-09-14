"""설정·이어보기·최근 파일 — JSON 파일 하나로 관리한다.

`~/.config/bora/state.json` (XDG 를 따른다).

원칙:
- **읽기 실패가 앱을 막지 않는다.** 깨진 파일은 옆에 치워 두고 기본값으로 시작한다.
- **원자적으로 쓴다.** 임시 파일에 쓰고 rename — 쓰다가 죽어도 반쪽 파일이 남지 않는다.
- 사생활: 이어보기·최근 파일은 끌 수 있고, 목록을 비울 수 있다(기획서 §6).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .log import get as get_logger

log = get_logger("state")

SCHEMA = 1
MAX_RECENT = 20
# 이 비율을 넘겨 봤으면 '다 본 것'으로 치고 이어보기를 묻지 않는다.
WATCHED_RATIO = 0.95
# 너무 앞이면 이어볼 의미가 없다.
MIN_RESUME_SECONDS = 30.0


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "bora"


def _key(path: Path) -> str:
    """파일을 가리키는 안정된 열쇠. 경로가 길거나 특수문자여도 안전하다."""
    return hashlib.sha1(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:16]


@dataclass
class Pin:
    """영상에 꽂아 둔 표시.

    `end` 가 없으면 **시점 핀**(그 자리로 이동), 있으면 **구간 핀**(A-B 반복을 건다).
    둘을 한 모델로 두면 목록·이동·삭제를 한 번만 만들면 된다.
    """

    start: float
    end: float | None = None
    label: str = ""
    created: float = field(default_factory=time.time)

    @property
    def is_range(self) -> bool:
        return self.end is not None and self.end > self.start

    @property
    def length(self) -> float:
        return (self.end - self.start) if self.is_range else 0.0


@dataclass
class RecentItem:
    path: str
    title: str = ""
    position: float = 0.0
    duration: float = 0.0
    finished: bool = False
    sub_track: str = ""
    pins: list = field(default_factory=list)        # [{start, end, label, created}]
    updated: float = field(default_factory=time.time)

    @property
    def resumable(self) -> bool:
        if self.finished or self.position < MIN_RESUME_SECONDS:
            return False
        if self.duration and self.position / self.duration >= WATCHED_RATIO:
            return False
        return True


@dataclass
class Settings:
    remember_position: bool = True
    keep_recent: bool = True
    speed: float = 1.0
    sub_font_size: int = 0          # 0 이면 mpv 기본값을 쓴다
    sub_font: str = ""
    sub_color: str = ""
    screenshot_dir: str = ""
    volume: float = 100.0
    # 기본 영상 플레이어를 Bora 로 바꾸기 전의 값. 끌 때 정확히 되돌리려고 들고 있는다.
    previous_defaults: dict = field(default_factory=dict)


class State:
    """설정과 기록. 만들자마자 읽고, 바꾸면 save() 를 부른다."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = Path(directory) if directory else config_dir()
        self.path = self.dir / "state.json"
        self.settings = Settings()
        self.recent: dict[str, RecentItem] = {}
        self.load()

    # ── 입출력 ───────────────────────────────────────────────────────────
    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # 깨진 설정 때문에 앱이 안 뜨면 안 된다. 치워 두고 기본값으로 간다.
            log.warning("설정을 읽지 못했다(%s). 기본값으로 시작한다.", exc)
            try:
                self.path.replace(self.path.with_suffix(".json.broken"))
            except OSError:
                pass
            return

        known = {f for f in Settings.__dataclass_fields__}
        for key, value in (raw.get("settings") or {}).items():
            if key in known:
                setattr(self.settings, key, value)

        for key, item in (raw.get("recent") or {}).items():
            try:
                self.recent[key] = RecentItem(**item)
            except TypeError:
                continue        # 형식이 바뀐 항목은 조용히 버린다
        log.debug("설정 로드: 최근 %d개", len(self.recent))

    def save(self) -> None:
        data = {
            "schema": SCHEMA,
            "settings": asdict(self.settings),
            "recent": {k: asdict(v) for k, v in self.recent.items()},
        }
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)          # 원자적 교체
        except OSError as exc:
            log.warning("설정을 저장하지 못했다: %s", exc)

    # ── 이어보기·최근 파일 ───────────────────────────────────────────────
    def note_playback(self, path: Path, position: float, duration: float,
                      title: str = "", sub_track: str = "") -> None:
        if not self.settings.keep_recent and not self.settings.remember_position:
            return
        finished = bool(duration) and position / duration >= WATCHED_RATIO
        key = _key(path)
        previous = self.recent.get(key)
        item = RecentItem(
            path=str(Path(path).resolve()),
            title=title or Path(path).name,
            position=0.0 if finished else float(position or 0.0),
            duration=float(duration or 0.0),
            finished=finished,
            sub_track=sub_track,
            # 재생 위치를 기록한다고 핀을 잃으면 안 된다.
            pins=list(previous.pins) if previous else [],
        )
        self.recent[key] = item
        self._trim()

    def resume_for(self, path: Path) -> float | None:
        """이어볼 위치. 없으면 None."""
        if not self.settings.remember_position:
            return None
        item = self.recent.get(_key(path))
        if item is None or not item.resumable:
            return None
        return item.position

    # ── 핀 ───────────────────────────────────────────────────────────────
    def pins_for(self, path: Path) -> list[Pin]:
        item = self.recent.get(_key(path))
        if item is None:
            return []
        out: list[Pin] = []
        for raw in item.pins:
            try:
                out.append(Pin(**raw) if isinstance(raw, dict) else raw)
            except TypeError:
                continue        # 형식이 바뀐 항목은 조용히 버린다
        return sorted(out, key=lambda p: p.start)

    def add_pin(self, path: Path, pin: Pin) -> None:
        key = _key(path)
        item = self.recent.get(key)
        if item is None:
            item = RecentItem(path=str(Path(path).resolve()), title=Path(path).name)
            self.recent[key] = item
        item.pins.append(asdict(pin))
        self.save()

    def remove_pin(self, path: Path, index: int) -> bool:
        pins = self.pins_for(path)
        if not (0 <= index < len(pins)):
            return False
        target = pins[index]
        item = self.recent[_key(path)]
        item.pins = [p for p in item.pins
                     if not (abs((p.get("start") if isinstance(p, dict) else p.start)
                                 - target.start) < 0.001)]
        self.save()
        return True

    def recent_items(self) -> list[RecentItem]:
        """최근 순. 사라진 파일은 걸러 낸다."""
        items = [i for i in self.recent.values() if Path(i.path).exists()]
        return sorted(items, key=lambda i: i.updated, reverse=True)

    def forget_all(self) -> None:
        self.recent.clear()
        self.save()

    def _trim(self) -> None:
        if len(self.recent) <= MAX_RECENT:
            return
        ordered = sorted(self.recent.items(), key=lambda kv: kv[1].updated, reverse=True)
        self.recent = dict(ordered[:MAX_RECENT])
