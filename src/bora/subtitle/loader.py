"""자막 하나를 보고 '무엇을 할지' 정하는 층.

실측(docs/research/2026-09-13-mpv-playback-path-tests.md §4)이 정해 준 원칙:

1. **인코딩은 파일을 다시 쓰지 않는다.** 판정 결과를 `--sub-codepage=+<enc>` 로 주입하면
   mpv 의 자체 탐지를 완전히 우회한다.
2. **파일을 만드는 것은 한·영 통합 SAMI 일 때뿐이다.** 단일 언어 자막은 손대지 않는다.
3. 분리가 안 되는 SAMI 는 `--sub-stretch-durations` 를 켜서 최소한 한글이 보이게 한다.
   단 한·영이 겹쳐 보이므로 **기본값으로 삼지 않는다.**
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .detect import DetectResult, detect
from .sami import Track, looks_like_sami, split_to_files

# mpv 가 자동으로 찾아 주는 자막 확장자 가운데 우리가 다루는 것들
SUB_SUFFIXES = (".smi", ".sami", ".srt", ".ass", ".ssa", ".sub", ".vtt")


@dataclass
class Plan:
    """자막 하나를 어떻게 넘길지에 대한 계획."""

    source: Path
    detect: DetectResult
    tracks: list[Track] = field(default_factory=list)
    fallback_stretch: bool = False

    @property
    def codepage(self) -> str | None:
        """mpv 에 넘길 `--sub-codepage` 값. 분리 트랙을 쓸 때는 필요 없다
        (우리가 이미 UTF-8 로 써 두었기 때문)."""
        if self.tracks:
            return None
        return self.detect.mpv_codepage

    @property
    def split(self) -> bool:
        return bool(self.tracks)

    def summary(self) -> str:
        """UI 상태 표시줄에 그대로 쓸 한 줄."""
        enc = self.detect.encoding.upper()
        badge = "" if self.detect.confident else " (추정)"
        if self.tracks:
            langs = "/".join(t.lang for t in self.tracks)
            return f"{enc}{badge} · 트랙 {len(self.tracks)}개 [{langs}]"
        return f"{enc}{badge}"


def find_sidecar(video: Path) -> Path | None:
    """같은 폴더에서 동명 자막을 찾는다.

    mpv 의 `sub-auto=fuzzy` 도 같은 일을 하지만, 우리는 **파일을 먼저 읽어 판정**해야 하므로
    직접 찾는다. 정확히 같은 이름을 우선하고, 없으면 `영상이름.*` 접두 일치를 본다
    (`movie.ko.smi` 같은 국내 관례).
    """
    if not video.exists():
        return None
    folder = video.parent
    stem = video.stem
    for suffix in SUB_SUFFIXES:
        exact = folder / (stem + suffix)
        if exact.is_file():
            return exact
    candidates = sorted(
        p for p in folder.glob(stem + ".*")
        if p.is_file() and p.suffix.lower() in SUB_SUFFIXES
    )
    return candidates[0] if candidates else None


def cache_dir_for(video: Path, base: Path) -> Path:
    """영상마다 고유한 임시 폴더. 원본 폴더에는 절대 쓰지 않는다
    (읽기 전용 매체일 수 있고, 사용자의 폴더를 어지럽히지 않는다)."""
    key = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return base / key


def prepare(video: Path, subtitle: Path, cache_base: Path) -> Plan:
    """자막 파일 하나를 보고 계획을 세운다. 파일을 만들 수도 있다."""
    raw = subtitle.read_bytes()
    result = detect(raw)
    plan = Plan(source=subtitle, detect=result)

    if not looks_like_sami(raw):
        return plan                      # SRT/ASS 등은 인코딩 주입으로 끝난다

    outdir = cache_dir_for(video, cache_base)
    try:
        plan.tracks = split_to_files(raw, result.encoding, outdir, stem=video.stem)
    except Exception:
        # 파싱에 실패해도 재생 자체를 막지 않는다. 원본을 그대로 쓰고 폴백을 켠다.
        plan.tracks = []
        plan.fallback_stretch = True
        return plan

    if not plan.tracks:
        # 단일 클래스 SAMI. 분리할 것이 없으니 원본을 그대로 쓴다.
        # 같은 시각 SYNC 가 이어지는 파일이면 0초 큐가 생길 수 있어 폴백을 켜 둔다.
        plan.fallback_stretch = True
    return plan


def prepare_for_video(video: Path, cache_base: Path, explicit: Path | None = None) -> Plan | None:
    """영상에 딸린 자막을 찾아 계획을 세운다. 자막이 없으면 None."""
    subtitle = explicit or find_sidecar(video)
    if subtitle is None or not subtitle.is_file():
        return None
    return prepare(video, subtitle, cache_base)
