"""실제 격리 경계와 작은 메모리 상한에서의 실패를 검사한다. GPU는 사용하지 않는다."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
GUARD = str(ROOT / 'scripts/run-tests-bounded.sh')


def run(*command, **settings):
    return subprocess.run(['bash', GUARD, *command], cwd=ROOT,
                          env={**os.environ, **settings}, capture_output=True,
                          text=True, timeout=20)


probe = '''
from pathlib import Path
import os, subprocess, sys
group = Path('/sys/fs/cgroup' + Path('/proc/self/cgroup').read_text().strip().split('::')[1])
assert (group / 'memory.max').read_text().strip() == '5368709120'
assert (group.parent / 'memory.max').read_text().strip() == '5368709120'
assert (group / 'memory.swap.max').read_text().strip() == '0'
assert (group / 'memory.oom.group').read_text().strip() == '1'
assert not Path('/dev/dri').exists() and not Path('/dev/kfd').exists()
assert os.environ['GSK_RENDERER'] == 'cairo'
assert os.environ['LIBGL_ALWAYS_SOFTWARE'] == '1'
subprocess.run([sys.executable, '-c', "from pathlib import Path; assert not Path('/dev/dri').exists()"], check=True)
'''
result = run(sys.executable, '-c', probe)
assert result.returncode == 0, result.stderr
result = run('/bin/sh', '-c', 'exit 7')
assert result.returncode == 7, result
result = run('/bin/sleep', '10', BORA_TEST_TIMEOUT_SECONDS='1')
assert result.returncode == 124, result
result = run('/bin/true', BORA_TEST_MEMORY_MAX='invalid')
assert result.returncode == 2, result
result = run('/bin/true', XDG_RUNTIME_DIR='/nonexistent-bora-runtime', GITHUB_ACTIONS='false')
assert result.returncode == 2, result

with tempfile.TemporaryDirectory(prefix='bora-guard-') as temporary:
    marker = str(Path(temporary) / 'started')
    first = subprocess.Popen(['bash', GUARD, sys.executable, '-c',
                              'from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(2)', marker],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not Path(marker).exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert Path(marker).exists(), 'first guard did not start'
        result = run('/bin/true')
        assert result.returncode == 2 and '다른 테스트' in result.stderr, result
    finally:
        out, err = first.communicate(timeout=15)
        assert first.returncode == 0, err

# 최대 64MiB의 별도 cgroup에서 256MiB 할당을 시도한다. 호스트 OOM 재현이 아니다.
result = run(sys.executable, '-c', 'allocation = bytearray(256 * 1024 * 1024)',
             BORA_TEST_MEMORY_MAX='64M')
assert result.returncode != 0 and 'memory.max=67108864' in result.stderr, result
result = run(sys.executable, '-c', probe)
assert result.returncode == 0, result.stderr
print('test guard: 9 checks passed (5GiB, GPU isolation, children, exit, timeout, invalid settings, lock, bounded OOM, recovery)')
