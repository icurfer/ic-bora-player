#!/usr/bin/env python3
"""AI 방식·BYOK 설정 실제 GTK 검증. 계정·보안 저장소·HTTP는 모의 객체만 사용한다."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
TEMP = tempfile.TemporaryDirectory(prefix='bora-byok-ui-')
folder = Path(TEMP.name)
os.environ['GSETTINGS_BACKEND'] = 'memory'
for key, suffix in [('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data')]:
    os.environ[key] = str(folder / suffix)
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from bora.app import BoraApplication
from bora.ai import api

results = []
vault = {'key': '', 'reads': 0}
network = {'fail': False, 'calls': []}


def check(label, condition):
    results.append(bool(condition))
    print(f"[{'통과' if condition else '실패'}] {label}", flush=True)
    assert condition, label


def pump(seconds=.1):
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending() and time.monotonic() < end:
            ctx.iteration(False)
        time.sleep(.005)


def ready(dialog):
    end = time.monotonic() + 4
    while dialog._busy and time.monotonic() < end:
        pump(.03)
    check('비동기 작업 완료', not dialog._busy)
    pump()


def scroller_for(dialog):
    child = dialog.get_content().get_first_child()
    while child is not None:
        if isinstance(child, Gtk.ScrolledWindow):
            return child
        child = child.get_next_sibling()
    raise AssertionError('설정 스크롤 영역 없음')


def shot(dialog, name, bottom=False):
    destination = os.environ.get('BORA_REVIEW_SHOTS')
    if not destination:
        return
    dialog.present()
    pump(.2)
    if bottom:
        adjustment = scroller_for(dialog).get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        pump()
    paintable = Gtk.WidgetPaintable.new(dialog)
    try:
        dialog.queue_draw()
        for _ in range(10):
            pump(.08)
            snapshot = Gtk.Snapshot.new()
            paintable.snapshot(snapshot, dialog.get_width(), dialog.get_height())
            node = snapshot.to_node()
            if node is not None:
                break
        texture = dialog.get_renderer().render_texture(node, None)
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        texture.save_to_png(str(target / (name + '.png')))
    finally:
        paintable.set_widget(None)


def fake_open(key, endpoint, body=None):
    network['calls'].append((endpoint, body))
    if network['fail']:
        raise api.AIError('API 키 인증에 실패했습니다. 키를 확인하거나 새 키를 입력하세요.')
    return io.BytesIO(json.dumps({'id': endpoint.split('/')[-1]}).encode())


class Probe(BoraApplication):
    def do_activate(self):
        super().do_activate()
        self.win = self.props.active_window
        GLib.timeout_add(250, self.run_checks)

    def run_checks(self):
        w = self.win
        dialog = None
        try:
            w.show_ai_settings()
            dialog = w._ai_settings
            ready(dialog)
            check('처음에는 로컬 Codex 기본', dialog.provider.get_selected() == 0 and api.load_config()['provider'] == 'codex')
            check('로컬 기본에서 키 저장소 미접근', vault['reads'] == 0)
            check('API 키 입력은 기본 숨김', not dialog.api_box.get_visible())
            shot(dialog, '01-codex-default')
            dialog.provider.set_selected(1)
            pump()
            check('API 선택만으로 적용되지 않음', dialog.api_box.get_visible() and api.load_config()['provider'] == 'codex')
            check('키 입력 가림 위젯', isinstance(dialog.key_entry, Gtk.PasswordEntry))
            shot(dialog, '02-api-selected')
            dialog.check.emit('clicked')
            ready(dialog)
            check('빈 키 연결 안내', '키를 입력' in dialog.status.get_text() and not network['calls'])
            dialog.key_entry.set_text('test-credential-one')
            dialog.check.emit('clicked')
            ready(dialog)
            check('연결 시험은 인증·모델 조회만', network['calls'][-1] == ('models/' + api.DEFAULT_MODEL, None))
            check('연결 시험이 키·방식을 저장하지 않음', vault['key'] == '' and api.load_config()['provider'] == 'codex')
            check('실제 질문 미전송 안내', '질문' in dialog.status.get_text() and '않' in dialog.status.get_text())
            dialog.apply.emit('clicked')
            ready(dialog)
            check('적용해야 API와 키 저장', api.load_config()['provider'] == 'openai' and vault['key'] == 'test-credential-one')
            check('저장 후 키 원문 제거', dialog.key_entry.get_text() == '' and '키가 있습니다' in dialog.key_status.get_text())
            check('패널 비용 경로 표시', 'OpenAI API' in w._chat._status.get_text())
            shot(dialog, '03-api-applied', bottom=True)
            dialog.close()
            pump()
            w.show_ai_settings()
            dialog = w._ai_settings
            ready(dialog)
            check('재열기 저장방식 복원·키 비노출', dialog.provider.get_selected() == 1 and dialog.key_entry.get_text() == '')
            dialog.apply.emit('clicked')
            ready(dialog)
            check('빈 입력 적용은 저장키 유지', vault['key'] == 'test-credential-one')
            dialog.key_entry.set_text('test-credential-two')
            network['fail'] = True
            dialog.check.emit('clicked')
            ready(dialog)
            check('인증 실패 원인·입력 보존', '인증에 실패' in dialog.status.get_text() and dialog.key_entry.get_text() == 'test-credential-two')
            check('인증 실패가 기존 저장키 변경하지 않음', vault['key'] == 'test-credential-one')
            shot(dialog, '04-auth-error', bottom=True)
            network['fail'] = False
            dialog.model_entry.set_text('bad model /')
            dialog.apply.emit('clicked')
            ready(dialog)
            check('잘못된 모델이 기존 키를 바꾸지 않음', vault['key'] == 'test-credential-one')
            dialog.model_entry.set_text(api.DEFAULT_MODEL)
            with patch.object(api.credentials, 'write', side_effect=RuntimeError('test vault failure')):
                dialog.apply.emit('clicked')
                ready(dialog)
                check('저장소 오류를 저장 성공으로 표시하지 않음', '저장소' in dialog.status.get_text() and vault['key'] == 'test-credential-one')
            with patch.object(api, 'save_config', side_effect=api.AIError('설정 폴더 저장 실패')):
                dialog.apply.emit('clicked')
                ready(dialog)
                check('키 저장 후 설정 실패의 부분 저장 안내', vault['key'] == 'test-credential-two'
                      and '키는 저장' in dialog.status.get_text() and '실패' in dialog.status.get_text())
            dialog.delete.emit('clicked')
            ready(dialog)
            check('명시 삭제·상태 표시', vault['key'] == '' and '없습니다' in dialog.key_status.get_text())
            check('삭제가 로컬로 자동전환하지 않음', api.load_config()['provider'] == 'openai')
            shot(dialog, '05-key-deleted', bottom=True)
            dialog.provider.set_selected(0)
            dialog.apply.emit('clicked')
            ready(dialog)
            check('명시적 로컬 복귀', api.load_config()['provider'] == 'codex')
            dialog.provider.set_selected(1)
            dialog.set_default_size(360, 420)
            pump(.3)
            scroller_for(dialog).get_vadjustment().set_value(0)
            pump()
            print(f'설정 좁은 창 요청360x420 / 실제{dialog.get_width()}x{dialog.get_height()}')
            check('좁은 창 가로 크기', dialog.get_width() <= 400)
            shot(dialog, '06-narrow-top')
            scroller = scroller_for(dialog)
            adjustment = scroller.get_vadjustment()
            adjustment.set_value(adjustment.get_upper())
            pump()
            check('좁은 창 하단 설정 접근', adjustment.get_value() > 0 and dialog.apply.get_mapped())
            shot(dialog, '07-narrow-actions')
            style = Adw.StyleManager.get_default()
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            pump()
            shot(dialog, '08-light-actions')
        except Exception:
            import traceback
            traceback.print_exc()
            results.append(False)
        finally:
            if dialog is not None:
                dialog.close()
            w._on_close()
            self.quit()
        return False


def main():
    def read_key():
        vault['reads'] += 1
        return vault['key']
    with ExitStack() as stack:
        stack.enter_context(patch.object(api.credentials, 'read', side_effect=read_key))
        stack.enter_context(patch.object(api.credentials, 'write', side_effect=lambda key: vault.update(key=key)))
        stack.enter_context(patch.object(api.credentials, 'delete', side_effect=lambda: vault.update(key='')))
        stack.enter_context(patch.object(api, '_open', side_effect=fake_open))
        Probe(non_unique=True).run([sys.argv[0]])
    print(f'{sum(results)}/{len(results)} 통과')
    return 0 if results and all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
