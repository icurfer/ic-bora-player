#!/usr/bin/env bash
# GTK 검사를 실행한다. 패키지 빌드·설치는 이 검사에 포함하지 않는다.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
TEST_PYTHON="${BORA_TEST_PYTHON:-python3}"
args=(-m pytest -q)
if [ -n "${RUNNER_TEMP:-}" ]; then args+=(--junitxml="$RUNNER_TEMP/tests.xml"); fi
if command -v xvfb-run >/dev/null 2>&1; then
  exec xvfb-run -a "$TEST_PYTHON" "${args[@]}"
fi
exec "$TEST_PYTHON" "${args[@]}"
