# -*- coding: utf-8 -*-
"""P1·P2 의 '화면 증상'을 mpv 경로에서 직접 본다 (ffmpeg CLI 가 아니라)."""
import mpv

def probe(subfile, **opts):
    seen = []
    p = mpv.MPV(vo='null', ao='null', really_quiet=True, speed=4, **opts)
    @p.property_observer('sub-text')
    def _on_sub(_n, v):
        if v:
            seen.append((p.time_pos, v.replace('\n', ' / ')))
    try:
        p.play('av://lavfi:color=c=black:s=320x240:d=8')
        p.wait_for_property('duration', lambda v: v is not None, timeout=10)
        p.sub_add(subfile)
        p.wait_for_playback(timeout=30)
    finally:
        p.terminate()
    return seen

files = ['short_cp949.smi', 'styled_cp949.smi', 'mid_cp949.smi', 'plain_cp949.srt']
cases = [('auto', {}), ('+cp949', dict(sub_codepage='+cp949')),
         ('auto+stretch', dict(sub_stretch_durations=True)),
         ('+cp949+stretch', dict(sub_codepage='+cp949', sub_stretch_durations=True))]
for f in files:
    print('##### %s' % f)
    for label, opts in cases:
        try:
            got = probe(f, **opts)
            txt = ' | '.join('%.1fs %s' % (t, s) for t, s in got[:3]) or '(자막 없음)'
        except Exception as e:
            txt = 'ERROR %s' % e
        print('  %-16s %s' % (label, txt))
    print()
