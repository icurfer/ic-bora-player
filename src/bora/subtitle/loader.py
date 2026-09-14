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
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..log import get as get_logger
from .detect import DetectResult, detect
from .sami import Track, looks_like_sami, split_to_files

log = get_logger("subtitle")

# mpv 가 자동으로 찾아 주는 자막 확장자 가운데 우리가 다루는 것들
SUB_SUFFIXES = (".smi", ".sami", ".srt", ".ass", ".ssa", ".sub", ".vtt")

# 국내 자막에서 아주 흔한 결함: SAMI 를 SRT 로 변환할 때 종료 신호 `&nbsp;` 가
# **텍스트로 그대로 남는다.** 그러면 그 큐가 화면에 '빈 칸'으로 찍혀서
# 사용자에게는 "자막이 안 나온다"로 보인다.
# (실측: 실제 영화 자막 2665 큐 중 1332 개(50%)가 이랬다 — research 5)
#
# 파일을 다시 쓰지 않고 mpv 의 `--sub-filter-regex` 로 그 줄을 통째로 버린다.
# POSIX ERE 이고, 줄 전체가 엔티티·공백뿐일 때만 지운다.
EMPTY_CUE_REGEX = r"^(&nbsp;|&#160;|&#xa0;|\s)*$"
# 파일에 이 엔티티가 하나라도 있으면 필터를 켠다(없으면 켤 이유가 없다).
_ENTITY_PROBE = re.compile(rb"&(nbsp|#160|#xa0);", re.I)


@dataclass
class Plan:
    """자막 하나를 어떻게 넘길지에 대한 계획."""

    source: Path
    detect: DetectResult
    tracks: list[Track] = field(default_factory=list)
    fallback_stretch: bool = False
    empty_cue_filter: bool = False      # `&nbsp;` 만 있는 큐를 버릴 것인가
    empty_cue_count: int = 0            # 몇 개나 있었는지 (UI·로그용)

    @property
    def sub_filters(self) -> list[str]:
        return [EMPTY_CUE_REGEX] if self.empty_cue_filter else []

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
        parts = [f"{enc}{badge}"]
        if self.tracks:
            langs = "/".join(t.lang for t in self.tracks)
            parts.append(f"트랙 {len(self.tracks)}개 [{langs}]")
        if self.empty_cue_filter:
            parts.append(f"빈 큐 {self.empty_cue_count}개 정리")
        return " · ".join(parts)


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

    # SAMI 든 SRT 든, 엔티티만 있는 큐는 화면에 빈 칸으로 찍힌다. 먼저 센다.
    hits = len(_ENTITY_PROBE.findall(raw))
    if hits:
        plan.empty_cue_filter = True
        plan.empty_cue_count = hits
    log.debug("자막 %s: %s (엔티티 큐 %d개)", subtitle.name, result.reason, hits)

    if not looks_like_sami(raw):
        return plan                      # SRT/ASS 등은 인코딩 주입 + 필터로 끝난다

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
        log.info("자막을 찾지 못했다: %s", video.name)
        return None
    plan = prepare(video, subtitle, cache_base)
    log.info("자막 계획: %s (%s)", plan.summary(), subtitle.name)
    return plan
