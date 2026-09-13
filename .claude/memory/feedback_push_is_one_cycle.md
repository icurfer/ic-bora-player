---
name: feedback_push_is_one_cycle
description: 코드와 문서·작업내역은 한 사이클로 함께 나가고, 관련 변경은 한 번의 버전 bump 로 묶는다
metadata:
  type: feedback
---

(STARTER RULE — 맞으면 남기고 아니면 지운다.) 작업 한 단위는 한 사이클이다:
변경 → 검증 → 기록 → 커밋 → **push**. 별도 "push 해줘" 지시를 기다리지 않는다.
코드와 작업내역·CHANGELOG 를 따로 떨어진 커밋으로 나누지 않고, 관련 변경은 한 번의 버전
bump 로 묶는다(잦은 micro bump 금지).

**왜:** CI 가 push 트리거인 구조에서 push 가 빠지면 배포가 통째로 누락된다. 절반만 나간 변경과
문서 어긋남이 "다 된 줄 알았던" 버그가 사는 자리다.
**적용:** 동작을 확인했으면 코드와 문서를 한 번에 커밋하고 push 까지 한다. 단 force push,
main 외 브랜치, 다른 저장소는 사전 확인한다.
