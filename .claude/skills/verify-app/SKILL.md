---
name: verify-app
description: Bora 변경을 실제로 재생시켜 검증하는 표준 절차 — 자막 인코딩·SAMI 트랙·하드웨어 디코딩 확인. 매번 일회용 스크립트를 쓰지 말고 여기에 쌓는다.
---

# verify-app (Bora)

변경을 "됐다"고 말하기 전에 **실제 파일을 열어 자막이 나오는지** 확인한다.
일회용 스크립트를 손으로 쓰지 말고 아래 자산을 쓰고, 없으면 만들어서 남긴다.

- `helpers/` — 재사용 유틸(샘플 자막 생성, 인코딩 변환, mpv 옵션 조합, 로그 파싱).
- `scenarios/` — 검증 흐름 하나당 파일 하나. 가장 가까운 것을 복제해 시작한다.

## 기준 시나리오 — 기획서 §6 수용 테스트

구현이 진행되면 아래를 `scenarios/` 에 하나씩 채운다. 출처:
[`docs/spec/plan-v0.1.0.md`](../../../docs/spec/plan-v0.1.0.md) §6.

| # | 시나리오 | 통과 기준 |
|---|---|---|
| T1 | CP949 `.smi` 를 영상과 같은 폴더에 두고 영상 열기 | 설정 없이 한글 자막이 나온다 |
| T2 | 107 바이트급 짧은 CP949 SAMI | 한글 정상(자동 탐지 단독으로는 오탐하는 사례) |
| T3 | `KRCC`+`ENCC` 통합 SAMI | 한국어 트랙 기본 표시, 영어는 별도 트랙, 한글 큐가 0초로 사라지지 않음 |
| T4 | UTF-8 `.srt` | 기존과 동일하게 정상 |
| T5 | Ubuntu 22.04 / 24.04 / 26.04 | 세 곳 모두 T1~T4 통과 |
| T6 | 1080p H.264 재생 | 하드웨어 디코딩(VA-API) 활성 확인 |

## 돌리는 법

```bash
# 전부 (01 만 영상 인자가 필요하다 — 나머지는 스스로 만들어 쓴다)
python3 .claude/skills/verify-app/scenarios/01-playback-renders.py <영상파일>
for f in .claude/skills/verify-app/scenarios/0[2-9]*.py \
         .claude/skills/verify-app/scenarios/1*.py; do
  echo "▶ $(basename "$f")"; timeout 300 python3 "$f" | tail -3
done
```

| 시나리오 | 무엇을 보나 | 인자 |
|---|---|---|
| 01 playback-renders | 실제 렌더·하드웨어 디코딩 | **영상 파일** |
| 02 subtitle-acceptance | T1~T4 자막 수용 테스트 | — |
| 03 ui-controls | 드롭·키·컨트롤 | — |
| 04 playback-extras | 속도·비율·최근 파일·스크린샷 | — |
| 05 subtitle-editor | 자막 편집·저장 | — |
| 06 notes-panel | 메모·타임스탬프·라이브 프리뷰 | — |
| 07 loop-and-pins | 구간 반복·핀 | — |
| 08 stt-and-pin-title | 텍스트 추출·핀 제목 | — |
| 09 clip-export | C1~C6 잘라내기·이어붙이기 | — |
| 10 keys-and-logging | 키 우선순위·메뉴 위치·로그·빈 창·종료 | — |
| 11 timeline-edit | T1~T12 타임라인 컷 편집 | — |

> ⚠ **시나리오는 반드시 설정을 격리한다** — `win.state = State(Path(tempfile.mkdtemp(...)))`.
> 예전에 이걸 빠뜨려 검증용 임시 영상 12개가 **사용자의 최근 파일 목록에 쌓였다.**
> 새 시나리오를 복제할 때 이 줄이 따라왔는지 확인할 것.

## 규칙
- 검증 자료(샘플 자막·영상)는 저장소에 커밋하지 말고 생성 스크립트를 `helpers/` 에 둔다.
  실제 샘플이 필요하면 `tests/fixtures/` 에 둔다 — 금칙 표현 게이트(Gate F)가 면제하는 경로다.
- **같은 검증을 손으로 두 번 쓰게 되면** 그때 helper 나 scenario 로 승격한다. 이 스킬은 그렇게 자란다.
- 검증하지 않은 변경을 "완료"라고 보고하지 않는다.
