---
name: project-platform-layout
description: 플랫폼 분기는 platform/<os>/ 안에만 둔다 — 넷으로 갈렸고 검증된 것은 리눅스뿐
metadata:
  type: project
---

`src/bora/platform/` 아래가 `linux` · `windows` · `macos` · `android` 로 갈렸다.
각 폴더가 `gl` · `paths` · `integration` 을 **같은 이름으로** 제공하고, 본체는
`from .platform import gl, paths, integration` 하나만 쓴다.

- 지켜야 할 모양은 `platform/base.py`. 시그니처는 **동작하는 리눅스 구현에 맞췄다**
  (명세를 먼저 쓰고 구현을 맞추면 이미 도는 것을 건드린다).
- `tests/test_platform.py` 25건이 **네 플랫폼 전부**에 대해 이름 누락과 import 가능 여부를
  검사한다. 지금 플랫폼이 아닌 폴더도 import 는 되어야 한다.
- **검증된 것은 리눅스(Ubuntu 26.04)뿐이다.** windows 는 코드만 있고 실기 미검증,
  macos·android 는 자리와 설명뿐 — `available()` 이 False 를 돌린다.

**Why:** 추측으로 짠 그럴듯한 구현을 넣으면 "되는 줄 알았는데 안 되는" 상태가 된다.
그게 아예 없는 것보다 나쁘다. 그래서 미지원 플랫폼은 **명시적으로 못 한다고 말하고
이유를 남긴다**(`unsupported_reason()`).

**How to apply:** 본체에 `sys.platform`·`if windows` 를 쓰지 않는다. 새 플랫폼은 폴더를
만들고 base 의 이름을 전부 채운다. 그리고 **실기로 돌려 본 것만 "지원한다"고 적는다** —
README 지원 표의 ✅ 는 검증을 뜻한다.
