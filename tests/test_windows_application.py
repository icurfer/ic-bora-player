"""Native GIO must open the normalized Python argv, not the interpreter argv."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from bora import platform


@pytest.mark.skipif(not platform.IS_WINDOWS, reason="Windows GIO 명령줄 재해석 회귀")
@pytest.mark.parametrize('files', [[], ['한글 영상.mp4', '한글 자막.srt']])
def test_native_gio_uses_supplied_arguments(tmp_path, files):
    result = tmp_path / 'result.json'
    paths = [str(tmp_path / name) for name in files]
    script = tmp_path / 'probe.py'
    script.write_text(f'''
import json
from pathlib import Path
from gi.repository import Gio
from bora.platform.windows.application import WindowsApplication
class Probe(WindowsApplication):
    def do_activate(self):
        Path({str(result)!r}).write_text(json.dumps([]), encoding='utf-8')
        self.quit()
    def do_open(self, files, n, hint):
        Path({str(result)!r}).write_text(json.dumps([f.get_path() for f in files[:n]]), encoding='utf-8')
        self.quit()
app = Probe(application_id='com.icurfer.Bora.ArgvTest', flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE)
raise SystemExit(app.run(['bora', *{paths!r}]))
''', encoding='utf-8')
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).resolve().parents[1] / 'src'),
                                       env.get('PYTHONPATH', '')])
    subprocess.run([sys.executable, str(script), 'unexpected-native-file.mp4'],
                   env=env, check=True, timeout=15)
    assert [Path(p) for p in json.loads(result.read_text(encoding='utf-8'))] == [Path(p) for p in paths]
