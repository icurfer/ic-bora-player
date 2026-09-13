# -*- coding: utf-8 -*-
"""인코딩 판정 회귀 테스트.

docs/research/scripts/pipeline.py 의 11케이스를 그대로 고정한다.
표본이 없으면 fixtures/make_fixtures.py 로 만든다.
"""

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.subtitle.detect import (  # noqa: E402
    HANGUL_MIN,
    detect,
    hangul_ratio,
    strip_markup,
)

# 파일 -> 기대 인코딩. research 2 §2-3 의 실측 결과다.
EXPECT = {
    "sample_cp949.smi": "cp949",
    "sample_utf8.smi": "utf-8",
    "short_cp949.smi": "cp949",
    "tiny_cp949.smi": "cp949",
    "mid_cp949.smi": "cp949",
    "styled_cp949.smi": "cp949",
    "bilingual_en_heavy_cp949.smi": "cp949",
    "plain_cp949.srt": "cp949",
    "short_cp949.srt": "cp949",
    "ja_sjis.smi": "shift_jis",
    "zh_gb18030.smi": "gb18030",
}


def setup_module(_module) -> None:
    if not (FIXTURES / "sample_cp949.smi").exists():
        sys.path.insert(0, str(FIXTURES))
        import make_fixtures

        make_fixtures.build()


@pytest.mark.parametrize("name,expected", sorted(EXPECT.items()))
def test_detect_encoding(name: str, expected: str) -> None:
    result = detect((FIXTURES / name).read_bytes())
    assert result.encoding == expected, f"{name}: {result.reason}"


def test_japanese_is_not_mistaken_for_korean() -> None:
    """가장 중요한 회귀 — 한글 비율만 보면 Shift_JIS 가 1.00 으로 나온다.

    탐지기의 CJK 판정(③)이 한글 비율(④)보다 먼저여야 이 테스트가 통과한다.
    단계 순서를 바꾸면 여기서 깨진다.
    """
    raw = (FIXTURES / "ja_sjis.smi").read_bytes()
    assert detect(raw).encoding == "shift_jis"
    # 한글 비율만 봤다면 CP949 로 잘못 갔을 것이라는 사실 자체도 고정한다
    assert hangul_ratio(strip_markup(raw)) >= HANGUL_MIN


def test_utf8_wins_first() -> None:
    result = detect("한글 자막입니다".encode("utf-8"))
    assert result.encoding == "utf-8"
    assert result.confident


def test_english_heavy_bilingual_is_cp949() -> None:
    """영어 비중이 큰 한·영 통합 자막은 탐지기가 UTF-8 로 오탐한다.

    ①이 실패했으면 탐지기의 UTF-8 판정을 믿지 않는다 — 그 규칙을 고정한다.
    """
    result = detect((FIXTURES / "bilingual_en_heavy_cp949.smi").read_bytes())
    assert result.encoding == "cp949"


def test_strip_markup_keeps_multibyte_intact() -> None:
    """태그 제거는 바이트 단위지만 멀티바이트 문자를 쪼개면 안 된다."""
    raw = "<SYNC Start=0><P Class=KRCC>안녕하세요</P>".encode("cp949")
    body = strip_markup(raw)
    assert body.decode("cp949") == "안녕하세요"


def test_result_exposes_mpv_codepage() -> None:
    """mpv 에 넘길 때는 '+' 접두가 붙어야 탐지를 우회한다."""
    assert detect("안녕".encode("cp949")).mpv_codepage == "+cp949"


def test_unconfident_result_is_flagged() -> None:
    """판정하지 못하면 confident=False 로 표시해 UI 가 '추정' 배지를 띄울 수 있어야 한다."""
    result = detect(bytes([0xA1, 0xA1, 0xFF, 0xFE, 0x80]))
    assert result.confident is False or result.encoding == "cp949"
