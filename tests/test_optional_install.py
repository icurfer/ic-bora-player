"""선택 기능 설치 스크립트와 런타임 경로가 같은 곳을 가리킨다."""
from pathlib import Path
import os
import subprocess

import pytest
from bora.ai import client
from bora.stt import install

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('kind,module,folder', [('ai', client, '.venv'), ('stt', install, '.venv-stt')])
def test_installed_script_and_runtime_agree(tmp_path, monkeypatch, kind, module, folder):
    data = tmp_path / 'data with spaces'
    monkeypatch.setattr(module, 'repo_root', lambda: data / 'bora')
    monkeypatch.setattr(module.platform_paths, 'data_dir', lambda: data / 'bora')
    env = {**os.environ, 'XDG_DATA_HOME': str(data)}
    result = subprocess.run(['bash', str(ROOT / f'scripts/install-{kind}.sh'), '--print-path'],
                            env=env, capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) / 'bin/python' == module.venv_python()


@pytest.mark.parametrize('module,folder', [(client, '.venv'), (install, '.venv-stt')])
def test_development_venv_and_user_fallback(tmp_path, monkeypatch, module, folder):
    repo = tmp_path / 'repo'
    user = tmp_path / 'user'
    monkeypatch.setattr(module, 'repo_root', lambda: repo)
    monkeypatch.setattr(module.platform_paths, 'data_dir', lambda: user)
    assert module.venv_python() == user / folder / 'bin/python'
    local = repo / folder / 'bin/python'
    local.parent.mkdir(parents=True)
    local.touch()
    assert module.venv_python() == local
