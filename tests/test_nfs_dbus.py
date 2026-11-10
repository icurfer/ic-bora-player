"""실제 사용자나 시스템 버스를 쓰지 않는 권한 서비스 메시지 검증."""
from pathlib import Path
import shutil
import subprocess
import sys
import pytest


def test_broker_over_private_dbus():
    if not shutil.which('dbus-run-session'):
        pytest.skip('dbus-run-session 필요')
    script = Path(__file__).with_name('nfs_dbus_probe.py')
    result = subprocess.run(['dbus-run-session', '--', sys.executable, str(script)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'disconnect cleanup passed' in result.stdout
