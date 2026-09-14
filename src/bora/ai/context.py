"""질문에 딸려 보낼 맥락을 조립한다.

무턱대고 자막 전체를 넣으면 비싸고 느리다. 층을 나눈다(기획서 v0.3 §4-4):

    system  : 역할 지시                          ← 고정 (캐시)
    [캐시]  : 강의 자막 전체 (있으면)             ← 강의마다 한 번 (캐시)
    user    : 지금 시점 앞뒤 자막 + 메모 + 질문   ← 매번 바뀜

**고정 부분을 앞에, 바뀌는 부분을 뒤에** 둔다 — 프롬프트 캐싱은 접두 일치라 순서가 중요하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..log import get as get_logger
from ..subtitle.model import SubtitleDocument, ms_to_srt

log = get_logger("ai.context")

SYSTEM = (
    "너는 강의를 보며 공부하는 사람을 돕는다. 한국어로 간결하게 답한다.\n"
    "- 자막과 메모에 있는 내용을 근거로 답한다.\n"
    "- 거기 없는 것은 추측하지 말고 모른다고 말한다. 일반 지식으로 답할 때는 그렇다고 밝힌다.\n"
    "- 학습자가 이어서 메모할 수 있게 짧게 쓴다. 서론·맺음말을 넣지 않는다."
)

# 지금 시점 앞뒤로 얼마나 가져올지(초). 5분이면 맥락은 충분하고 토큰은 감당된다.
WINDOW_SECONDS = 300
# 자막 전체를 캐시에 올릴지 판단하는 기준. 너무 짧으면 캐시가 걸리지 않는다.
MIN_CACHE_CHARS = 2000
# 메모에서 앞뒤로 가져올 줄 수
NOTE_LINES = 12


@dataclass
class Question:
    text: str
    position: float = 0.0
    video_title: str = ""
    subtitle_path: Path | None = None
    note_text: str = ""
    note_line: int = -1
    model: str = "claude-opus-5"
    full_subtitle: str = field(default="", repr=False)
    nearby_subtitle: str = field(default="", repr=False)
    note_excerpt: str = field(default="", repr=False)


def _load_subtitle(path: Path | None) -> list:
    if path is None or not Path(path).is_file():
        return []
    try:
        return SubtitleDocument.load(Path(path)).cues
    except Exception as exc:
        log.debug("자막을 맥락으로 읽지 못했다: %s", exc)
        return []


def _cues_to_text(cues, start_ms: int | None = None, end_ms: int | None = None) -> str:
    lines = []
    for cue in cues:
        if start_ms is not None and cue.end_ms < start_ms:
            continue
        if end_ms is not None and cue.start_ms > end_ms:
            break
        body = " ".join(cue.text.split())
        if body:
            lines.append(f"[{ms_to_srt(cue.start_ms)[:8]}] {body}")
    return "\n".join(lines)


def _note_excerpt(note_text: str, line: int) -> str:
    """메모에서 커서 부근만. 전체를 보내면 길고, 지금 묻는 것과 무관한 내용이 섞인다."""
    if not note_text:
        return ""
    lines = note_text.splitlines()
    if line < 0:
        return "\n".join(lines[-NOTE_LINES:])
    lo = max(0, line - NOTE_LINES // 2)
    return "\n".join(lines[lo:lo + NOTE_LINES])


def build(question: Question) -> Question:
    """맥락을 채워 돌려준다. 원본을 바꾸지 않는다."""
    cues = _load_subtitle(question.subtitle_path)
    full = _cues_to_text(cues)
    here = int(question.position * 1000)
    nearby = _cues_to_text(cues, here - WINDOW_SECONDS * 1000, here + WINDOW_SECONDS * 1000)

    question.full_subtitle = full if len(full) >= MIN_CACHE_CHARS else ""
    question.nearby_subtitle = nearby
    question.note_excerpt = _note_excerpt(question.note_text, question.note_line)
    log.debug("맥락: 자막 전체 %d자, 부근 %d자, 메모 %d자",
              len(question.full_subtitle), len(nearby), len(question.note_excerpt))
    return question


def to_request(question: Question) -> dict:
    """worker 에 넘길 요청. 캐시가 걸리도록 **고정 → 가변** 순서를 지킨다."""
    system: list[dict] = [{"type": "text", "text": SYSTEM}]
    if question.full_subtitle:
        # 강의마다 한 번만 값을 치르고 이후 질문은 캐시를 읽는다.
        system.append({
            "type": "text",
            "text": f"# 강의 자막 전체: {question.video_title}\n\n{question.full_subtitle}",
            "cache_control": {"type": "ephemeral"},
        })

    parts = []
    if question.nearby_subtitle:
        parts.append(f"## 지금 보고 있는 대목 ({ms_to_srt(int(question.position * 1000))[:8]} 근처)\n"
                     f"{question.nearby_subtitle}")
    if question.note_excerpt:
        parts.append(f"## 내 메모\n{question.note_excerpt}")
    parts.append(f"## 질문\n{question.text}")

    return {
        "model": question.model,
        "system": system,
        "user": "\n\n".join(parts),
    }
