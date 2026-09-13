"""SAMI 파서·분리기.

국내 관례인 한·영 통합 SAMI(`<P Class=KRCC>` / `<P Class=ENCC>`)를 **언어 클래스별 트랙**으로 나눈다.
ffmpeg 의 samidec 는 Class 를 보지 않아 한 스트림에 섞고(P3), 같은 시각의 SYNC 가 이어지면
앞 큐가 0초가 되어 한글이 아예 안 보인다(P4).

큐 끝을 **같은 클래스의 다음 SYNC** 로 잡으면 두 문제가 함께 사라진다 — 실측으로 확인했다
(docs/research/2026-09-13-mpv-playback-path-tests.md §3).
프로토타입: docs/research/scripts/sami_split.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SYNC_RE = re.compile(r"<SYNC\s+Start\s*=\s*(\d+)[^>]*>", re.I)
_P_RE = re.compile(r"<P(?:\s+[^>]*)?>", re.I)
_CLASS_RE = re.compile(r"Class\s*=\s*[\"']?([A-Za-z0-9_-]+)", re.I)
_LANG_RE = re.compile(r"\.(\w+)\s*\{[^}]*?lang\s*:\s*([A-Za-z-]+)", re.I | re.S)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]*>")
_BODY_RE = re.compile(r"<BODY[^>]*>", re.I)

# 클래스 이름 관례. <STYLE> 의 lang: 이 있으면 그쪽이 우선이다.
_CLASS_LANG = {"KRCC": "ko", "ENCC": "en", "JPCC": "ja", "CNCC": "zh"}

# 마지막 큐에는 끝 시각이 없다. 이만큼 보여주고 끝낸다.
_TAIL_MS = 4000
# 같은 클래스 안에서 시각이 겹치면 최소한 이만큼은 보여준다.
_MIN_MS = 2000

_NBSP = "\xa0"


@dataclass(frozen=True)
class Cue:
    start_ms: int
    text: str

    @property
    def is_terminator(self) -> bool:
        """`&nbsp;` 단독 큐 — '여기서 자막을 지워라'는 국내 관례의 종료 신호."""
        return not self.text.strip() or self.text.strip() == _NBSP


@dataclass(frozen=True)
class Track:
    path: Path
    lang: str       # mpv 의 lang 인자로 넘긴다
    title: str      # 트랙 메뉴에 보일 이름
    cue_count: int


def parse(text: str) -> tuple[dict[str, list[Cue]], dict[str, str]]:
    """-> ({클래스: [Cue]}, {클래스: lang})"""
    langs = {k.upper(): v for k, v in _LANG_RE.findall(text)}
    body = _BODY_RE.split(text)[-1]

    cues: dict[str, list[Cue]] = {}
    last_class = "UNKNOWN"
    parts = _SYNC_RE.split(body)
    for i in range(1, len(parts), 2):
        start = int(parts[i])
        chunk = parts[i + 1]

        cls = last_class
        m = _P_RE.search(chunk)
        if m:
            cm = _CLASS_RE.search(m.group(0))
            if cm:
                cls = cm.group(1).upper()
        last_class = cls

        raw = _P_RE.sub("", chunk)
        raw = _BR_RE.sub("\n", raw)
        plain = _TAG_RE.sub("", raw)
        plain = (plain.replace("&nbsp;", _NBSP).replace("&amp;", "&")
                      .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
        plain = "\n".join(line.strip() for line in plain.strip().split("\n")).strip()
        cues.setdefault(cls, []).append(Cue(start, plain))
    return cues, langs


def _fmt(ms: int) -> str:
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def to_srt(cues: list[Cue]) -> str:
    """같은 클래스 안에서만 끝 시각을 계산한다 — 이것이 0초 큐를 없애는 핵심이다."""
    out: list[str] = []
    n = 0
    for i, cue in enumerate(cues):
        if cue.is_terminator:
            continue                      # 종료 신호는 출력하지 않는다
        end = cues[i + 1].start_ms if i + 1 < len(cues) else cue.start_ms + _TAIL_MS
        if end <= cue.start_ms:
            end = cue.start_ms + _MIN_MS
        n += 1
        out.append("%d\n%s --> %s\n%s\n" % (n, _fmt(cue.start_ms), _fmt(end), cue.text))
    return "\n".join(out)


def language_of(cls: str, langs: dict[str, str]) -> str:
    """<STYLE> 의 lang: 우선, 없으면 클래스 이름 관례, 그래도 없으면 클래스 이름 그대로."""
    lang = langs.get(cls)
    if lang:
        return lang.split("-")[0].lower()
    return _CLASS_LANG.get(cls, cls.lower())


def looks_like_sami(raw: bytes) -> bool:
    head = raw[:4096].upper()
    return b"<SAMI" in head or (b"<SYNC" in head and b"<P" in head)


def split_to_files(raw: bytes, encoding: str, outdir: Path, stem: str = "sub") -> list[Track]:
    """클래스가 2개 이상인 SAMI 를 클래스별 UTF-8 SRT 로 쓴다.

    클래스가 하나뿐이면 **빈 리스트**를 반환한다 — 분리할 이유가 없고, 원본을 그대로 쓰는 편이
    낫다(인코딩만 주입하면 된다).
    """
    text = raw.decode(encoding, errors="replace")
    cues, langs = parse(text)

    usable = {cls: lst for cls, lst in cues.items() if any(not c.is_terminator for c in lst)}
    if len(usable) < 2:
        return []

    outdir.mkdir(parents=True, exist_ok=True)
    tracks: list[Track] = []
    for cls, lst in usable.items():
        body = to_srt(lst)
        if not body.strip():
            continue
        lang = language_of(cls, langs)
        path = outdir / f"{stem}.{lang}.srt"
        path.write_text(body, encoding="utf-8")
        title = f"{lang.upper()} ({cls})"
        tracks.append(Track(path, lang, title, body.count(" --> ")))

    # 한국어를 앞에 둔다 — 기본 선택 대상이다(기획서 §5-2 ②).
    tracks.sort(key=lambda t: (t.lang != "ko", t.lang))
    return tracks
