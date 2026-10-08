"""버전 정책은 임시 Git 저장소에서 staged blob과 실제 Debian 정렬을 검증한다."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('version_policy', ROOT / 'scripts/version_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize('value', ['0.26.6-dev.1', '0.26.6-rc.1', '1.0.0', '1.10.12\n'])
def test_valid(value):
    assert policy.validate(value) == value.rstrip('\n')


@pytest.mark.parametrize('value', ['1.2', 'v1.2.3', '01.2.3', '1.2.3-rc.01', '1.2.3\n\n', '1.2.3+anything', '1.2.3-rc', '1.2.3 ', '1.2.3\n2.0.0'])
def test_invalid(value):
    with pytest.raises(ValueError):
        policy.validate(value)


def test_debian_candidate_sorts_before_final():
    assert policy.debian('1.2.3-rc.1') == '1.2.3~rc.1'
    subprocess.run(['dpkg', '--compare-versions', policy.debian('1.2.3-rc.1'), 'lt', '1.2.3'], check=True)
    subprocess.run(['dpkg', '--compare-versions', policy.debian('1.2.3-dev.1'), 'lt', policy.debian('1.2.3-rc.1')], check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for filename in ['scripts/check-conventions.sh', 'scripts/check_taboo.py', 'scripts/version_policy.py']:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / filename, target)
    for filename in ['AGENTS.md', 'CLAUDE.md']:
        (tmp_path / filename).write_text('<!-- praxis:shared:begin -->\nShared rules\n<!-- praxis:shared:end -->\n')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/RELEASING.md').write_text('Release policy')
    (tmp_path / 'version').write_text('1.2.3-rc.1')
    (tmp_path / 'CHANGELOG.md').write_text('## [1.2.3-rc.1]\n')
    (tmp_path / 'docs/releases').mkdir()
    (tmp_path / 'docs/releases/1.2.3-rc.1.md').write_text('GUI-E2E: passed\nUnit-tests: passed\nPlatform: Ubuntu 26.04\n')
    monkeypatch.chdir(tmp_path)
    subprocess.run(['git', 'init', '-q'], check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], check=True)
    subprocess.run(['git', 'add', '.'], check=True)
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], check=True)
    return tmp_path


def gate():
    return subprocess.run(['bash', 'scripts/check-conventions.sh'], capture_output=True, text=True)


def test_code_and_document_commits_without_bump(repo):
    (repo / 'example.py').write_text('print(1)\n')
    (repo / 'docs/RELEASING.md').write_text('Updated policy')
    subprocess.run(['git', 'add', '.'], check=True)
    result = gate()
    assert result.returncode == 0, result.stderr


def test_staged_invalid_version_not_hidden_by_worktree_fix(repo):
    (repo / 'version').write_text('1.2.3\n\n')
    subprocess.run(['git', 'add', 'version'], check=True)
    (repo / 'version').write_text('1.2.3')
    assert gate().returncode != 0


def test_agent_rule_drift_blocks(repo):
    (repo / 'AGENTS.md').write_text('<!-- praxis:shared:begin -->\nDifferent rules\n<!-- praxis:shared:end -->\n')
    subprocess.run(['git', 'add', 'AGENTS.md'], check=True)
    assert gate().returncode != 0


def test_binary_addition_blocks(repo):
    (repo / 'bora.deb').write_text('test package')
    subprocess.run(['git', 'add', 'bora.deb'], check=True)
    assert gate().returncode != 0


def test_required_policy_deletion_blocks(repo):
    subprocess.run(['git', 'rm', 'docs/RELEASING.md'], check=True, capture_output=True)
    assert gate().returncode != 0


def test_release_checks_tag_tree_and_notes(repo):
    subprocess.run(['git', 'tag', 'v1.2.3-rc.1'], check=True)
    policy.check_release('1.2.3-rc.1', 'v1.2.3-rc.1')
    with pytest.raises(ValueError):
        policy.check_release('1.2.3-rc.1', 'v1.2.3')
    (repo / 'uncommitted.txt').write_text('dirty')
    with pytest.raises(ValueError, match='깨끗한'):
        policy.check_release('1.2.3-rc.1', 'v1.2.3-rc.1')
    (repo / 'uncommitted.txt').unlink()
    (repo / 'docs/releases/1.2.3-rc.1.md').write_text('GUI-E2E: unverified\nUnit-tests: passed\nPlatform: Ubuntu 26.04\n')
    subprocess.run(['git', 'add', '.'], check=True)
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'unverified'], check=True)
    subprocess.run(['git', 'tag', '-f', 'v1.2.3-rc.1'], check=True, capture_output=True)
    with pytest.raises(ValueError, match='검증 기록'):
        policy.check_release('1.2.3-rc.1', 'v1.2.3-rc.1')


def test_development_identity_and_dev_release_block(repo):
    value = policy.development('1.2.3')
    assert value.startswith('1.2.3-dev.0+git.') and not value.endswith('.dirty')
    (repo / 'dirty.txt').write_text('change')
    assert policy.development('1.2.4-dev.1').endswith('.dirty')
    with pytest.raises(ValueError, match='개발 버전'):
        policy.check_release('1.2.4-dev.1', 'v1.2.4-dev.1')
