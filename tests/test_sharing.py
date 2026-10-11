"""개인용 파일의 강제 추가와 기존 추적 파일을 CI에서도 차단한다."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_personal_paths_blocked_but_cached_removal_preserves_local_files(tmp_path):
    def run(*args, ok=True):
        result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
        assert (result.returncode == 0) == ok, result.stdout + result.stderr
        return result

    run('git', 'init', '-q')
    paths = ['harness/config/profile.json', 'docs/spec/private.md',
             'docs/scope/private.md', 'docs/done/private.md',
             'docs/deferred/private.md', 'docs/requirements/backlog.md']
    for name in paths:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('private')
    (tmp_path / 'docs/README.md').write_text('public')
    run('git', 'add', '.')
    gate = str(ROOT / 'scripts/check-sharing.sh')
    run('bash', gate, ok=False)
    run('bash', gate, '--all', ok=False)
    run('git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Existing tracked records')
    run('bash', gate)  # no staged changes
    run('bash', gate, '--all', ok=False)  # fresh CI checkout still catches them
    run('git', 'rm', '--cached', *paths)
    run('bash', gate)
    run('bash', gate, '--all')
    assert all((tmp_path / name).read_text() == 'private' for name in paths)
    run('bash', str(ROOT / 'scripts/configure-sharing.sh'), 'personal')
    run('git', 'check-ignore', *paths)
    run('git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Untrack private files')
    run('git', 'add', '-f', paths[0])
    run('bash', gate, ok=False)
