# Praxis 하네스 적용

배치 위치: harness와 Claude/Codex task 진입점, 기존 GitHub CI.
설정·비밀값 위치: harness/config에 검사 명령만, 작업 기록은 무시되는 harness/.state. 비밀값 저장 없음.
기존 패턴: Bora 릴리스 단위 버전·staged gate·GitHub 빌드 업로드 유지.
개발용 프로필을 적용하고 코드/인덱스/HEAD 변경 시 검증 만료를 확인한다.
