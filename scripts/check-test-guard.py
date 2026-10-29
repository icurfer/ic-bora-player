"""실제 격리 경계와 작은 메모리 상한에서의 실패를 검사한다. GPU는 사용하지 않는다."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
GUARD = str(ROOT / 'scripts/run-tests-bounded.sh')


def report_failure(kind, error, traceback):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        message = str(error).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::error::Test guard failed: ' + message, flush=True)
    sys.__excepthook__(kind, error, traceback)


sys.excepthook = report_failure


def run(*command, **settings):
    return subprocess.run(['bash', GUARD, *command], cwd=ROOT,
                          env={**os.environ, 'BORA_TEST_EXPECT_UID': str(os.getuid()), **settings}, capture_output=True,
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
assert os.getuid() == int(os.environ['BORA_TEST_EXPECT_UID'])
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

# 의도적인 OOM은 별도 선택 검사다. 일반 로컬 검증에서는 경고를 만들지 않는다.
if os.environ.get('BORA_TEST_CHECK_OOM') == '1':
    result = run(sys.executable, '-c', 'allocation = bytearray(256 * 1024 * 1024)',
                 BORA_TEST_MEMORY_MAX='64M')
    assert result.returncode != 0 and 'memory.max=67108864' in result.stderr, result
else:
    print('SKIP: intentional OOM check (requires BORA_TEST_CHECK_OOM=1)')
result = run(sys.executable, '-c', probe)
assert result.returncode == 0, result.stderr
print('test guard: required checks passed (5GiB, GPU isolation, caller uid, children, exit, timeout, invalid settings, lock, recovery)')
