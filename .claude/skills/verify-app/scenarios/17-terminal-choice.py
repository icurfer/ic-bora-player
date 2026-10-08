#!/usr/bin/env python3
"""격리한 GTK 창에서 실제 Ctrl+Enter와 외부 도구 선택을 검증한다.

실제 CLI/API는 호출하지 않는다. CI 가상 X11에서만 명시 플래그로 포커스를 설정한다.
"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))


class Unverified(Exception):
    pass


def main():
    with tempfile.TemporaryDirectory(prefix='bora-terminal-e2e-') as directory:
        folder = Path(directory)
        os.environ['GSETTINGS_BACKEND'] = 'memory'
        for name in ('CONFIG', 'CACHE', 'DATA'):
            os.environ[f'XDG_{name}_HOME'] = str(folder / name.lower())
        try:
            import gi
            gi.require_version('Gtk', '4.0')
            gi.require_version('Gdk', '4.0')
            gi.require_version('GdkX11', '4.0')
            gi.require_version('Adw', '1')
            from gi.repository import Adw, Gdk, GdkX11, GLib, Gtk
            Adw.init()
            display = Gdk.Display.get_default()
            if display is None or not isinstance(display, GdkX11.X11Display):
                raise Unverified('실제 X11 GTK 디스플레이 필요')
            x = ctypes.CDLL('libX11.so.6')
            xt = ctypes.CDLL('libXtst.so.6')
        except (ImportError, ValueError, OSError, Unverified) as exc:
            print(f'미검증: {exc}', flush=True)
            return 2

        from bora.ai import workspace
        from bora.notes.panel import NotePanel
        from bora.state import State
        from bora.window import BoraWindow

        def pump(seconds=.1):
            end = time.monotonic() + seconds
            context = GLib.MainContext.default()
            while time.monotonic() < end:
                while context.pending() and time.monotonic() < end:
                    context.iteration(False)
                time.sleep(.005)

        def wait_for(predicate):
            end = time.monotonic() + 4
            while not predicate() and time.monotonic() < end:
                pump(.04)
            return predicate()

        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
        x.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XKeysymToKeycode.restype = ctypes.c_uint
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

        def ctrl_enter(window):
            connection = x.XOpenDisplay(None)
            if not connection:
                raise Unverified('X11 연결 실패')
            pressed = []
            try:
                xid = GdkX11.X11Surface.get_xid(window.get_surface())
                if os.environ.get('BORA_TEST_ISOLATED_X11') == '1':
                    x.XSetInputFocus(connection, xid, 2, 0)
                    x.XSync(connection, False)
                focused, revert = ctypes.c_ulong(), ctypes.c_int()
                x.XGetInputFocus(connection, ctypes.byref(focused), ctypes.byref(revert))
                if focused.value != xid:
                    raise Unverified('검증 창 포커스가 아니므로 키 주입 중단')
                for name in ('Control_L', 'Return'):
                    code = x.XKeysymToKeycode(connection, x.XStringToKeysym(name.encode()))
                    assert code, f'키 코드 없음: {name}'
                    assert xt.XTestFakeKeyEvent(connection, code, 1, 0), 'XTest 키 입력 실패'
                    pressed.append(code)
            finally:
                for code in reversed(pressed):
                    xt.XTestFakeKeyEvent(connection, code, 0, 0)
                x.XSync(connection, False)
                x.XCloseDisplay(connection)
            pump(.2)

        class Host(Gtk.Window):
            open_agent_terminal = BoraWindow.open_agent_terminal

            def __init__(self):
                super().__init__(title='Bora isolated terminal E2E', default_width=380, default_height=500)
                self.state = State(folder / 'state')
                self._current = folder / 'sample.mp4'
                self._current.touch()
                self._plan = None
                self.messages = []
                self._notes = NotePanel(self)
                self.set_child(self._notes)
                assert self._notes.load_for(self._current, '격리 메모')

            def toast(self, message):
                self.messages.append(message)
                return False

            def toggle_notes(self, *_args):
                pass

            def show_ai_settings(self, *_args):
                raise AssertionError('앱 AI 설정은 이 동작에서 열리면 안 됨')

        window = None
        results = []
        calls = []

        def check(name, condition):
            results.append(bool(condition))
            print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
            assert condition, name

        def fake_launch(video, note, subtitle=None, question=None, provider='codex'):
            # 호출 시점 파일 내용을 잡아 Ctrl+Enter가 저장보다 먼저 실행되는 회귀도 검출한다.
            calls.append((provider, question, Path(note).read_text(), Path(video), Path(note)))

        try:
            with patch.object(workspace, 'terminal_command', return_value='/mock/cli'), \
                    patch.object(workspace, 'launch', side_effect=fake_launch):
                window = Host()
                window.present()
                check('격리 GTK 창 표시', wait_for(lambda: window.get_mapped()))
                for index, provider in enumerate(('claude', 'codex'), start=1):
                    notes = window._notes
                    notes._terminal_choices[provider].set_active(True)
                    question = f'{provider} 현재 줄 질문'
                    notes._buffer.set_text(question)
                    notes.focus_editor()
                    pump()
                    ctrl_enter(window)
                    check(f'{provider} 실제 CtrlEnter 한 번 실행', wait_for(lambda: len(calls) == index))
                    selected, actual_question, saved, video, note = calls[-1]
                    check(f'{provider} 선택·질문 전달', selected == provider and actual_question == question)
                    check(f'{provider} 실행 전 저장·파일 일치', saved == question + '\n'
                          and video == window._current and note == notes.doc.path and not notes.doc.dirty)
                    check(f'{provider} 선택 저장', State(folder / 'state').settings.terminal_provider == provider)
                pump(.2)
                check('중복 터미널 호출 없음', len(calls) == 2)
        except Unverified as exc:
            print(f'미검증: {exc}', flush=True)
            return 2
        except Exception as exc:
            import traceback
            traceback.print_exc()
            message = str(exc).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error::Terminal E2E failed: {message}', flush=True)
            return 1
        finally:
            if window is not None:
                window._notes._cancel_autosave()
                window._notes.cancel_ask()
                window.destroy()
                pump(.1)
        print(f'{sum(results)}/{len(results)} 통과 — 실제 XTest 키입력, CLI 실행은 모의', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
