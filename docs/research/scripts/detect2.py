# -*- coding: utf-8 -*-
"""§8-4 심화 — 비ASCII 기준 한글 비율. ASCII 는 어느 인코딩에서도 같으므로 분모에서 뺀다."""
import ctypes, ctypes.util, re, glob

u = ctypes.CDLL(ctypes.util.find_library('uchardet') or 'libuchardet.so.0')
u.uchardet_new.restype = ctypes.c_void_p
u.uchardet_get_charset.restype = ctypes.c_char_p
u.uchardet_handle_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
for fn in ('uchardet_data_end', 'uchardet_get_charset', 'uchardet_delete'):
    getattr(u, fn).argtypes = [ctypes.c_void_p]

def detect(b):
    h = u.uchardet_new(); u.uchardet_handle_data(h, b, len(b)); u.uchardet_data_end(h)
    r = (u.uchardet_get_charset(h) or b'').decode() or '(실패)'
    u.uchardet_delete(h); return r

TAG_RE = re.compile(rb'<[^>]*>'); ENT_RE = re.compile(rb'&[a-zA-Z#0-9]{1,8};')
SRT_TS_RE = re.compile(rb'^\s*\d+\s*$|^\s*[\d:,]+\s*-->\s*[\d:,]+\s*$', re.M)
def strip_markup(b):
    return b' '.join(SRT_TS_RE.sub(b' ', ENT_RE.sub(b' ', TAG_RE.sub(b' ', b))).split())

def nonascii_hangul(b, enc='cp949'):
    """(비ASCII 문자 수, 그중 한글 음절 비율). 디코드 실패면 None."""
    try:
        t = b.decode(enc)
    except Exception:
        return None
    na = [c for c in t if ord(c) > 127]
    if not na:
        return (0, None)
    han = sum(1 for c in na if '가' <= c <= '힣')
    return (len(na), han / len(na))

print('%-30s %-14s %6s %8s   %s' % ('파일', 'uchardet(본문)', '비ASCII', '한글비율', 'cp949 디코드 앞부분'))
print('-' * 118)
for f in sorted(glob.glob('*.smi') + glob.glob('*.srt')):
    raw = open(f, 'rb').read()
    body = strip_markup(raw)
    r = detect(body)
    res = nonascii_hangul(body)
    if res is None:
        cnt, ratio, peek = '-', '-', '(cp949 디코드 실패)'
    else:
        cnt, ratio = res
        ratio = '  -  ' if ratio is None else '%5.2f' % ratio
        peek = body.decode('cp949', 'replace')[:34]
    print('%-30s %-14s %6s %8s   %s' % (f, r, cnt, ratio, peek))
