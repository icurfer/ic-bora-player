#!/usr/bin/env bash
# Linux 테스트와 자식을 하나의 메모리 제한 안에서 실행한다.
set -euo pipefail
fail() { echo "테스트 보호 실패: $*" >&2; exit 2; }

if [ "${1:-}" = --inside ]; then
  shift
  group="$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)"
  case "$group" in */bora-tests-*.scope) ;; *) fail '전용 cgroup이 아닙니다';; esac
  control="/sys/fs/cgroup$group"
  [ "$(cat "$control/memory.max")" != max ] || fail '메모리 상한이 없습니다'
  [ "$(cat "$control/memory.swap.max")" = 0 ] || fail '스왑이 차단되지 않았습니다'
  echo 1 > "$control/memory.oom.group"
  [ "$(cat "$control/memory.oom.group")" = 1 ] || fail '묶음 종료 설정 실패'
  [ -f /usr/share/glvnd/egl_vendor.d/50_mesa.json ] || fail 'Mesa EGL 필요'
  vulkan=/dev/null
  for driver in /usr/share/vulkan/icd.d/lvp_icd*.json; do
    if [ -f "$driver" ]; then vulkan="$driver"; break; fi
  done
  ulimit -c 0
  drop=()
  if [ "${GITHUB_ACTIONS:-}" = true ] && [ "$(id -u)" = 0 ] && [ "${SUDO_UID:-0}" != 0 ]; then
    # CI에서는 root로 장치를 격리한 다음 원래 사용자로 명령을 실행한다.
    # 격리 전에 권한을 낮추면 실행 서버의 uid-map 제한에 걸린다.
    drop=(setpriv --reuid="$SUDO_UID" --regid="$SUDO_GID" --init-groups)
  fi
  echo "테스트 보호: memory.max=$(cat "$control/memory.max") bytes, swap=0, GPU 장치 격리" >&2
  exec bwrap --bind / / --dev /dev --die-with-parent -- \
    "${drop[@]}" env GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe \
    __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json \
    __GLX_VENDOR_LIBRARY_NAME=mesa VK_DRIVER_FILES="$vulkan" "$@"
fi

[ "$#" -gt 0 ] || fail '실행할 명령이 필요합니다'
current_group="$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)"
case "$current_group" in
  */bora-tests.slice/bora-tests-*.scope) exec bash "$0" --inside "$@" ;;
esac
for dependency in systemd-run systemctl flock bwrap timeout; do
  command -v "$dependency" >/dev/null || fail "$dependency 필요"
done
[ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ] || fail 'cgroup v2 필요'
limit="${BORA_TEST_MEMORY_MAX:-5G}"
seconds="${BORA_TEST_TIMEOUT_SECONDS:-300}"
[[ "$limit" =~ ^[1-9][0-9]*[MG]$ ]] || fail '메모리 설정은 5G, 512M 형태로 지정하세요'
[[ "$seconds" =~ ^[1-9][0-9]*$ ]] && [ "$seconds" -le 3600 ] || fail '시간 제한은 1~3600초입니다'

# 같은 사용자의 다른 체크아웃에서도 겹쳐 실행하지 않는다.
runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if { [ ! -d "$runtime" ] || [ ! -O "$runtime" ]; } && [ "${GITHUB_ACTIONS:-}" = true ]; then
  runtime="${RUNNER_TEMP:-}"
fi
[ -d "$runtime" ] && [ -O "$runtime" ] || fail '사용자 runtime 디렉터리 필요'
exec 9>"$runtime/bora-tests.lock"
flock -n 9 || fail '다른 테스트가 실행 중입니다. 종료 후 하나씩 실행하세요'
runner=(systemd-run --user)
manager=(systemctl --user)
if [ "${GITHUB_ACTIONS:-}" = true ]; then
  # CI에서는 사용자 버스 유무와 관계없이 장치 격리를 위한 root 경로를 쓴다.
  sudo -n true || fail 'CI systemd 권한이 없습니다'
  command -v setpriv >/dev/null || fail 'CI setpriv 필요'
  runner=(sudo -n -E systemd-run)
  manager=(sudo -n systemctl)
else
  systemctl --user show-environment >/dev/null 2>&1 || fail '사용자 systemd에 연결할 수 없습니다'
fi
# 상위 slice도 제한해 중단 직후 남은 자식과 다음 실행의 합계까지 보호한다.
"${manager[@]}" set-property --runtime bora-tests.slice "MemoryMax=$limit" MemorySwapMax=0
script="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
unit="bora-tests-$(id -u)-$$"
"${runner[@]}" --scope --quiet --unit="$unit" --slice=bora-tests.slice \
  -p "MemoryMax=$limit" -p MemorySwapMax=0 -p "RuntimeMaxSec=$((seconds + 10))" \
  timeout --signal=TERM --kill-after=5s "${seconds}s" bash "$script" --inside "$@"
