# -*- coding: utf-8 -*-
"""트랙 이름 표시 회귀 테스트.

mpv 가 주는 조각(lang/title/codec)을 사람이 읽을 수 있는 한 줄로 만드는지 고정한다.
실제 영화(Inside Out)의 트랙 구성을 그대로 표본으로 쓴다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.tracks import IMAGE_SUB_CODECS, language_name, track_label  # noqa: E402


def test_language_names_are_korean() -> None:
    assert language_name("kor") == "한국어"
    assert language_name("eng") == "영어"
    assert language_name("fre") == "프랑스어"
    assert language_name("spa") == "스페인어"
    assert language_name("jpn") == "일본어"


def test_unknown_language_falls_back_to_code() -> None:
    assert language_name("xyz") == "xyz"
    assert language_name(None) == ""
    assert language_name("") == ""


def test_image_subtitle_is_marked() -> None:
    """이미지 자막은 인코딩 전처리가 통하지 않는다. 사용자가 구분할 수 있어야 한다."""
    label = track_label({"id": 1, "type": "sub", "lang": "eng", "codec": "dvd_subtitle"})
    assert label == "영어 [이미지]"
    assert "dvd_subtitle" in IMAGE_SUB_CODECS


def test_commentary_track_keeps_title() -> None:
    label = track_label({"id": 2, "type": "sub", "lang": "eng",
                         "title": "Commentary", "codec": "dvd_subtitle"})
    assert label == "영어 · Commentary [이미지]"


def test_external_subtitle_is_marked() -> None:
    label = track_label({"id": 7, "type": "sub", "lang": "kor",
                         "codec": "subrip", "external": True})
    assert label == "한국어 (외부)"


def test_useless_title_is_dropped() -> None:
    """제목이 'srt' 뿐이면 정보가 없다. 언어가 있으면 버린다."""
    label = track_label({"id": 7, "type": "sub", "lang": "kor",
                         "title": "srt", "codec": "subrip", "external": True})
    assert label == "한국어 (외부)"


def test_audio_shows_channels_and_default() -> None:
    label = track_label({"id": 1, "type": "audio", "lang": "eng",
                         "demux-channel-count": 8, "default": True})
    assert label == "영어 · 8채널 ★"
    stereo = track_label({"id": 2, "type": "audio", "lang": "eng",
                          "title": "Commentary", "demux-channel-count": 2})
    assert stereo == "영어 · Commentary · 스테레오"


def test_nameless_track_falls_back_to_id() -> None:
    assert track_label({"id": 3, "type": "sub", "codec": "subrip"}) == "트랙 3"
