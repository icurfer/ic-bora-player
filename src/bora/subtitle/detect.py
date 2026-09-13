"""자막 인코딩 판정.

docs/research/2026-09-13-mpv-playback-path-tests.md §2 의 실측으로 확정한 순서를 그대로 옮겼다.
프로토타입은 docs/research/scripts/pipeline.py (합성 표본 11개 통과).

⚠ 단계 순서를 바꾸지 말 것. 특히 ③(탐지기의 CJK 판정)은 ④(한글 비율)보다 **먼저**다.
   Shift_JIS 바이트열을 cp949 로 디코드하면 한글 음절 비율이 1.00 이 나온다 — 즉
   한글 비율만으로는 일본어를 구분할 수 없다. 순서를 뒤집으면 일본어 자막이 깨진다.
   tests/test_detect.py 가 이 순서를 고정한다.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import re
from dataclasses import dataclass

# uchardet 이 지목하면 그대로 믿는 CJK 계열. 한글 비율로 뒤집지 않는다.
CJK_TRUSTED: dict[str, str] = {
    "SHIFT_JIS": "shift_jis",
    "EUC-JP": "euc_jp",
    "ISO-2022-JP": "iso2022_jp",
    "GB18030": "gb18030",
    "GBK": "gbk",
    "BIG5": "big5",
    "EUC-KR": "cp949",
    "UHC": "cp949",
    "EUC-TW": "euc_tw",
}

# 비ASCII 문자 중 한글 음절이 이 비율 이상이면 CP949 로 본다.
# 실측: CP949 자막은 전부 1.00, 중국어(GB18030)는 0.50.
# 한자가 섞인 한글 자막을 고려해 1.00 을 요구하지 않는다.
# ⚠ 합성 표본 11개로 정한 값이다. 실제 자막 표본이 모이면 재검토한다(deferred §4).
HANGUL_MIN = 0.7

_TAG_RE = re.compile(rb"<[^>]*>")
_ENTITY_RE = re.compile(rb"&[a-zA-Z#0-9]{1,8};")
_SRT_TS_RE = re.compile(rb"^\s*\d+\s*$|^\s*[\d:,]+\s*-->\s*[\d:,]+\s*$", re.M)

_HANGUL_FIRST = "가"
_HANGUL_LAST = "힣"


@dataclass(frozen=True)
class DetectResult:
    encoding: str       # 파이썬 코덱 이름
    confident: bool     # False 면 UI 에 '추정' 배지를 띄운다
    reason: str         # 어느 단계에서 정해졌는지. 로그와 툴팁에 그대로 쓴다

    @property
    def mpv_codepage(self) -> str:
        """mpv 에 강제로 넘길 값. '+' 접두가 mpv 자체 탐지를 완전히 우회한다."""
        return "+" + self.encoding


def strip_markup(raw: bytes) -> bytes:
    """태그·엔티티·SRT 타임코드를 제거해 '본문 바이트'만 남긴다.

    디코드 '전에' 부르므로 바이트 단위로 자른다. 안전한 이유:
    '<'(0x3C) '>'(0x3E) '&'(0x26) ';'(0x3B) 는 CP949·Shift_JIS·GB18030 의 2바이트 문자
    trail byte 범위(0x40~0xFE)에 들어가지 않아 멀티바이트 문자를 쪼갤 수 없다.
    """
    body = _TAG_RE.sub(b" ", raw)
    body = _ENTITY_RE.sub(b" ", body)
    body = _SRT_TS_RE.sub(b" ", body)
    return b" ".join(body.split())


def _load_uchardet():
    path = ctypes.util.find_library("uchardet") or "libuchardet.so.0"
    lib = ctypes.CDLL(path)
    lib.uchardet_new.restype = ctypes.c_void_p
    lib.uchardet_get_charset.restype = ctypes.c_char_p
    lib.uchardet_handle_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    for fn in ("uchardet_data_end", "uchardet_get_charset", "uchardet_delete"):
        getattr(lib, fn).argtypes = [ctypes.c_void_p]
    return lib


try:
    _UCHARDET = _load_uchardet()
except OSError:          # 라이브러리가 없어도 나머지 단계로 판정은 계속된다
    _UCHARDET = None


def uchardet(data: bytes) -> str:
    """mpv 가 쓰는 것과 같은 탐지기. 실패하면 빈 문자열."""
    if _UCHARDET is None or not data:
        return ""
    handle = _UCHARDET.uchardet_new()
    try:
        _UCHARDET.uchardet_handle_data(handle, data, len(data))
        _UCHARDET.uchardet_data_end(handle)
        return (_UCHARDET.uchardet_get_charset(handle) or b"").decode()
    finally:
        _UCHARDET.uchardet_delete(handle)


def hangul_ratio(data: bytes, encoding: str = "cp949") -> float | None:
    """해당 인코딩으로 디코드했을 때 '비ASCII 문자 중 한글 음절' 비율.

    ASCII 는 어느 인코딩에서도 같으므로 분모에서 뺀다 — 영어 비중이 큰 한·영 통합 자막도
    제대로 판정된다(실측: 영어가 많아도 1.00).
    디코드 실패나 비ASCII 문자가 없으면 None.
    """
    try:
        text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None
    non_ascii = [c for c in text if ord(c) > 127]
    if not non_ascii:
        return None
    hangul = sum(1 for c in non_ascii if _HANGUL_FIRST <= c <= _HANGUL_LAST)
    return hangul / len(non_ascii)


def detect(raw: bytes) -> DetectResult:
    """자막 바이트열의 인코딩을 판정한다."""
    # ① 엄격 UTF-8
    try:
        raw.decode("utf-8")
        return DetectResult("utf-8", True, "엄격 UTF-8 디코드 성공")
    except UnicodeDecodeError:
        pass

    # ② 태그를 벗겨 본문만 탐지기에 넘긴다
    body = strip_markup(raw)
    guess = uchardet(body)

    # ③ 탐지기가 CJK 를 지목하면 신뢰한다 (한글 비율로 뒤집지 않는다)
    if guess in CJK_TRUSTED:
        return DetectResult(CJK_TRUSTED[guess], True, f"탐지기 판정 {guess}")

    # ④ Latin 오탐·UTF-8 오탐·탐지 실패 → 한글 비율로 CP949 를 확인
    #    (①이 실패했으므로 탐지기가 UTF-8 이라 해도 믿지 않는다)
    ratio = hangul_ratio(body)
    if ratio is not None and ratio >= HANGUL_MIN:
        seen = guess or "탐지 실패"
        return DetectResult("cp949", True, f"한글 비율 {ratio:.2f} (탐지기: {seen})")

    # ⑤ 폴백 — 국내 사용자가 대상이므로 cp949 로 열되 확신이 없다고 표시한다
    seen = guess or "탐지 실패"
    shown = "없음" if ratio is None else f"{ratio:.2f}"
    return DetectResult("cp949", False, f"폴백 추정 (탐지기: {seen}, 한글 비율: {shown})")
