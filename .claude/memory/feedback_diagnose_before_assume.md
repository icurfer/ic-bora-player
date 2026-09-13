---
name: feedback_diagnose_before_assume
description: 증상 보고를 받으면 추정하지 말고 실제 탐침으로 재현부터 한다
metadata:
  type: feedback
---

(STARTER RULE — 맞으면 남기고 아니면 지운다.) "안 된다", "안 보인다" 류 보고를 받으면 원인을
추정해 코드를 바꾸기 전에 구체적인 탐침으로 재현한다(요청 추적, DB 카운트, 실패하는 테스트).
**사용자가 제시한 가설도 검증 대상**이지 전제가 아니다.

**왜:** 추정으로 고치면 증상만 가려지고 원인이 남아 재발한다.
**적용:** 관찰 → 진단 → 변경 순서. [[feedback_no_quick_fix]] 도 함께 본다.
