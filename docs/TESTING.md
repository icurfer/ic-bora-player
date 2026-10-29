# Linux 테스트 보호

단위 검사는 `BORA_TEST_PYTHON=/usr/bin/python3 bash scripts/check-python-tests.sh`로 실행한다.
특정 검사만 실행하려면 뒤에 pytest 인수를 붙인다.
GUI 시나리오와 다른 검사 명령은 `bash scripts/run-tests-bounded.sh <명령> <인수...>`로 감싼다.
Xvfb도 이 실행기 안에서 시작해야 자식 메모리에 포함된다.

실행기는 테스트와 자식 전체에 기본 **5GiB** cgroup 메모리 상한과 300초 시간 제한을 건다.
스왑을 허용하지 않으며 OOM 시 해당 테스트 묶음을 종료한다. 같은 사용자의 보호된 테스트는
하나씩만 실행한다. cgroup v2·systemd·bubblewrap·flock·timeout이 필요하며,
보호를 적용할 수 없으면 테스트를 시작하지 않는다. GitHub Actions의 전용 실행 서버에서는
비대화형 sudo로 시스템 systemd와 장치 격리를 설정한 다음,
실제 검사 명령은 원래 사용자 권한으로 실행한다. 호스트의 사용자 namespace 제한은 바꾸지 않는다.

GPU 드라이버 메모리가 프로세스 제한에 모두 포함된다고 보장할 수 없으므로,
사설 `/dev`로 `/dev/dri`와 `/dev/kfd` 등 하드웨어 GPU 장치 접근을 차단한다.
GTK는 cairo, OpenGL은 소프트웨어 렌더링을 사용한다. 실제 GPU 가속·실기 재생 통과를
이 검사로 주장하지 않는다. 사용자 앱과 설치된 플레이어의 메모리 설정은 바꾸지 않는다.

상한에 걸리면 실패로 기록하고 원인을 먼저 확인한다. 이유와 사용자 동의를 확인한 경우에만
`BORA_TEST_MEMORY_MAX=6G`처럼 명시적으로 조정한다. 시간은
`BORA_TEST_TIMEOUT_SECONDS=600`으로 조정할 수 있다. 기본 설정은 자동으로 늘어나지 않는다.
실행기를 우회한 직접 `pytest`·GUI 실행에는 이 보호가 적용되지 않는다.

`python3 scripts/check-test-guard.py`는 기본적으로 의도적인 OOM을 발생시키지 않는다.
64MiB 제한 초과 종료 검사는 `BORA_TEST_CHECK_OOM=1`로 별도 선택하며,
로컬에서는 경고가 발생한다는 설명과 사용자 확인 후에만 실행한다. GitHub의 전용 CI에서만
이 선택 검사를 자동으로 실행한다.
