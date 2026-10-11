# Bora 문서

- [버전·배포 정책](RELEASING.md): 릴리스 단위 버전과 GitHub CI 패키지 빌드·업로드.
- [작업 관리](TASK_MANAGEMENT.md): 포탈 ic-bora 스페이스와 작업 인계.
- `research/`: 공개 검토용 재현·조사 자료.
- `releases/`: 릴리스별 공개 검증·설치 안내.
- [변경 내역](../CHANGELOG.md): 사용자에게 보이는 변경과 공개 요약.

## 로컬 개발 기록

ic-praxis 개인용 범위를 사용한다. `harness/`, `docs/requirements/`, `docs/spec/`,
`docs/scope/`, `docs/deferred/`, `docs/done/`은 로컬에서 관리하며 Git에 추가하지 않는다.
이미 공개된 파일은 작업 사본을 보존하고 추적에서만 제외했다. 과거 Git 이력은 유지한다.
`scripts/check-sharing.sh`는 재추적을 검사하며 CI에서도 실행한다.

새 클론에서 개인용 하네스가 필요하면 공식 [ic-praxis](https://github.com/icurfer/ic-praxis)의
설치 절차를 검토해 별도로 설치한다. 프로젝트의 기존 지침·CI·스크립트를 덮어쓰지 않는다.
설치 후 `bash scripts/configure-sharing.sh personal`로 개인용 범위를 지정하고
`node harness/bin/praxis.mjs profile select development`를 실행한다.
프로젝트 검사는 아래 공개 검사 명령을 로컬 `harness/config/project.json`에 연결한다.

```bash
bash scripts/check-index-clean.sh
bash scripts/check-conventions.sh --all
bash scripts/check-python-tests.sh
```

GitHub CI는 이 명령을 직접 실행하므로 로컬 하네스가 없어도 검사·패키지 빌드·업로드가 가능하다.
개발 문서 수정만으로 제품 버전을 올리지 않는다. `docs/RELEASING.md`가 버전 정책의 기준이다.
