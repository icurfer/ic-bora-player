# done-v0.3.0 — Bora v0.1 MVP 구현 완료 (2026-09-14)

범위: [`../scope/scope-v0.1.0.md`](../scope/scope-v0.1.0.md) · 기획: [`../spec/plan-v0.1.0.md`](../spec/plan-v0.1.0.md)
기간: 2026-09-13 ~ 2026-09-14 · 버전: `0.1.4` → **`0.3.0`**

## §0 한 줄

**국내 자막(CP949 SAMI)을 영상 옆에 두면 아무 설정 없이 한글 자막이 나온다.** 기획서 §6 의 T1~T4 가
26.04 에서 통과했다.

## §1 영향받는 레포

| 레포 | 변경 | 버전 |
|---|---|---|
| `ic-bora-player` | 첫 코드. `src/bora/` 전체, 테스트, 검증 시나리오 | 0.1.4 → **0.3.0** |
| `hcloud/infra` (`hm-lab/com-lab/`) | 개발 환경 기록 — mpv 스택 설치, Flatpak, 메모리 경로 함정 | — (문서) |

## §2 만든 것

| 파일 | 역할 | 출처 |
|---|---|---|
| `src/bora/util/gl.py` | `eglGetProcAddress` · 현재 FBO 조회 (ctypes, **PyOpenGL 없음**) | `research/scripts/spike_gtk4.py` |
| `src/bora/player.py` | libmpv 래퍼. 렌더 컨텍스트 + 자막 주입 | 스파이크 승격 |
| `src/bora/glarea.py` | `set_auto_render(False)` + `update_cb` → `queue_render` | 스파이크 승격 |
| `src/bora/window.py` | 창·컨트롤·자막 메뉴·드롭·단축키·전체화면 | 신규 |
| `src/bora/app.py`, `__main__.py` | 진입점. 인자가 둘이면 두 번째를 자막으로 본다 | 신규 |
| `src/bora/subtitle/detect.py` | 인코딩 판정 5단계 | `research/scripts/pipeline.py` |
| `src/bora/subtitle/sami.py` | SAMI 클래스별 분리 | `research/scripts/sami_split.py` |
| `src/bora/subtitle/loader.py` | **무엇을 할지 정하는 층** (Plan) | 신규 — research 2 §4 의 결론 |
| `tests/` | 단위 테스트 26개 + 표본 생성기 | 신규 |
| `.claude/skills/verify-app/scenarios/01~03` | 재생·렌더 / 자막 수용 / UI 동작 | 신규 |

**설계의 핵심은 실측이 정해 줬다**: 인코딩은 파일을 다시 쓰지 않고 `--sub-codepage=+<enc>` 로 주입하고,
파일을 만드는 것은 **한·영 통합 SAMI 일 때뿐**이다. 단일 언어 자막은 손대지 않는다.

## §3 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 | **26개 통과** |
| T1 CP949 SAMI 동명 자동 로드 | 통과 — `첫 번째 자막입니다` / `똠방각하 - 확장 한글 테스트` |
| T2 짧은 CP949 SAMI (107 B) | 통과 — `안녕하세요` (탐지기 단독으로는 1252 로 오탐하는 표본) |
| T3 한·영 통합 SAMI | 통과 — 트랙 2개, 한국어 기본 선택, 화면에 영어가 섞이지 않음 |
| T4 UTF-8 SRT | 통과 |
| T6 하드웨어 디코딩 | 통과 — `hwdec-current=vulkan-copy`, 1080p 드랍 0 |
| UI 동작 11항목 | 전부 통과 (드롭·단축키·전체화면·볼륨·싱크) |
| Gate F 자체 검사 | 통과 |
| T5 (22.04/24.04) | **연기** — deferred §1 |

## §4 도중에 잡은 결함

| # | 결함 | 원인 | 조치 |
|---|---|---|---|
| 1 | libmpv 초기화 거부 (`Non-C locale detected`) | GTK 가 `setlocale(LC_ALL, "")` 을 부르면 `LC_NUMERIC` 이 ko_KR 이 된다 | `Player.__init__` 에서 `LC_NUMERIC` 만 C 로 되돌린다. 첫 실행이 우연히 성공한 것은 import 순서 때문이었다 |
| 2 | **Gate F 가 죽어 있었다** | grep 의 바이트 범위 패턴이 브래킷 안에서 처리되지 않아 **아무것도 매칭하지 않았다**. 통과만 시키니 아무도 몰랐다 | 검사를 `scripts/check_taboo.py`(파이썬)로 옮기고 `scripts/selftest_taboo.sh` 추가 |
| 3 | 드롭 타깃이 헤더바 위에서 안 받음 | 내용 박스에 붙였다 | 창 자체에 붙였다 |
| 4 | 표본 글자 오타 (똑/똠) + 잘못된 라벨 | 파이썬 `euc_kr` 코덱은 UHC 확장까지 받아 'UHC 전용 글자'가 성립하지 않는다 | 표본과 라벨 정정, 근거를 주석에 남김 |

## §5 계측이 틀렸던 사례 — 다음 세션이 같은 함정에 빠지지 않도록

세 번 모두 **앱이 아니라 검증 코드가 틀렸다.** 실패를 보고 앱을 고치려 들었으면 멀쩡한 코드를 망가뜨렸을 것이다.

1. **GLArea 의 `render` 시그널에 핸들러를 덧붙여 프레임을 세면 0 이 나온다.** 앞선 핸들러가 `True` 를
   반환해 전파가 멈추기 때문이다. → `Player.render` 에서 센다.
2. **`seek` 직후 `sub-text` 를 읽으면 빈 문자열이다.** 아직 갱신되지 않았다.
   → 재생하면서 주기적으로 모은다.
3. **한 프로세스에서 `Gtk.Application` 을 여러 번 `run()` 하면 두 번째부터 뜨지 않는다.**
   → 케이스마다 별도 프로세스로 돌린다.

또 하나: **초당 렌더 수를 통과 기준으로 쓰면 안 된다.** 창이 가려지면 컴포지터가 프레임 콜백을 주지
않아 정상인데도 뚝 떨어진다(단독 25.8/s, 다른 검증 직후 10/s 미만). 판정은 "렌더가 한 번이라도
돌았는가"로 하고 fps 는 참고값으로만 본다.

## §6 남은 것

- **scope 밖 · 연기**: 22.04·24.04 대응, 배포 방식(8-1) 선택, Flatpak 매니페스트 → [`../deferred/backlog-v0.1.0.md`](../deferred/backlog-v0.1.0.md)
- **다음에 가장 값어치 있는 일**: **실제 자막 표본 수집.** 지금 판정 임계값 `HANGUL_MIN=0.7` 의 근거는
  합성 표본 11개뿐이다. 실제 `.smi` 파일 수십 개를 넣어 보면 깨질 수 있다(deferred §4).
- 오디오 트랙 선택·화면 비율·플레이리스트 등은 v0.2 이후.
