# -*- coding: utf-8 -*-
"""§8-4/§5-2② 검증 — SAMI 를 언어 클래스별 SRT 로 분리한다.
   큐 끝 = '같은 클래스'의 다음 SYNC (클래스를 섞지 않으므로 0초 큐가 생기지 않는다)."""
import re, io, os

SYNC_RE = re.compile(r'<SYNC\s+Start\s*=\s*(\d+)[^>]*>', re.I)
P_RE    = re.compile(r'<P(?:\s+[^>]*)?>', re.I)
CLASS_RE= re.compile(r'Class\s*=\s*["\']?([A-Za-z0-9_-]+)', re.I)
LANG_RE = re.compile(r'\.(\w+)\s*\{[^}]*?lang\s*:\s*([A-Za-z-]+)', re.I | re.S)
TAG_RE  = re.compile(r'<[^>]*>')

def parse_sami(text):
    """-> {클래스: [(start_ms, 본문), ...]}, {클래스: lang}"""
    langs = {k.upper(): v for k, v in LANG_RE.findall(text)}
    body = re.split(r'<BODY[^>]*>', text, flags=re.I)[-1]
    cues, last_class = {}, 'UNKNOWN'
    parts = SYNC_RE.split(body)
    for i in range(1, len(parts), 2):
        start, chunk = int(parts[i]), parts[i + 1]
        m = P_RE.search(chunk)
        cls = last_class
        if m:
            cm = CLASS_RE.search(m.group(0))
            if cm:
                cls = cm.group(1).upper()
        last_class = cls
        raw = P_RE.sub('', chunk)
        raw = re.sub(r'<br\s*/?>', '\n', raw, flags=re.I)
        txt = TAG_RE.sub('', raw)
        txt = txt.replace('&nbsp;', '\xa0').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        txt = '\n'.join(l.strip() for l in txt.strip().split('\n')).strip()
        cues.setdefault(cls, []).append((start, txt))
    return cues, langs

def to_srt(cue_list):
    """같은 클래스 안에서만 끝 시각을 계산한다. 공백 큐(&nbsp;)는 '종료' 신호."""
    out, n = [], 0
    for i, (start, txt) in enumerate(cue_list):
        if not txt.strip() or txt.strip() == '\xa0':
            continue                                   # 종료 신호 큐는 출력하지 않는다
        end = cue_list[i + 1][0] if i + 1 < len(cue_list) else start + 4000
        if end <= start:                               # 같은 클래스 안에서 시각이 같으면 최소 길이 부여
            end = start + 2000
        n += 1
        fmt = lambda ms: '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
        out.append('%d\n%s --> %s\n%s\n' % (n, fmt(start), fmt(end), txt))
    return '\n'.join(out)

def split_file(path, enc, outdir='.'):
    text = open(path, 'rb').read().decode(enc)
    cues, langs = parse_sami(text)
    made = []
    for cls, lst in cues.items():
        srt = to_srt(lst)
        if not srt.strip():
            continue
        lang = langs.get(cls, cls.lower())
        out = os.path.join(outdir, '%s.%s.srt' % (os.path.splitext(os.path.basename(path))[0], lang))
        io.open(out, 'w', encoding='utf-8').write(srt)
        made.append((cls, lang, out))
    return made

if __name__ == '__main__':
    for cls, lang, out in split_file('sample_cp949.smi', 'cp949'):
        print('--- %s (lang=%s) -> %s' % (cls, lang, out))
        print(open(out, encoding='utf-8').read())
