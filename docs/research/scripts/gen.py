# -*- coding: utf-8 -*-
"""기획서 §8-4 검증용 샘플 생성. research 문서 §1 을 그대로 쓰고 케이스를 늘렸다."""
import os

smi = """<SAMI>
<HEAD><TITLE>test</TITLE>
<STYLE TYPE="text/css"><!--
P { text-align:center; font-size:20pt; color:white; }
.KRCC { Name:Korean; lang:ko-KR; SAMIType:CC; }
.ENCC { Name:English; lang:en-US; SAMIType:CC; }
--></STYLE></HEAD>
<BODY>
<SYNC Start=1000><P Class=KRCC>첫 번째 자막입니다.<br>두 번째 줄
<SYNC Start=1000><P Class=ENCC>First subtitle line.<br>second line
<SYNC Start=3000><P Class=KRCC>&nbsp;
<SYNC Start=4000><P Class=KRCC>똠방각하 - 확장 한글(UHC 전용 글자) 테스트
<SYNC Start=4000><P Class=ENCC>UHC-only hangul test
<SYNC Start=6000><P Class=KRCC>&nbsp;
</BODY></SAMI>
"""
short = "<SAMI><BODY><SYNC Start=1000><P Class=KRCC>안녕하세요\n<SYNC Start=2000><P Class=KRCC>&nbsp;\n</BODY></SAMI>\n"
tiny  = "<SAMI><BODY><SYNC Start=0><P Class=KRCC>네</BODY></SAMI>\n"
mid   = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=KRCC>이것은 %d번째 자막 문장입니다. 오늘 날씨가 좋네요.\n" % (i*2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"
# 태그 비중이 더 큰 실전형: 스타일 헤더가 길고 본문이 짧다
styled = smi.split('<BODY>')[0] + "<BODY>\n<SYNC Start=1000><P Class=KRCC>안녕하세요\n<SYNC Start=3000><P Class=KRCC>&nbsp;\n</BODY></SAMI>\n"
# 영어 비중이 큰 한·영 통합(국내 관례) — 한글 본문은 적다
bilingual_en_heavy = smi.split('<BODY>')[0] + "<BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=ENCC>This is a fairly long english subtitle line number %d for the test.\n"
    "<SYNC Start=%d><P Class=KRCC>짧은 한글\n" % (i*2000, i, i*2000) for i in range(1, 6)
) + "</BODY></SAMI>\n"
# SRT 케이스 (태그가 거의 없다 — 대조군)
srt = "".join("%d\n00:00:%02d,000 --> 00:00:%02d,000\n이것은 %d번째 자막입니다.\n\n" % (i, i*2, i*2+2, i)
              for i in range(1, 6))
srt_short = "1\n00:00:01,000 --> 00:00:03,000\n안녕하세요\n\n"

cases = [
    ('sample_cp949.smi', smi, 'cp949'),
    ('sample_utf8.smi',  smi, 'utf-8'),
    ('short_cp949.smi',  short, 'cp949'),
    ('tiny_cp949.smi',   tiny, 'cp949'),
    ('mid_cp949.smi',    mid, 'cp949'),
    ('styled_cp949.smi', styled, 'cp949'),
    ('bilingual_en_heavy_cp949.smi', bilingual_en_heavy, 'cp949'),
    ('plain_cp949.srt',  srt, 'cp949'),
    ('short_cp949.srt',  srt_short, 'cp949'),
]
for name, text, enc in cases:
    data = text.encode(enc)
    assert data, name          # 0 바이트면 즉시 실패시킨다(research 문서 §1 경고)
    open(name, 'wb').write(data)
    print('%-32s %6d B  (%s)' % (name, len(data), enc))

# 오탐 위험 대조군: 일본어(Shift_JIS)·중국어(GB18030) 자막.
# 본문을 유니코드 이스케이프로 쓴 이유: 이 저장소는 한자를 금칙으로 두고 커밋 게이트(Gate F)가
# 이를 막는다. 샘플 생성에는 한자가 정당하게 필요하므로, 게이트 예외를 넓히는 대신 이스케이프로 쓴다.
ja = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=JPCC>\u3053\u308c\u306f%d\u756a\u76ee\u306e\u5b57\u5e55\u3067\u3059\u3002\u4eca\u65e5\u306f\u3044\u3044\u5929\u6c17\u3067\u3059\u306d\u3002\n" % (i*2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"
zh = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=CNCC>\u8fd9\u662f\u7b2c%d\u4e2a\u5b57\u5e55\u3002\u4eca\u5929\u5929\u6c14\u5f88\u597d\u3002\n" % (i*2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"
for name, text, enc in [('ja_sjis.smi', ja, 'shift_jis'), ('zh_gb18030.smi', zh, 'gb18030')]:
    data = text.encode(enc)
    open(name, 'wb').write(data)
    print('%-32s %6d B  (%s)' % (name, len(data), enc))
