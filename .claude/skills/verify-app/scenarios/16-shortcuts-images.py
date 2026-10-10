#!/usr/bin/env python3
"""실제 GTK 키 이벤트와 메모 이미지의 두 제공자 전달을 격리 검증한다."""
import base64
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
TEMP = tempfile.TemporaryDirectory(prefix='bora-images-ui-')
folder = Path(TEMP.name)
os.environ['GSETTINGS_BACKEND'] = 'memory'
for key, suffix in [('XDG_CONFIG_HOME','config'), ('XDG_CACHE_HOME','cache'), ('XDG_DATA_HOME','data')]:
    os.environ[key] = str(folder / suffix)
import gi
gi.require_version('Gtk','4.0'); gi.require_version('Gdk','4.0'); gi.require_version('GdkX11','4.0')
from gi.repository import Gtk, Gdk, GdkX11, GLib
from bora.app import BoraApplication
from bora.ai import api, client, workspace
from PIL import Image

results = []
requests = []
local_images = []


def check(name, condition):
    results.append(bool(condition))
    print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
    assert condition, name


def pump(seconds=.1):
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending() and time.monotonic() < end:
            ctx.iteration(False)
        time.sleep(.005)


def wait_for(condition):
    # 소프트웨어 렌더링 중 worker/GLib 응답도 기다린다. 무한 대기는 하지 않는다.
    end = time.monotonic() + 10
    while not condition() and time.monotonic() < end:
        pump(.04)
    return condition()


def keypress(window, names):
    """사용자 다른 창에는 키를 보내지 않는다. 포커스 XID 불일치는 검증 실패다."""
    x = ctypes.CDLL('libX11.so.6')
    xt = ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]; x.XOpenDisplay.restype = ctypes.c_void_p
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
    x.XStringToKeysym.argtypes = [ctypes.c_char_p]; x.XStringToKeysym.restype = ctypes.c_ulong
    x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; x.XKeysymToKeycode.restype = ctypes.c_uint
    x.XFlush.argtypes = [ctypes.c_void_p]
    xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x.XOpenDisplay(None)
    assert display, 'X11 display 접근 필요'
    pressed = []
    try:
        focused, revert = ctypes.c_ulong(), ctypes.c_int()
        x.XGetInputFocus(display, ctypes.byref(focused), ctypes.byref(revert))
        assert focused.value == GdkX11.X11Surface.get_xid(window.get_surface()), '검증 창이 실제 포커스가 아니므로 키 주입 중단'
        for name in names:
            code = x.XKeysymToKeycode(display, x.XStringToKeysym(name.encode()))
            assert code, name
            xt.XTestFakeKeyEvent(display, code, 1, 0)
            pressed.append(code)
    finally:
        for code in reversed(pressed):
            xt.XTestFakeKeyEvent(display, code, 0, 0)
        x.XFlush(display)
        x.XCloseDisplay(display)
    pump(.2)


def shot(window, name):
    destination = os.environ.get('BORA_REVIEW_SHOTS')
    if not destination:
        return
    window.present(); window.player.paused = True
    paintable = Gtk.WidgetPaintable.new(window)
    try:
        window.queue_draw()
        for _ in range(12):
            pump(.1)
            snapshot = Gtk.Snapshot.new()
            paintable.snapshot(snapshot, window.get_width(), window.get_height())
            node = snapshot.to_node()
            if node is not None:
                break
        target = Path(destination); target.mkdir(parents=True, exist_ok=True)
        window.get_renderer().render_texture(node, None).save_to_png(str(target / (name + '.png')))
    finally:
        paintable.set_widget(None)


def fake_open(key, endpoint, body=None):
    requests.append(body)
    events = [{'type':'response.output_text.delta', 'delta':'모의 이미지 설명'}, {'type':'response.completed', 'response':{'usage':{}}}]
    return io.BytesIO(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events))


class FakeSession:
    def __init__(self, *args):
        self.work = tempfile.TemporaryDirectory(prefix='bora-image-worker-')
        self.pending = []
    def __enter__(self): return self
    def __exit__(self, *args): self.work.cleanup()
    def require_chatgpt(self): pass
    def rpc(self, method, params):
        if method == 'thread/start': return {'thread':{'id':'sample-thread'}}
        for item in params['input']:
            if item['type'] == 'localImage':
                local_images.append(Path(item['path']).read_bytes())
        self.pending = [
            {'method':'item/agentMessage/delta','params':{'threadId':'sample-thread','turnId':'sample-turn','itemId':'sample-item','delta':'모의 Codex 이미지 설명'}},
            {'method':'turn/completed','params':{'threadId':'sample-thread','turn':{'status':'completed'}}}]
        return {'turn':{'id':'sample-turn'}}


class Probe(BoraApplication):
    def do_activate(self):
        super().do_activate()
        self.win = self.props.active_window
        self.win.player.volume = 0
        GLib.timeout_add(1000, self.run_checks)
    def run_checks(self):
        w = self.win
        try:
            w.show_chat(); w.present(); pump(.3)
            # 가상 X11 소프트웨어 재생이 idle 응답 처리를 굶기지 않게 한다.
            # 이 시나리오는 입력·첨부 검증이다. 실제 재생 회귀는 시나리오01에서 검사한다.
            w.player.paused = True
            notes, chat = w._notes, w._chat
            notes._buffer.set_text('메모 질문'); notes.focus_editor(); pump()
            with patch.object(w,'open_agent_terminal',return_value=True) as terminal:
                keypress(w,['Control_L','Return'])
                check('실제 메모 CtrlEnter 외부 터미널 호출', terminal.call_count == 1)
                keypress(w,['Control_L','Shift_L','Return'])
                check('메모 CtrlShiftEnter가 기본 호출 안 함', terminal.call_count == 1)
                check('메모 CtrlShiftEnter는 앱 질문 초안', chat._text(chat._input.get_buffer()) == '메모 질문' and not requests)
            notes._terminal_choices['claude'].set_active(True)
            notes._buffer.set_text('Claude 질문 전달'); notes.focus_editor(); pump()
            with patch.object(workspace, 'terminal_command', return_value='/mock/claude'), patch.object(workspace, 'launch') as launch:
                keypress(w,['Control_L','Return'])
                check('실제 CtrlEnter 선택한 Claude 터미널 호출', wait_for(lambda: launch.call_count == 1)
                      and launch.call_args.kwargs.get('provider') == 'claude')
                check('Claude에 현재 줄 전달 전 메모 저장', launch.call_args.args[3] == 'Claude 질문 전달'
                      and 'Claude 질문 전달' in notes.doc.path.read_text())
            notes._terminal_choices['codex'].set_active(True)
            notes.focus_editor(); pump()
            with patch.object(notes,'insert_screenshot') as capture:
                keypress(w,['Control_L','Shift_L','S'])
                check('실제 메모 CtrlShiftS 캡처 호출', capture.call_count == 1)
            notes._buffer.set_text('메모 저장 검사'); notes.focus_editor(); pump()
            keypress(w,['Control_L','s'])
            # NoteDocument.save는 끝 개행을 보장한다. 편집 버퍼와 파일의 계약을 비교한다.
            expected = notes._text()
            if expected and not expected.endswith('\n'):
                expected += '\n'
            check('실제 메모 CtrlS 저장', notes.doc.path.read_text() == expected)
            keypress(w,['Control_L','t'])
            check('실제 메모 CtrlT 현재 시각', '[' in notes._text())
            notes._buffer.set_text('이미지 질문\n![00:00:01](a.assets/sample.png)')
            notes.save(); chat.refresh_images()
            check('이미지 기본 포함·개수 안내', chat.image_check.get_active() and '1장' in chat._image_status.get_text())
            check('AI CtrlEnter 안내 상시 표시', chat._key_hint.get_mapped() and 'Ctrl+Enter' in chat._key_hint.get_text())
            phases = [c.get_propagation_phase() for c in chat._input.observe_controllers() if isinstance(c,Gtk.EventControllerKey)]
            check('AI 키 처리 CAPTURE', Gtk.PropagationPhase.CAPTURE in phases)
            api.save_config('openai',api.DEFAULT_MODEL)
            with patch.object(api,'get_key',return_value='test-credential'), patch.object(api,'_open',side_effect=fake_open):
                chat.set_question('이미지를 설명해 주세요'); pump()
                keypress(w,['Return'])
                check('AI Enter는 줄바꿈', '\n' in chat._text(chat._input.get_buffer()) and not requests)
                keypress(w,['Control_L','Shift_L','Return'])
                check('AI CtrlShiftEnter는 전송하지 않음', not requests)
                keypress(w,['Control_L','Return'])
                check('실제 AI CtrlEnter 전송 완료', wait_for(lambda: chat._runner is None and bool(requests)))
                content = requests[-1]['input'][0]['content']
                image = next(item for item in content if item['type']=='input_image')
                check('API에 실제 PNG 바이트 첨부', base64.b64decode(image['image_url'].split(',')[1]) == (folder/'videos/a.assets/sample.png').read_bytes())
                check('기록은 파일 이름만 보존', chat.doc.messages[-2].get('attachments') == ['sample.png'])
                chat.context_check.set_active(False); chat.image_check.set_active(False)
                chat.set_question('이미지 없이 질문'); chat.send()
                check('이미지 없이 요청 완료', wait_for(lambda: chat._runner is None))
                check('이미지 해제시 텍스트만 전송', isinstance(requests[-1]['input'],str))
                chat.image_check.set_active(True)
                notes._buffer.set_text('\n'.join(f'![{i}](a.assets/{i}.png)' for i in range(5)))
                chat.set_question('초과 질문 보존')
                check('5장 초과 전송 차단·초안 보존', not chat.send() and '4장' in chat._image_status.get_text() and chat._text(chat._input.get_buffer())=='초과 질문 보존')
                shot(w,'02-image-limit')
                notes._buffer.set_text('![outside](../outside.png)')
                check('메모 폴더 밖 첨부 차단', not chat.send() and '폴더 밖' in chat._image_status.get_text())
            notes._buffer.set_text('![sample](a.assets/sample.png)'); notes.save()
            api.save_config('codex',api.DEFAULT_MODEL)
            with patch.object(client,'Session',FakeSession), patch.object(client,'ensure_ready',return_value=(True,'ready')), patch('bora.ai.panel.ensure_ready',return_value=(True,'ready')):
                chat.set_question('Codex 이미지 확인'); chat.send()
                check('Codex 이미지 요청 완료', wait_for(lambda: chat._runner is None and bool(local_images)))
                check('Codex에 실제 이미지 임시파일 전달', local_images[-1] == (folder/'videos/a.assets/sample.png').read_bytes())
            w.set_default_size(960,560); pump(.3)
            def inside(widget):
                found, bounds = widget.compute_bounds(w)
                return (widget.get_mapped() and found and bounds.get_width() > 0
                        and bounds.get_height() > 0 and bounds.get_x() >= 0
                        and bounds.get_y() >= 0
                        and bounds.get_x() + bounds.get_width() <= w.get_width() + 1
                        and bounds.get_y() + bounds.get_height() <= w.get_height() + 1)
            # 요청 크기에는 창 장식이 포함될 수 있다. 실제 콘텐츠 안의 접근성을 검사한다.
            check('960x560 두 입력과 AI 전송 접근', w.get_width() <= 960 and w.get_height() <= 560
                  and all(inside(widget) for widget in (notes._view, chat._input, chat.send_button)))
            shot(w,'01-images-shortcuts')
            notes._shortcut_button.popup(); pump(.2)
            check('메모 단축키 도움 열림', notes._shortcut_button.get_popover().get_visible())
            shot(w,'03-shortcut-help')
            notes._shortcut_button.popdown()
            notes.focus_editor(); pump()
            keypress(w, ['Control_L', 'w'])
            check('실제 CtrlW 정상 종료', wait_for(lambda: not w.get_visible() and not w.player.alive))
        except Exception:
            import traceback
            traceback.print_exc(); results.append(False)
        finally:
            if w.player.alive: w.player.close()
            self.quit()
        return False


def main():
    Gtk.init_check()
    if Gdk.Display.get_default() is None:
        print('미검증: GTK 디스플레이에 접근할 수 없어 단축키·이미지 GUI 검사를 실행하지 못했습니다.', flush=True)
        return 2
    directory=folder/'videos/a.assets'; directory.mkdir(parents=True)
    for name in ['sample',*[str(i) for i in range(5)]]:
        Image.new('RGB',(48,32),(30,150,230)).save(directory/(name+'.png'))
    Image.new('RGB',(4,4)).save(folder/'outside.png')
    video=folder/'videos/a.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=25:duration=20','-c:v','libx264','-preset','ultrafast',str(video)],check=True)
    Probe(non_unique=True).run([sys.argv[0],str(video)])
    if not results:
        print('미검증: GUI 초기화 또는 실행 실패로 검증 항목이 실행되지 않았습니다.', flush=True)
    else:
        print(f'{sum(results)}/{len(results)} 통과')
    return 0 if results and all(results) else 1

if __name__=='__main__': raise SystemExit(main())
