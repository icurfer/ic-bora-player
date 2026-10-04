---
name: feedback-isolation-too-late
description: 격리·초기화는 "읽히기 전"에 해야 한다 — 늦은 격리를 고쳤다고 말했다가 두 번 틀렸다
metadata:
  type: feedback
---

검증이 사용자 설정을 더럽히는 문제를 `win.state = State(임시폴더)` 로 막았다고 말했다.
**틀렸다.** 창은 `__init__` 에서 `_apply_settings()` 로 사용자 설정을 이미 player 에
적용한 뒤였다. 최근 파일이 안 쌓이는 것만 보고 "격리됐다"고 판단했는데, 볼륨(80)과
자막 위치(90)는 그대로 새어 들어가 다음 검증에서 기대값과 어긋났다.

올바른 자리는 **앱이 설정을 읽기 전**이다:
`os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()` 를 import 보다 먼저.

**Why:** "고쳤다"의 근거가 증상 하나(최근 파일)뿐이었다. 그 설정이 영향을 주는 **다른 경로**
(player 에 적용되는 값들)를 확인하지 않았다. 부분 증상이 사라진 것을 전체가 고쳐진 것으로
읽으면, 남은 경로는 더 찾기 어려워진다 — 이미 "고쳤다"고 믿고 있기 때문이다.

**How to apply:** 격리·초기화·설정 주입을 고칠 때는 **그 값이 흘러가는 경로를 전부 세고**
각각을 확인한다. 증상 하나가 사라진 것으로 끝내지 않는다. 그리고 "고쳤다"고 보고하기 전에
**그 변경이 실제로 유효한 시점에 일어나는지**(읽히기 전인지) 확인한다.
[[feedback-verify-before-done]] [[project-gui-verification-blind-spots]]
