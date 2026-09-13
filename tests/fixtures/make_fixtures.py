# -*- coding: utf-8 -*-
"""테스트 표본 생성. docs/research/scripts/gen.py 와 같은 표본을 유지한다.

⚠ 원본 조사 스크립트는 이 줄을 "UHC 전용 글자"라고 불렀는데, 파이썬의 euc_kr 코덱은
   UHC 확장까지 받아들여 cp949 와 사실상 같게 동작한다. 파이썬 안에서는 '전용'을 구분할 수
   없으므로 라벨을 '확장 한글'로 고쳤다. (uchardet 은 UHC 와 EUC-KR 을 다르게 답하므로
   detect.CJK_TRUSTED 가 둘 다 cp949 로 매핑하는 것은 그대로 맞다.)
   조사 때 쓴 글자도 오타였다 — 똑(U+B611)이 아니라 똠(U+B620)이다.

  python3 tests/fixtures/make_fixtures.py

⚠ 일본어·중국어 본문을 유니코드 이스케이프로 쓰는 이유: 이 저장소는 한자를 금칙으로 두고
   커밋 게이트(Gate F)가 막는다. tests/fixtures/ 는 게이트 예외 경로지만, 생성 스크립트는
   그 밖에 있어도 되도록 이스케이프로 통일한다.
"""
from pathlib import Path

OUT = Path(__file__).parent

SMI = """<SAMI>
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
<SYNC Start=4000><P Class=KRCC>똠방각하 - 확장 한글 테스트
<SYNC Start=4000><P Class=ENCC>extended hangul test
<SYNC Start=6000><P Class=KRCC>&nbsp;
</BODY></SAMI>
"""
SHORT = "<SAMI><BODY><SYNC Start=1000><P Class=KRCC>안녕하세요\n<SYNC Start=2000><P Class=KRCC>&nbsp;\n</BODY></SAMI>\n"
TINY = "<SAMI><BODY><SYNC Start=0><P Class=KRCC>네</BODY></SAMI>\n"
MID = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=KRCC>이것은 %d번째 자막 문장입니다. 오늘 날씨가 좋네요.\n" % (i * 2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"
STYLED = SMI.split("<BODY>")[0] + "<BODY>\n<SYNC Start=1000><P Class=KRCC>안녕하세요\n<SYNC Start=3000><P Class=KRCC>&nbsp;\n</BODY></SAMI>\n"
BILINGUAL = SMI.split("<BODY>")[0] + "<BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=ENCC>This is a fairly long english subtitle line number %d for the test.\n"
    "<SYNC Start=%d><P Class=KRCC>짧은 한글\n" % (i * 2000, i, i * 2000) for i in range(1, 6)
) + "</BODY></SAMI>\n"
SRT = "".join("%d\n00:00:%02d,000 --> 00:00:%02d,000\n이것은 %d번째 자막입니다.\n\n" % (i, i * 2, i * 2 + 2, i)
              for i in range(1, 6))
SRT_SHORT = "1\n00:00:01,000 --> 00:00:03,000\n안녕하세요\n\n"
JA = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=JPCC>これは%d番目の字幕です。今日はいい天気ですね。\n" % (i * 2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"
ZH = "<SAMI><BODY>\n" + "".join(
    "<SYNC Start=%d><P Class=CNCC>这是第%d个字幕。今天天气很好。\n" % (i * 2000, i)
    for i in range(1, 8)) + "</BODY></SAMI>\n"

CASES = [
    ("sample_cp949.smi", SMI, "cp949"),
    ("sample_utf8.smi", SMI, "utf-8"),
    ("short_cp949.smi", SHORT, "cp949"),
    ("tiny_cp949.smi", TINY, "cp949"),
    ("mid_cp949.smi", MID, "cp949"),
    ("styled_cp949.smi", STYLED, "cp949"),
    ("bilingual_en_heavy_cp949.smi", BILINGUAL, "cp949"),
    ("plain_cp949.srt", SRT, "cp949"),
    ("short_cp949.srt", SRT_SHORT, "cp949"),
    ("ja_sjis.smi", JA, "shift_jis"),
    ("zh_gb18030.smi", ZH, "gb18030"),
]


def build() -> None:
    for name, text, enc in CASES:
        data = text.encode(enc)
        assert data, name          # 0 바이트면 즉시 실패시킨다
        (OUT / name).write_bytes(data)


if __name__ == "__main__":
    build()
    for name, _t, enc in CASES:
        print("%-32s %6d B  (%s)" % (name, (OUT / name).stat().st_size, enc))
