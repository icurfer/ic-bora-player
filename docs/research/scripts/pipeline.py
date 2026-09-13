# -*- coding: utf-8 -*-
"""§8-4 — 실측으로 도출한 인코딩 판정 파이프라인 프로토타입과 그 검증.
   기획서 §5-2 ① 의 순서를 실측 결과에 맞춰 고친 판이다."""
import ctypes, ctypes.util, re, glob

u = ctypes.CDLL(ctypes.util.find_library('uchardet') or 'libuchardet.so.0')
u.uchardet_new.restype = ctypes.c_void_p
u.uchardet_get_charset.restype = ctypes.c_char_p
u.uchardet_handle_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
for fn in ('uchardet_data_end', 'uchardet_get_charset', 'uchardet_delete'):
    getattr(u, fn).argtypes = [ctypes.c_void_p]

def uchardet(b):
    h = u.uchardet_new(); u.uchardet_handle_data(h, b, len(b)); u.uchardet_data_end(h)
    r = (u.uchardet_get_charset(h) or b'').decode() or ''
    u.uchardet_delete(h); return r

TAG_RE = re.compile(rb'<[^>]*>'); ENT_RE = re.compile(rb'&[a-zA-Z#0-9]{1,8};')
SRT_TS_RE = re.compile(rb'^\s*\d+\s*$|^\s*[\d:,]+\s*-->\s*[\d:,]+\s*$', re.M)
def strip_markup(b):
    return b' '.join(SRT_TS_RE.sub(b' ', ENT_RE.sub(b' ', TAG_RE.sub(b' ', b))).split())

# uchardet 이 지목하면 그대로 믿는 CJK 계열. 한글 비율로 뒤집지 않는다.
CJK_TRUSTED = {'SHIFT_JIS': 'shift_jis', 'EUC-JP': 'euc_jp', 'ISO-2022-JP': 'iso2022_jp',
               'GB18030': 'gb18030', 'BIG5': 'big5', 'EUC-KR': 'cp949', 'UHC': 'cp949',
               'EUC-TW': 'euc_tw'}
HANGUL_MIN = 0.7   # 비ASCII 중 한글 음절 비율 임계 (실측: CP949 1.00 / 중국어 0.50)

def hangul_ratio(b, enc='cp949'):
    try:
        t = b.decode(enc)
    except Exception:
        return None
    na = [c for c in t if ord(c) > 127]
    if not na:
        return None
    return sum(1 for c in na if '가' <= c <= '힣') / len(na)

def decide(raw):
    """-> (인코딩, 확신, 근거)"""
    # ① UTF-8 엄격 디코드
    try:
        raw.decode('utf-8')
        return 'utf-8', True, '①엄격 UTF-8 성공'
    except UnicodeDecodeError:
        pass
    body = strip_markup(raw)
    guess = uchardet(body)
    # ② uchardet 이 CJK 를 지목하면 신뢰
    if guess in CJK_TRUSTED:
        return CJK_TRUSTED[guess], True, '②uchardet=%s' % guess
    # ③ UTF-8 이라 답해도 ①이 실패했으므로 믿지 않는다 (한·영 통합 자막 오탐 사례)
    # ④ Latin 오탐·실패·UTF-8 오탐 → cp949 디코드 + 비ASCII 한글 비율 검증
    r = hangul_ratio(body)
    if r is not None and r >= HANGUL_MIN:
        return 'cp949', True, '④한글비율 %.2f (uchardet=%s)' % (r, guess or '실패')
    # ⑤ 폴백 — UI 에 "추정" 배지
    return 'cp949', False, '⑤폴백 (uchardet=%s, 한글비율=%s)' % (
        guess or '실패', '없음' if r is None else '%.2f' % r)

EXPECT = {'sample_cp949.smi': 'cp949', 'sample_utf8.smi': 'utf-8', 'short_cp949.smi': 'cp949',
          'tiny_cp949.smi': 'cp949', 'mid_cp949.smi': 'cp949', 'styled_cp949.smi': 'cp949',
          'bilingual_en_heavy_cp949.smi': 'cp949', 'plain_cp949.srt': 'cp949',
          'short_cp949.srt': 'cp949', 'ja_sjis.smi': 'shift_jis', 'zh_gb18030.smi': 'gb18030'}

ok = bad = 0
print('%-30s %-11s %-11s %-5s %s' % ('파일', '기대', '판정', '결과', '근거'))
print('-' * 104)
for f in sorted(glob.glob('*.smi') + glob.glob('*.srt')):
    if f not in EXPECT:        # sami_split.py 가 만든 파생 트랙 등은 판정 대상이 아니다
        continue
    enc, sure, why = decide(open(f, 'rb').read())
    want = EXPECT[f]
    good = (enc == want)
    ok, bad = ok + good, bad + (not good)
    print('%-30s %-11s %-11s %-5s %s' % (f, want, enc, 'OK' if good else 'FAIL',
                                         why + ('' if sure else '  [추정 배지]')))
print('-' * 104)
print('통과 %d / 실패 %d' % (ok, bad))
