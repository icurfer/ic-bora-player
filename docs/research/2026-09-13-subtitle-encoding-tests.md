# 실측 기록 — 국내 자막(SAMI·CP949)이 리눅스 플레이어에서 겪는 문제 (2026-09-13)

기획서(`../spec/plan-v0.1.0.md`)의 근거. **전부 lab(Ubuntu 26.04, ffmpeg 8.0.1, libuchardet 0.0.8) 에서
아래 명령으로 재현**했다. 웹 자료는 보조 근거로만 썼다.

## 0. 결론 요약

| # | 확인된 사실 | 의미 |
|---|---|---|
| A | ffmpeg SAMI 디코더는 `<P Class=KRCC>` / `<P Class=ENCC>` **언어 클래스를 무시**하고 한 스트림에 섞는다 | 한·영 통합 SAMI(국내 관례)는 화면에 두 언어가 겹쳐 나온다 |
| B | 같은 `Start` 시각의 SYNC 가 연속되면 앞 큐가 **0초 길이**가 된다 | A 와 결합 → 한글 큐가 0초로 사라지고 영어만 남는 경우가 생긴다 |
| C | CP949 SAMI 를 인코딩 지정 없이 넣으면 한글 줄이 **깨지는 게 아니라 통째로 버려진다** (`Invalid UTF-8 … Error decoding`) — 영어 줄은 살아남는다 | 사용자는 "자막이 일부만 나온다"로 체감. 원인 추적이 어렵다 |
| D | `-sub_charenc cp949` 를 주면 정상 | 인코딩을 **맞게 알려주는 것**이 문제의 전부다 |
| E | mpv 가 실제로 쓰는 탐지기 **uchardet 는 태그가 많은 짧은 SAMI 를 `WINDOWS-1252` 로 오탐**한다 (107 B → 1252, 56 B → 1252, 10 B → 실패). 600 B 급은 `UHC`로 정확 | mpv 기본값 `--sub-codepage=auto` 만으로는 **짧은 파일·태그 비중 큰 파일**에서 깨진다. 이게 실제 공백이다 |
| F | python `chardet` 도 107 B 에서 신뢰도 0.67 로 흔들린다 (598 B 는 0.99) | 어떤 탐지기든 **본문이 짧으면 못 믿는다** → 탐지 전 태그 제거 + 한글 바이트 비율 검증이 필요 |

## 1. 샘플 생성

```python
# python3
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
open('sample_utf8.smi','w',encoding='utf-8').write(smi)
open('sample_cp949.smi','wb').write(smi.encode('cp949'))
short = "<SAMI><BODY><SYNC Start=1000><P Class=KRCC>안녕하세요\n<SYNC Start=2000><P Class=KRCC>&nbsp;\n</BODY></SAMI>\n"
open('short_cp949.smi','wb').write(short.encode('cp949'))
mid = "<SAMI><BODY>\n" + "".join(f"<SYNC Start={i*2000}><P Class=KRCC>이것은 {i}번째 자막 문장입니다. 오늘 날씨가 좋네요.\n" for i in range(1,8)) + "</BODY></SAMI>\n"
open('mid_cp949.smi','wb').write(mid.encode('cp949'))
```

> ⚠ CP949 에 없는 문자(예: em-dash `—`)가 들어가면 `encode('cp949')` 가 실패해 **0 바이트 파일**이 생기고
> 이후 테스트가 전부 무효가 된다. 처음에 실제로 이 실수를 했다. 하이픈 `-` 로 대체할 것.

## 2. ffmpeg SAMI 디코더 동작 (A·B·C·D)

```bash
ffmpeg -hide_banner -loglevel error -i sample_utf8.smi -f srt -            # A·B
ffmpeg -hide_banner -loglevel warning -i sample_cp949.smi -f srt -         # C
ffmpeg -hide_banner -loglevel error -sub_charenc cp949 -i sample_cp949.smi -f srt -   # D
```

A·B 결과(UTF-8): KRCC·ENCC 큐가 **한 스트림에 번갈아** 나오고, 1000ms 의 한글 큐는
`00:00:01,000 --> 00:00:01,000` (0초). 뒤따르는 같은 시각 ENCC SYNC 가 앞 큐를 끊기 때문.

C 결과(CP949, 지정 없음):
```
[sami] Invalid UTF-8 in decoded subtitles text; maybe missing -sub_charenc option
Error decoding subtitles: Invalid data found when processing input
1  00:00:01,000 --> 00:00:03,000  First subtitle line. / second line
2  00:00:04,000 --> 00:00:06,000  UHC-only hangul test
```
→ **한글 큐 2개가 통째로 없어지고 영어만 출력.**

D 결과(`-sub_charenc cp949`): 한글 정상.

## 3. uchardet 직접 호출 (E) — mpv 와 같은 라이브러리

`uchardet` CLI 는 미설치였지만 `libuchardet.so.0` 는 libmpv 의존성으로 이미 있어 ctypes 로 호출했다.

```python
import ctypes, ctypes.util
u = ctypes.CDLL(ctypes.util.find_library('uchardet') or 'libuchardet.so.0')
u.uchardet_new.restype = ctypes.c_void_p
u.uchardet_get_charset.restype = ctypes.c_char_p
u.uchardet_handle_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
for fn in ('uchardet_data_end','uchardet_get_charset','uchardet_delete'):
    getattr(u, fn).argtypes = [ctypes.c_void_p]
def detect(b):
    h = u.uchardet_new(); u.uchardet_handle_data(h, b, len(b)); u.uchardet_data_end(h)
    r = u.uchardet_get_charset(h).decode() or '(실패)'; u.uchardet_delete(h); return r
```

| 입력 | 바이트 | uchardet 결과 |
|---|---|---|
| `short_cp949.smi` (자막 1줄 + 태그) | 107 | **WINDOWS-1252** ❌ |
| `mid_cp949.smi` (자막 7줄) | 598 | UHC ✅ |
| `sample_cp949.smi` (한·영 혼합) | 587 | UHC ✅ |
| `sample_utf8.smi` | 737 | UTF-8 ✅ |
| `안녕하세요` (본문만) | 10 | (실패) |
| `안녕하세요 오늘 날씨 좋네요` (본문만) | 27 | UHC ✅ |
| `<SAMI><BODY><SYNC Start=0><P Class=KRCC>네</BODY></SAMI>` | 56 | **WINDOWS-1252** ❌ |

**해석**: 한글 바이트가 27 B 만 있어도 맞히지만, **ASCII 태그가 비중을 차지하면 Latin 계열로 기운다.**
SAMI 는 태그 비중이 크므로 짧은 자막 파일에서 오탐이 구조적으로 발생한다.
→ 탐지 전에 태그·엔티티를 벗겨 **본문만** 넘기고, 결과를 `cp949` 로 디코드해 **한글 음절 비율**로 검증하는
2단 파이프라인이 필요하다.

## 4. python chardet (F)

```bash
chardetect short_cp949.smi mid_cp949.smi sample_cp949.smi
# short 107 B → EUC-KR 0.67 / mid 598 B → EUC-KR 0.99 / sample 587 B → CP949 0.99
```

## 5. 패키지·버전 매트릭스 (Ubuntu 22.04 ~ 26.04) — 웹 조회

출처: packages.ubuntu.com (2026-09-13 조회). 26.04 값은 lab 의 `apt-cache policy` 로 재확인.

| 패키지 | 22.04 jammy | 24.04 noble | 26.04 resolute |
|---|---|---|---|
| libmpv | **libmpv1** 0.34.1 | libmpv2 0.37.0 | libmpv2 0.41.0 |
| mpv → libuchardet0 의존 | ✅ (0.34.1 부터 확인) | ✅ | ✅ |
| libgtk-4-1 | 4.6.9 | 4.14.5 | 4.22.4 |
| libadwaita-1-0 | **1.1.7** | 1.5.0 | 1.9.1 |
| python3-mpv | **0.5.2** | 1.0.4 | 1.0.8 |
| python3-gi | (jammy 3.42) | 3.48 | 3.56.2 |
| uchardet / libuchardet-dev | 0.0.7 | 0.0.8 | 0.0.8 |
| ffmpeg | 4.4 | 6.1 | 8.0.1 |

- jammy 의 `libadwaita 1.1` 은 이후 버전의 위젯(ToolbarView 1.4, Dialog 1.5, SpinRow 1.4 등)이 없다.
- jammy 의 `python3-mpv 0.5.2` 는 6년 전 판. 렌더 컨텍스트 API 지원 여부 **미확인** (다음 세션 검증 항목).
- python-mpv 는 `ctypes.util.find_library('mpv')` 로 libmpv 를 찾고 **libmpv ≥ 0.33 (API 1.108)** 을 요구 →
  jammy 0.34.1 도 통과. lab 에는 libmpv 미설치라 실제 로드는 **미검증**.

## 6. 참고 링크 (보조 근거)

- mpv `--sub-codepage`: 기본 `auto`(uchardet). ENCA/`utf8:` 접두 시절 문법은 구판이며 현행 문법은 매뉴얼로 재확인 필요
  — https://mpv.io/manual/master/#options-sub-codepage
- uchardet 도입 PR(mpv #2193, 우리 자막 사례 포함) — https://github.com/mpv-player/mpv/pull/2193
- 국내 자막이 Windows-1254 로 오탐된 사례 언급 — https://github.com/chardet/chardet/issues/164
- python-mpv + GTK4 렌더 예제 — https://github.com/trin94/python-mpv-gtk4 , https://gist.github.com/jaseg/657e8ecca3267c0d82ec85d40f423caa
- Celluloid(GTK4+libadwaita, libmpv, Flathub 배포·월 6.5k 다운로드) — https://github.com/celluloid-player/celluloid
- 이름 충돌 확인: `jamak` 은 자막 편집기·mpv 자막 다운로더로 이미 2건 존재 → 사용 안 함
