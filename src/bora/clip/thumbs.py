"""필름스트립 썸네일 — 보이는 것만, 게으르게, 백그라운드로.

**왜 이렇게 하나**(실측 `docs/research/2026-09-19-video-cut-concat-tests.md` §5):
`fps` 필터로 전체를 훑어 100장을 뽑으면 **291.8초** 걸린다. 타임라인을 열 때마다 5분을
기다릴 수는 없다. 개별 seek 로 뽑으면 장당 0.26초라 같은 100장이 26초다 — 11배 빠르다.

그래서 타임라인은 **즉시 열리고**, 그림은 뒤이어 채워진다. 확대하면 그 구간을 다시 뽑는다.
뽑은 것은 디스크에 캐시한다(지워도 되는 곳에).
"""

from __future__ import annotations

import hashlib
import queue
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

from ..log import get as get_logger  # noqa: E402

log = get_logger("clip.thumbs")

HEIGHT = 60             # px. 장당 약 3.2 KB 였다
TIMEOUT = 15            # 초. 한 장 뽑는 데 이보다 걸리면 뭔가 잘못된 것이다
# 같은 초를 두 번 뽑지 않도록 이 단위로 맞춘다. 타임라인을 조금 끌 때마다
# 새 좌표가 되어 버리면 캐시가 쓸모없어진다.
QUANTUM = 1.0


def cache_dir(video: Path) -> Path:
    """`~/.cache/bora/thumbs/<해시>/`. 통째로 지워도 앱에 지장이 없다."""
    digest = hashlib.sha1(str(Path(video).resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(GLib.get_user_cache_dir()) / "bora" / "thumbs" / digest


def snap(seconds: float) -> float:
    return round(max(0.0, seconds) / QUANTUM) * QUANTUM


class ThumbStrip:
    """한 영상의 썸네일 창고.

    `request()` 로 필요한 시각을 주면 백그라운드로 뽑고, 한 장 끝날 때마다 `on_ready` 를
    **메인 스레드에서** 부른다. `get()` 은 있으면 주고 없으면 None — 호출 쪽은 없는 자리를
    빈칸으로 그리면 된다.
    """

    def __init__(self, video: Path, on_ready=None) -> None:
        self.video = Path(video)
        self.on_ready = on_ready
        self._cache: dict[float, GdkPixbuf.Pixbuf] = {}
        self._missing: set[float] = set()       # 뽑아 봤지만 실패한 것 — 다시 시도하지 않는다
        self._queue: queue.Queue = queue.Queue()
        self._pending: set[float] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._dir = cache_dir(self.video)

    # ── 바깥에서 쓰는 것 ─────────────────────────────────────────────────
    def get(self, seconds: float) -> GdkPixbuf.Pixbuf | None:
        return self._cache.get(snap(seconds))

    def request(self, times: list[float]) -> None:
        """이 시각들이 필요하다. 이미 있거나 줄 서 있는 것은 건너뛴다."""
        fresh = []
        with self._lock:
            for raw in times:
                at = snap(raw)
                if at in self._cache or at in self._pending or at in self._missing:
                    continue
                self._pending.add(at)
                fresh.append(at)
        for at in fresh:
            self._queue.put(at)
        if fresh:
            self._ensure_worker()

    def cancel(self) -> None:
        """줄 서 있는 것을 버린다. 이미 뽑는 중인 한 장은 끝까지 간다(곧 끝난다)."""
        with self._lock:
            self._pending.clear()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def close(self) -> None:
        self._stop.set()
        self.cancel()
        self._queue.put(None)

    # ── 내부 ─────────────────────────────────────────────────────────────
    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._pump, daemon=True)
        self._worker.start()

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                at = self._queue.get(timeout=2.0)
            except queue.Empty:
                return                          # 할 일이 없으면 조용히 물러난다
            if at is None:
                return
            with self._lock:
                if at not in self._pending:     # 그 사이 취소됐다
                    continue
            pixbuf = self._load_or_extract(at)
            with self._lock:
                self._pending.discard(at)
                if pixbuf is not None:
                    self._cache[at] = pixbuf
                else:
                    self._missing.add(at)
            if pixbuf is not None and self.on_ready:
                GLib.idle_add(self.on_ready, at)

    def _load_or_extract(self, at: float) -> GdkPixbuf.Pixbuf | None:
        path = self._dir / f"{int(at)}.jpg"
        if path.is_file():
            try:
                return GdkPixbuf.Pixbuf.new_from_file(str(path))
            except GLib.Error:
                path.unlink(missing_ok=True)    # 깨진 캐시는 버리고 다시 뽑는다
        if not self._extract(at, path):
            return None
        try:
            return GdkPixbuf.Pixbuf.new_from_file(str(path))
        except GLib.Error as exc:
            log.debug("썸네일을 읽지 못했다 %.0f초: %s", at, exc)
            return None

    def _extract(self, at: float, out: Path) -> bool:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("썸네일 캐시 폴더를 만들지 못했다: %s", exc)
            return False
        # `-ss` 를 `-i` 앞에 — 키프레임으로 건너뛴다. 장당 0.26초의 근거다.
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-ss", f"{at:.3f}", "-i", str(self.video),
            "-frames:v", "1", "-vf", f"scale=-1:{HEIGHT}", str(out),
        ]
        try:
            done = subprocess.run(command, capture_output=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("썸네일 추출 실패 %.0f초: %s", at, exc)
            return False
        if done.returncode != 0 or not out.is_file():
            log.debug("썸네일 없음 %.0f초 (코드 %s)", at, done.returncode)
            return False
        return True
