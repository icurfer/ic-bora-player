"""트랙 이름을 사람이 읽을 수 있게 만든다.

mpv 가 주는 트랙 정보는 `lang='eng'`, `title='Commentary'`, `codec='dvd_subtitle'` 같은 조각이라
그대로 메뉴에 쓰면 무슨 트랙인지 알기 어렵다. 여기서 한 줄짜리 이름으로 합친다.
"""

from __future__ import annotations

# ISO 639-2/B · 639-1 혼용. 국내 사용자가 만날 법한 것 위주로 둔다.
LANG_NAMES = {
    "kor": "한국어", "ko": "한국어",
    "eng": "영어", "en": "영어",
    "jpn": "일본어", "ja": "일본어",
    "chi": "중국어", "zho": "중국어", "zh": "중국어",
    "fre": "프랑스어", "fra": "프랑스어", "fr": "프랑스어",
    "ger": "독일어", "deu": "독일어", "de": "독일어",
    "spa": "스페인어", "es": "스페인어",
    "ita": "이탈리아어", "it": "이탈리아어",
    "rus": "러시아어", "ru": "러시아어",
    "por": "포르투갈어", "pt": "포르투갈어",
    "tha": "태국어", "vie": "베트남어", "ind": "인도네시아어",
    "ara": "아랍어", "hin": "힌디어", "tur": "터키어", "pol": "폴란드어",
    "nld": "네덜란드어", "dut": "네덜란드어", "swe": "스웨덴어", "dan": "덴마크어",
    "fin": "핀란드어", "nor": "노르웨이어", "ces": "체코어", "cze": "체코어",
    "hun": "헝가리어", "ell": "그리스어", "gre": "그리스어", "heb": "히브리어",
    "und": "언어 미상",
}

# 글자가 아니라 이미지로 된 자막. 싱크 조절은 되지만 인코딩 전처리는 의미가 없다.
IMAGE_SUB_CODECS = {"dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle", "xsub"}


def language_name(code: str | None) -> str:
    if not code:
        return ""
    return LANG_NAMES.get(code.lower(), code)


def _channels(track: dict) -> str:
    count = track.get("demux-channel-count") or track.get("audio-channels")
    if not count:
        return ""
    return {1: "모노", 2: "스테레오"}.get(count, f"{count}채널")


def track_label(track: dict) -> str:
    """메뉴에 보일 한 줄. 예) '영어 · Commentary · 스테레오', '한국어 (외부)'"""
    parts: list[str] = []

    lang = language_name(track.get("lang"))
    if lang:
        parts.append(lang)

    title = (track.get("title") or "").strip()
    # 'srt' 처럼 확장자만 든 제목은 정보가 없다. 언어가 이미 있으면 버린다.
    if title and title.lower() not in {lang.lower(), "srt", "ass", "smi", "sub", "vtt"}:
        parts.append(title)

    if track.get("type") == "audio":
        ch = _channels(track)
        if ch:
            parts.append(ch)

    label = " · ".join(parts) or f"트랙 {track.get('id')}"

    if track.get("type") == "sub" and track.get("codec") in IMAGE_SUB_CODECS:
        label += " [이미지]"
    if track.get("external"):
        label += " (외부)"
    if track.get("default"):
        label += " ★"
    return label
