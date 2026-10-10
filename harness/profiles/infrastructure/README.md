# Infrastructure harness / 인프라용 — 연동 준비

이 유형은 개발용과 분리된 확장 지점입니다. **운영 실행기는 아직 구현하지 않았습니다.**
기존 운영 프로젝트를 참고해 절차를 확정한 뒤 구현합니다.

1. `harness/config/profile.json`에서 `infrastructure`를 선택합니다.
2. 사용자가 지정하는 참고 프로젝트를 `harness/config/infrastructure.json`의
   `referenceProject`에 기록합니다. 공개 가능한 프로젝트 이름이나 문서 URL만 사용하고,
   비밀정보·접속 자격증명·개인 절대 경로는 넣지 않습니다. 미지정이면 `null`을 유지합니다.
3. 이후 참고 프로젝트의 실제 운영 규약·조회/적용 구분·대상 환경·검증/복구 절차를
   조사해 인프라 실행기와 설정 형식을 설계합니다. 지금 임의의 운영 절차를 생성하지 않습니다.

`profile status`는 연동 대기 상태로 종료 코드 1을 반환합니다. 선택 명령의 성공은
사용 준비 완료를 뜻하지 않습니다. `task` 명령은 개발용 실행기로 전달되지 않고 차단됩니다.
참고 프로젝트를 기록해도 실행이 활성화되지 않습니다. CI도 자동 활성화되지 않습니다.

Common profile selection lives in `harness/src/main.mjs`. Add a separate
infrastructure implementation later; reuse only applicable shared components.
Do not assume development task size, version bumps or Git fingerprints model live
infrastructure state. Existing repository operations remain governed by their own
rules; installing this placeholder does not authorize operational changes.
