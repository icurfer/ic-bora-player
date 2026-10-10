"""내보내기 원본 보호와 실제 ffmpeg 합치기 회귀."""
from pathlib import Path
import shutil
import subprocess

import pytest

from bora.clip.model import Clip
from bora.clip.runner import ExportJob, ExportRunner
from bora.clip.probe import probe


@pytest.fixture
def video(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg 필요')
    folder = tmp_path / "user's folder"
    folder.mkdir()
    path = folder / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=160x120:rate=10:duration=3',
                    '-c:v', 'libx264', str(path)], check=True)
    return path


@pytest.mark.parametrize('alias', ['same', 'symlink', 'hardlink', 'numbered'])
def test_source_cannot_be_export_target(video, alias):
    output = video
    join = True
    clips = [Clip(0, 1)]
    if alias in ('symlink', 'hardlink'):
        output = video.with_name('alias.mp4')
        if alias == 'symlink':
            try:
                output.symlink_to(video)
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    pytest.skip('Windows 파일 symlink 권한 필요')
                raise
        else:
            output.hardlink_to(video)
    elif alias == 'numbered':
        video = video.rename(video.with_name('part-1.mp4'))
        output = video.with_name('part.mp4')
        clips = [Clip(0, 1), Clip(1, 2)]
        join = False
    before = video.read_bytes()
    errors = []
    runner = ExportRunner(on_error=errors.append)
    assert not runner.start(ExportJob(video, clips, output, join=join))
    assert '원본' in errors[-1]
    assert video.read_bytes() == before


def test_concat_in_quoted_directory(video):
    output = video.with_name('result.mp4')
    errors = []
    runner = ExportRunner(on_error=errors.append)
    assert runner.start(ExportJob(video, [Clip(0, .8), Clip(1, 2)], output, mode='encode'))
    runner._thread.join(15)
    assert not runner.running
    assert errors == []
    assert abs(probe(output).duration - 1.8) < .15
    assert not list(video.parent.glob('.bora-clip-*'))


@pytest.mark.parametrize('cancel', [False, True])
def test_join_failure_or_cancel_preserves_previous_output(video, monkeypatch, cancel):
    output = video.with_name('result.mp4')
    output.write_bytes(b'previous result')
    runner = ExportRunner()
    run = runner._ffmpeg

    def fail_join(command, **kwargs):
        if kwargs['step'] == '이어붙이는 중':
            Path(command[-1]).write_bytes(b'incomplete result')
            runner._cancelled = cancel
            return False
        return run(command, **kwargs)

    monkeypatch.setattr(runner, '_ffmpeg', fail_join)
    assert runner.start(ExportJob(video, [Clip(0, .8), Clip(1, 2)], output, mode='encode'))
    runner._thread.join(15)
    assert not runner.running
    assert output.read_bytes() == b'previous result'
    assert not list(video.parent.glob('.bora-clip-*'))
