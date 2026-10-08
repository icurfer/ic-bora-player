---
name: feedback_push_is_one_cycle
description: 코드와 문서·작업내역은 한 사이클로 함께 나가고, 버전 증가는 릴리스 단위로만 결정한다
metadata:
  type: feedback
---

(STARTER RULE — 맞으면 남기고 아니면 지운다.) 작업 한 단위는 한 사이클이다:
변경 → 검증 → 기록 → 커밋 → **push**. 별도 "push 해줘" 지시를 기다리지 않는다.
코드와 관련 작업 기록을 함께 관리한다. 작업 커밋은 버전 증가를 요구하지 않는다.
CHANGELOG의 Unreleased에 모으고 릴리스 단위로 버전을 결정한다. docs/RELEASING.md를 따른다.

**왜:** push는 소스 변경 공유이며, 패키지 배포와는 별도다. 절반만 나간 변경과
문서 어긋남이 "다 된 줄 알았던" 버그가 사는 자리다.
**적용:** 동작을 확인했으면 코드와 문서를 한 번에 커밋하고 push 까지 한다. 단 force push,
main 외 브랜치, 다른 저장소는 사전 확인한다.
