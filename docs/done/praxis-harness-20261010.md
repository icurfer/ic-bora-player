# Praxis 개발 하네스 적용

원본 icurfer/ic-praxis HEAD 96aa5b13afbdbce3e6aaf580d6163195f9813aed를 원격과 대조했다.
Bora는 앱 개발 프로젝트이므로 development를 선택했다. 기존 버전/릴리스 정책과 지침을
덮어쓰지 않고 harness 런타임·프로필·task 진입점·index 검사만 가져왔다. 라이선스는
harness/UPSTREAM_LICENSE에 보존했다.

## 프로젝트 적용

- Node.js 18+ 및 Git만 필요. npm 설치와 제품 런타임 의존성 추가 없음.
- .claude/commands/praxis-task.md, .agents/skills/praxis-task/SKILL.md를 공통 진입점으로 제공.
- 인덱스 일치 → 전체 규칙 → 하네스 회귀 → Python/GTK 검사. 패키지 로컬 빌드는 포함하지 않음.
- 검증 기록은 harness/.state에 보존하고 Git 추적에서 제외. 코드·인덱스·HEAD 변경 시 만료.
- 원본 테스트의 매커밋 버전 증가 가정은 Bora의 릴리스 단위 정책으로 조정.
- 기존 CI/release workflow가 task init/check/validate/status를 호출. 별도 praxis CI 추가 없음.
- 기존 키입력 시나리오와 GitHub deb 빌드·설치·업로드 단계 유지.

## 검증

하네스 회귀 9개 통과, 원본 praxis-gate.yml 전용 검사 1개는 Bora에 해당 workflow가 없어 skip.
실제 작업 레코드 adopt-praxis-harness를 생성하고 기획서와 범위를 연결했다.
최종 하네스 검증과 원격 CI 결과는 작업 후 기록한다.
