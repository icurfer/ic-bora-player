# -*- coding: utf-8 -*-
"""§5-2② 최종 검증 — 분리한 트랙을 주입하면 P3(겹침)·P4(0초)가 사라지는가."""
import mpv

seen = []
p = mpv.MPV(vo='null', ao='null', really_quiet=True, speed=4)
@p.property_observer('sub-text')
def _on(_n, v):
    if v:
        seen.append((p.time_pos, v.replace('\n', ' / ')))
try:
    p.play('av://lavfi:color=c=black:s=320x240:d=8')
    p.wait_for_property('duration', lambda v: v is not None, timeout=10)
    # 전처리기가 만든 UTF-8 트랙 두 개를 주입. 기본 표시는 한국어.
    p.sub_add('sample_cp949.ko-KR.srt', 'select', 'Korean', 'kor')
    p.sub_add('sample_cp949.en-US.srt', 'auto',   'English', 'eng')
    tracks = [(t['id'], t.get('type'), t.get('title'), t.get('lang'), t.get('selected'))
              for t in p.track_list if t.get('type') == 'sub']
    p.wait_for_playback(timeout=30)
finally:
    p.terminate()

print('자막 트랙 목록:')
for t in tracks:
    print('  id=%s type=%s title=%r lang=%s selected=%s' % t)
print('\n재생 중 표시된 자막:')
for t, s in seen:
    print('  %5.2fs  %s' % (t, s))
