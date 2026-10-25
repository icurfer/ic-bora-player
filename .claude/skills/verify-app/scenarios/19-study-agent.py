#!/usr/bin/env python3
"""격리 GTK 학습 에이전트 흐름. 실제 영상 캡처, AI 요약은 모의 제공자다."""
import os
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    with tempfile.TemporaryDirectory(prefix='bora-study-agent-') as directory:
        folder = Path(directory)
        os.environ['GSETTINGS_BACKEND'] = 'memory'
        for key in ('CONFIG', 'CACHE', 'DATA'):
            os.environ[f'XDG_{key}_HOME'] = str(folder / key.lower())
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw, Gdk, GLib, Gtk
        Adw.init()
        if Gdk.Display.get_default() is None:
            print('미검증: GTK 디스플레이 없음')
            return 2
        from bora.app import BoraApplication
        from bora.ai import client, api
        from bora.ai.history import Conversation
        from bora.state import State
        results, runners = [], []
        window = app = None

        def pump(seconds=.15):
            end = time.monotonic() + seconds
            context = GLib.MainContext.default()
            while time.monotonic() < end:
                while context.pending() and time.monotonic() < end:
                    context.iteration(False)
                time.sleep(.005)

        def check(name, condition):
            results.append(bool(condition))
            print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
            assert condition, name

        def text(buffer):
            return buffer.get_text(*buffer.get_bounds(), True)

        def shot(name, target=None):
            destination = os.environ.get('BORA_REVIEW_SHOTS')
            if not destination:
                return
            target = target or window
            paintable = Gtk.WidgetPaintable.new(target)
            try:
                node = None
                for _ in range(10):
                    target.queue_draw()
                    pump(.08)
                    snapshot = Gtk.Snapshot.new()
                    paintable.snapshot(snapshot, target.get_width(), target.get_height())
                    node = snapshot.to_node()
                    if node is not None:
                        break
                assert node is not None
                path = Path(destination) / (name + '.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                assert target.get_native().get_renderer().render_texture(node, None).save_to_png(str(path))
                print('캡처:', path, flush=True)
            finally:
                paintable.set_widget(None)

        def inside(widget):
            ok, bounds = widget.compute_bounds(window)
            return (ok and widget.get_mapped() and bounds.get_width() > 0 and bounds.get_height() > 0
                    and bounds.get_x() >= -1 and bounds.get_y() >= -1
                    and bounds.get_x() + bounds.get_width() <= window.get_width() + 1
                    and bounds.get_y() + bounds.get_height() <= window.get_height() + 1)

        def descendants(widget):
            yield widget
            child = widget.get_first_child()
            while child is not None:
                yield from descendants(child)
                child = child.get_next_sibling()

        def actual_key(name):
            # CI/검증용 격리 X11만 허용하며 사용자 데스크톱 포커스는 바꾸지 않는다.
            assert os.environ.get('BORA_TEST_ISOLATED_X11') == '1'
            gi.require_version('GdkX11', '4.0')
            from gi.repository import GdkX11
            assert isinstance(Gdk.Display.get_default(), GdkX11.X11Display)
            x, xt = ctypes.CDLL('libX11.so.6'), ctypes.CDLL('libXtst.so.6')
            x.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x.XOpenDisplay.restype = ctypes.c_void_p
            x.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
            x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x.XStringToKeysym.argtypes = [ctypes.c_char_p]
            x.XStringToKeysym.restype = ctypes.c_ulong
            x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            x.XKeysymToKeycode.restype = ctypes.c_uint
            xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            display = x.XOpenDisplay(None)
            assert display
            code = None
            try:
                xid = GdkX11.X11Surface.get_xid(window.get_surface())
                x.XSetInputFocus(display, xid, 2, 0)
                x.XSync(display, False)
                focused, revert = ctypes.c_ulong(), ctypes.c_int()
                x.XGetInputFocus(display, ctypes.byref(focused), ctypes.byref(revert))
                assert focused.value == xid, '키 주입 전 검증 창 포커스 확인 실패'
                code = x.XKeysymToKeycode(display, x.XStringToKeysym(name.encode()))
                assert code and xt.XTestFakeKeyEvent(display, code, 1, 0)
            finally:
                if code:
                    xt.XTestFakeKeyEvent(display, code, 0, 0)
                x.XSync(display, False)
                x.XCloseDisplay(display)
            pump(.2)

        def actual_click(widget):
            assert os.environ.get('BORA_TEST_ISOLATED_X11') == '1'
            from gi.repository import GdkX11
            x, xt = ctypes.CDLL('libX11.so.6'), ctypes.CDLL('libXtst.so.6')
            x.XOpenDisplay.restype = ctypes.c_void_p
            x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x.XDefaultRootWindow.restype = ctypes.c_ulong
            x.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                               ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                                               ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong)]
            x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x.XCloseDisplay.argtypes = [ctypes.c_void_p]
            xt.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
            xt.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            display = x.XOpenDisplay(None)
            assert display
            try:
                xid = GdkX11.X11Surface.get_xid(window.get_surface())
                left, top, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
                assert x.XTranslateCoordinates(display, xid, x.XDefaultRootWindow(display), 0, 0,
                                              ctypes.byref(left), ctypes.byref(top), ctypes.byref(child))
                ok, bounds = widget.compute_bounds(window)
                assert ok and widget.get_mapped()
                assert xt.XTestFakeMotionEvent(display, -1, left.value + int(bounds.get_x() + bounds.get_width() / 2),
                                              top.value + int(bounds.get_y() + bounds.get_height() / 2), 0)
                assert xt.XTestFakeButtonEvent(display, 1, 1, 0)
                assert xt.XTestFakeButtonEvent(display, 1, 0, 0)
                x.XSync(display, False)
            finally:
                x.XCloseDisplay(display)
            pump(.2)

        class FakeRunner:
            def __init__(self, **callbacks):
                self.callbacks = callbacks
                self.cancelled = False
                runners.append(self)
            def ask(self, question):
                self.question = question
                return True
            def cancel(self):
                self.cancelled = True
            def finish(self, answer='## 모의 학습 요약\n질문과 답변의 핵심'):
                self.callbacks['on_delta'](answer)
                self.callbacks['on_done']()

        try:
            video = folder / '학습 영상.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=4', '-c:v', 'libx264',
                            '-preset', 'ultrafast', str(video)], check=True, timeout=30)
            video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:03,900\n학습 검토 자막\n', encoding='utf-8')
            app = BoraApplication(non_unique=True)
            app.register(None)
            app.activate()
            window = app.props.active_window
            window.state = State(folder / 'state')
            window.player.volume = 0
            window.player._mpv.hwdec = 'no'
            window.open_path(video)
            pump(.5)
            window.player.paused = True
            notes, chat = window._notes, window._chat
            window.show_chat()
            window.toggle_agent()
            notes.save()
            check('에이전트만 열 때 미수정 메모 파일 생성 없음', not notes.doc.path.exists())
            for show_notes, show_agent in ((False, False), (True, False), (False, True), (True, True)):
                window.toggle_notes(show_notes)
                if window._chat_open != show_agent:
                    window.toggle_agent()
                pump()
                check(f'표시 상태 메모={show_notes} 에이전트={show_agent}',
                      notes.get_visible() == show_notes and chat.get_visible() == show_agent
                      and window._study.get_visible() == (show_notes or show_agent))
            question = {'role': 'user', 'id': 'q1', 'content': '이 영상의 질문입니다', 'timestamp': 1}
            answer = {'role': 'assistant', 'reply_to': 'q1', 'content': '이 영상의 답변입니다', 'timestamp': 2}
            chat.doc.messages = [question, answer]
            chat.doc.save()
            chat._render()
            chat._sync_buttons()
            chat.set_question('보존할 질문 초안')
            window.toggle_agent()
            window.toggle_agent()
            check('닫기·재열기 대화와 초안 보존', chat.doc.messages == [question, answer]
                  and text(chat._input.get_buffer()) == '보존할 질문 초안')
            saved_note = notes.doc.path.read_text()
            check('닫을 때 대화 시각과 원문 자동 기록', '[00:00:01]' in saved_note
                  and '[00:00:02]' in saved_note and saved_note.count(answer['content']) == 1)
            window.toggle_agent()
            window.toggle_agent()
            check('변경 없이 닫고 다시 열어도 중복 없음', notes.doc.path.read_text() == saved_note)
            check('영상별 대화 재로드', Conversation(video).messages == chat.doc.messages)
            window.toggle_notes(False)
            check('메모 없이 실제 영상 캡처', chat.capture_frame() and not window._notes_open)
            capture = chat._captures[str(video)][0]
            check('실제 PNG 파일·요청 이미지 포함', capture.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                  and capture in chat._request_images())
            pump()
            check('캡처 썸네일 표시', chat._capture_box.get_mapped())
            shot('study-agent-capture')
            for _ in range(3):
                check('추가 실제 프레임 첨부', chat.capture_frame())
            check('5번째 첨부 차단', not chat.capture_frame() and len(chat._captures[str(video)]) == 4)
            window.toggle_notes(True)
            window.set_default_size(960, 560)
            pump(.3)
            print(f'4장 두 패널 요청960x560 실제{window.get_width()}x{window.get_height()}', flush=True)
            check('4장 두 패널 입력·전송 접근', all(inside(w) for w in (notes._view, chat._input, chat.send_button)))
            window.set_default_size(640, 560)
            pump(.3)
            print(f'4장 최소 요청640x560 실제{window.get_width()}x{window.get_height()}', flush=True)
            check('4장 최소 창 입력·전송 접근', all(inside(w) for w in (notes._view, chat._input, chat.send_button)))
            thumbnails = list(chat._captures[str(video)])
            boxes = list(descendants(chat._capture_box))
            images = [w for w in boxes if isinstance(w, (Gtk.Image, Gtk.Picture))]
            check('4장 썸네일 크기 제한', len(images) == 4 and all(inside(w) and 24 <= w.get_height() <= 60 for w in images))
            shot('study-four-captures-narrow')
            for path in thumbnails:
                chat._remove_capture(path)
            window.set_default_size(960, 700)
            pump()
            check('첨부 제거', capture not in chat._request_images() and not chat._capture_box.get_visible())
            # 실제 프레임을 핀에 저장하고 이미지 앞 제목 위치에서 생각을 이어 쓴다.
            window.toggle_notes(True)
            pin_count = len(window.state.pins_for(video))
            scene_pin = window.add_pin()
            pin_images = sorted(video.with_suffix('.assets').glob('pin-*.png'))
            check('핀 실제 PNG와 영상 시각 기록', scene_pin is not None and len(pin_images) == 1
                  and pin_images[0].read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                  and len(window.state.pins_for(video)) == pin_count + 1)
            from bora.notes.model import format_stamp
            cursor = notes._buffer.get_iter_at_mark(notes._buffer.get_insert())
            remaining = notes._buffer.get_text(cursor, notes._buffer.get_end_iter(), True)
            check('핀 제목 뒤 이미지 앞 커서', remaining.startswith('\n\n![장면 ')
                  and format_stamp(scene_pin.start) in notes._text())
            notes._buffer.insert_at_cursor('핀에서 떠오른 아이디어')
            notes.save(force=True)
            pump(.2)
            cursor_rect = notes._view.get_iter_location(notes._buffer.get_iter_at_mark(notes._buffer.get_insert()))
            visible_rect = notes._view.get_visible_rect()
            check('새 핀 제목 커서가 실제 메모 화면에 보임',
                  cursor_rect.y + cursor_rect.height > visible_rect.y
                  and cursor_rect.y < visible_rect.y + visible_rect.height)
            check('핀 아이디어와 장면 함께 저장', '핀에서 떠오른 아이디어' in notes.doc.path.read_text()
                  and 'pin-' in notes.doc.path.read_text())
            shot('study-pin-idea')
            pin_count += 1
            with patch.object(window.player, 'screenshot', side_effect=OSError('모의 캡처 실패')):
                failed_capture_pin = window.add_pin(label='캡처 실패에도 보존할 생각')
            notes.save(force=True)
            check('캡처 실패에도 시각 핀과 메모 보존', failed_capture_pin is not None
                  and len(window.state.pins_for(video)) == pin_count + 1
                  and '캡처 실패에도 보존할 생각' in notes.doc.path.read_text())
            # 첨부 이후 외부 경로를 가리키게 된 경우에도 초안과 대화 기록을 보존한다.
            unsafe = folder.parent / 'outside-study-review.png'
            chat._captures[str(video)] = [unsafe]
            chat.set_question('외부 첨부 차단 시 보존할 질문')
            saved_messages = list(chat.doc.messages)
            with patch.object(api, 'load_config', return_value={'provider': 'codex'}), \
                    patch('bora.ai.panel.ensure_ready', return_value=(True, '모의 준비')):
                check('폴더 밖 첨부 초안·대화 보존', not chat.send()
                      and text(chat._input.get_buffer()) == '외부 첨부 차단 시 보존할 질문'
                      and chat.doc.messages == saved_messages)
            chat._captures.pop(str(video), None)
            chat._render_captures()
            button = Gtk.Button()
            chat._insert_note(button, video, answer)
            note = notes.doc.path.read_text()
            check('질문과 답변 함께 저장', question['content'] in note and answer['content'] in note)
            check('메모 열기에도 에이전트 유지', window._notes_open and window._chat_open)
            original_note = notes._text()
            retry_text = '\n\n저장 재시도 검토 문장\n'
            with patch.object(notes.doc, 'save', side_effect=OSError('모의 저장 실패')):
                check('저장 실패 시 삽입 되돌림', not chat.append_note(retry_text, video)
                      and notes._text() == original_note and notes.doc.path.read_text() == note)
            check('저장 재시도 중복 없음', chat.append_note(retry_text, video)
                  and notes.doc.path.read_text().count(retry_text.strip()) == 1)
            note = notes.doc.path.read_text()
            chat.make_study(summarize=False)
            preview = chat._study_preview
            pump()
            check('원문 미리보기', question['content'] in text(preview.buffer) and answer['content'] in text(preview.buffer))
            check('원문 미리보기는 자동 저장 안 함', notes.doc.path.read_text() == note)
            shot('study-original-preview', preview)
            with patch.object(api, 'load_config', return_value={'provider': 'codex'}), \
                    patch.object(client, 'ensure_ready', return_value=(True, '모의 준비')), \
                    patch.object(client, 'AskRunner', FakeRunner):
                check('요약 창 비모달·메모 기본 포함', not preview.get_modal() and preview.include_notes.get_active())
                preview.include_notes.set_active(False)
                preview.summarize()
                check('요약 메모 포함 해제', '핀에서 떠오른 아이디어' not in runners[-1].question.text)
                preview.stop()
                preview.include_notes.set_active(True)
                preview.summarize()
                check('요약에 메모 스냅샷 포함', '핀에서 떠오른 아이디어' in runners[-1].question.text)
                notes._buffer.insert(notes._buffer.get_end_iter(), '\n요약 중에도 작성하는 생각')
                notes.save(force=True)
                check('요약 중 메모 편집과 스냅샷 분리', '요약 중에도 작성하는 생각' in notes.doc.path.read_text()
                      and '요약 중에도 작성하는 생각' not in runners[-1].question.text)
                check('요약 생성 중 적용 차단', not preview.apply_button.get_sensitive())
                runners[-1].finish()
                pump()
                check('모의 요약 완료·원문 보존', preview.runner is None and preview.apply_button.get_sensitive()
                      and '모의 학습 요약' in text(preview.buffer) and chat.doc.messages == [question, answer])
                shot('study-summary-preview', preview)
                preview.apply()
                pump()
                check('확인한 요약 메모 추가', '모의 학습 요약' in notes.doc.path.read_text())
                chat.make_study(summarize=False)
                preview = chat._study_preview
                preview.summarize()
                runners[-1].callbacks['on_error']('모의 요약 연결 오류')
                pump()
                check('요약 오류 원문 보존·적용 차단', not preview.apply_button.get_sensitive()
                      and chat.doc.messages == [question, answer] and '연결 오류' in preview.status.get_text())
                preview.original()
                check('요약 오류 후 원문 복귀', question['content'] in text(preview.buffer)
                      and answer['content'] in text(preview.buffer))
                preview.summarize()
                cancelled = runners[-1]
                preview.stop()
                cancelled.finish('취소 이후 늦은 응답')
                pump()
                check('요약 중지·늦은 응답 차단', cancelled.cancelled
                      and '늦은 응답' not in text(preview.buffer) and not preview.apply_button.get_sensitive())
                preview.original()
                check('중지 뒤 원문 복귀', question['content'] in text(preview.buffer)
                      and preview.apply_button.get_sensitive())
                preview.summarize()
                stale = runners[-1]
                other = folder / '다른 영상.mp4'
                other.write_bytes(video.read_bytes())
                chat.doc.messages.append({'role': 'user', 'content': '전환 전에 자동 기록', 'timestamp': 3})
                chat._dirty = True
                window.open_path(other)
                pump(.3)
                window.player.paused = True
                stale.finish('이전 영상에서 늦게 온 응답')
                pump()
                check('영상 전환 시 요약 닫기·늦은 응답 차단', preview.closed and stale.cancelled
                      and chat._path == other and chat._study_preview is None
                      and '이전 영상' not in notes._text())
                check('영상 교체는 이전 메모에만 새 대화 기록', '전환 전에 자동 기록' in video.with_suffix('.md').read_text()
                      and '전환 전에 자동 기록' not in notes._text())
            window.open_path(video)
            pump(.3)
            window.player.paused = True
            window.show_chat()
            window.toggle_notes(True)
            window.set_default_size(640, 560)
            pump(.3)
            print(f'좁은 창 요청640x560 실제{window.get_width()}x{window.get_height()}', flush=True)
            check('좁은 창 독립 토글·첨부·메모 생성·입력·전송 접근', all(inside(w) for w in
                  (window._notes_toggle, window._agent_toggle, chat.capture_button,
                   chat.study_button, chat._input, chat.send_button, notes._view)))
            shot('study-narrow-both')
            window.set_default_size(960, 800)
            pump(.2)
            window._on_right_click(None, 1, 50, 50)
            pump(.2)
            labels = [w.get_label() for w in descendants(window._menu_popover) if isinstance(w, Gtk.Label)]
            check('우클릭 메뉴 속도·단축키 안내 표시', '재생 속도 느리게' in labels
                  and '재생 속도 빠르게' in labels and ',' in labels and '.' in labels)
            shot('study-speed-menu', window._menu_popover)
            window._menu_popover.popdown()
            print('우클릭 메뉴는 핸들러 표시 검사. 실제 포인터 입력은 별도 검증.', flush=True)
            if os.environ.get('BORA_TEST_ISOLATED_X11') == '1':
                window.set_focus(None)
                before_speed = window.player.speed
                actual_key('period')
                check('실제 . 키 속도 증가', abs(window.player.speed - before_speed - .25) < .01)
                actual_key('comma')
                check('실제 , 키 속도 감소', abs(window.player.speed - before_speed) < .01)
                chat.focus_editor()
                pump()
                original_draft = text(chat._input.get_buffer())
                actual_key('period')
                check('질문 입력 중 속도 키 보호', window.player.speed == before_speed
                      and text(chat._input.get_buffer()) != original_draft)
                actual_click(window._video)
                check('영상 실제 클릭으로 입력 포커스 해제', window.get_focus() is window._video)
                paused = window.player.paused
                actual_key('space')
                check('영상 클릭 뒤 실제 Space 재생 전환', window.player.paused != paused)
                window.player.paused = True
                actual_key('period')
                speed_toast = window._speed_toast
                for _ in range(3):
                    actual_key('period')
                check('연속 속도 키는 같은 알림에 최신 값 즉시 반영', window._speed_toast is speed_toast
                      and speed_toast.get_title() == f'재생 속도 {window.player.speed:g}x')
                chat.doc.messages.append({'role': 'user', 'content': '닫을 때 저장 실패 검토', 'timestamp': 3})
                chat._dirty = True
                with patch.object(notes.doc, 'save', side_effect=OSError('모의 저장 실패')):
                    actual_click(chat.close_button)
                    check('닫기 저장 실패 시 패널과 대화 보존', window._chat_open
                          and '닫을 때 저장 실패 검토' not in notes._text())
                actual_click(chat.close_button)
                check('실제 닫기 버튼은 자동 기록 후 영상 포커스', not window._chat_open
                      and window.get_focus() is window._video
                      and notes.doc.path.read_text().count('닫을 때 저장 실패 검토') == 1)
                window.show_chat()
                rich = '# 활성함수 비교\n**핵심 개념**과 `ReLU`\n\n| 종류 | 음수 입력 |\n|---|---|\n| ReLU | 0 |\n| Leaky ReLU | 작은 기울기 |\n\n```python\nf = max(0, x)\n```'
                chat.doc.messages.append({'role': 'assistant', 'content': rich, 'timestamp': 3})
                chat._dirty = True
                chat._render()
                pump(.2)
                chat._to_bottom()
                pump(.2)
                shot('study-markdown-response')
                check('표와 강조를 GTK 응답에서 표시', any(isinstance(w, Gtk.Grid) for w in descendants(chat._messages)))
                window.set_default_size(640, 560)
                pump(.3)
                check('마크다운 긴 응답에서도 닫기·입력 접근', all(inside(w) for w in (chat.close_button, chat._input, chat.send_button)))
                window.toggle_notes(False)
                pump(.2)
                chat._to_bottom()
                pump(.2)
                manager = Adw.StyleManager.get_default()
                manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
                pump(.3)
                shot('study-markdown-light-narrow')
                manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
                pump(.3)
                shot('study-markdown-dark-narrow')
                with patch.object(api, 'load_config', return_value={'provider': 'codex'}), \
                        patch.object(client, 'ensure_ready', return_value=(True, '모의 준비')), \
                        patch.object(client, 'AskRunner', FakeRunner):
                    chat.make_study()
                    check('요약 버튼 한 번으로 전체 메모 요약 시작', chat._study_preview.runner is runners[-1]
                          and '핀에서 떠오른 아이디어' in runners[-1].question.text
                          and '활성함수 비교' in runners[-1].question.text)
                    chat._study_preview.close()
                chat.doc.messages.append({'role': 'user', 'content': '플레이어 종료 자동 기록', 'timestamp': 3})
                chat._dirty = True
                closing = window
                window.close()
                pump(.2)
                check('플레이어 종료 전 새 대화 저장', not closing.player.alive
                      and '플레이어 종료 자동 기록' in video.with_suffix('.md').read_text())
                window = None
            else:
                print('미검증: 격리 X11 플래그 없음, 실제 키입력 검사 생략', flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            message = str(exc).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
            print(f'::error::Study agent failed: {message}', flush=True)
            return 1
        finally:
            if window is not None:
                if window._chat._study_preview is not None:
                    window._chat._study_preview.close()
                window._notes._cancel_autosave()
                window._on_close()
                if window.player.alive:
                    window.player.close()
                window.destroy()
                pump(.1)
            if app is not None:
                app.quit()
        print(f'{sum(results)}/{len(results)} 통과 — 실제 GTK·영상 캡처, AI 응답은 모의', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
