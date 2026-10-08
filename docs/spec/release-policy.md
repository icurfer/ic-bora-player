# 버전·배포 규칙 전환

요구: 개발 작업마다 버전 증가하는 규칙을 폐기하고 오픈소스 배포 관례에 맞춘다.
배치 위치: AGENTS/CLAUDE 공통 지침, docs/RELEASING.md, scripts 버전 검사와 GitHub Actions.
설정·비밀값 위치: version 한 곳, CI 인증은 GitHub 제공 토큰을 사용하고 저장소에 저장하지 않는다.
기존 패턴: staged blob 검사는 유지, 비밀값·금칙어 검사 유지.
공개 이력 보존, dist 추적 해제, 개발본/후보/정식 구분, GitHub 서버에서 검사·deb 빌드·업로드. 개발본은 artifact, 출시 태그는 Draft Release로 제공한다.
