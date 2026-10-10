#!/usr/bin/env python3
"""공통 GTK UI의 실제 배치·테마·아이콘 검사. 키입력/IME E2E는 별도다."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    with tempfile.TemporaryDirectory(prefix='bora-shared-ui-') as directory:
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
            print('미검증: GTK 디스플레이 없음', flush=True)
            return 2
        from bora.app import BoraApplication
        from bora.state import State
        results = []
        window = None
        app = None
        manager = Adw.StyleManager.get_default()
        original_scheme = manager.get_color_scheme()

        def check(label, condition):
            results.append(bool(condition))
            print(f"[{'통과' if condition else '실패'}] {label}", flush=True)
            assert condition, label

        def pump(seconds=.15):
            end = time.monotonic() + seconds
            context = GLib.MainContext.default()
            while time.monotonic() < end:
                while context.pending() and time.monotonic() < end:
                    context.iteration(False)
                time.sleep(.005)

        def shot(name):
            destination = os.environ.get('BORA_REVIEW_SHOTS')
            if not destination:
                return
            paintable = Gtk.WidgetPaintable.new(window)
            try:
                node = None
                for _ in range(12):
                    window.queue_draw()
                    pump(.08)
                    snapshot = Gtk.Snapshot.new()
                    paintable.snapshot(snapshot, window.get_width(), window.get_height())
                    node = snapshot.to_node()
                    if node is not None:
                        break
                assert node is not None, '화면 캡처 노드 없음'
                target = Path(destination)
                target.mkdir(parents=True, exist_ok=True)
                path = target / f'{name}.png'
                assert window.get_renderer().render_texture(node, None).save_to_png(str(path))
                print(f'캡처: {path}', flush=True)
            finally:
                paintable.set_widget(None)

        def text(buffer):
            return buffer.get_text(*buffer.get_bounds(), True)

        def preservation():
            buffer = window._notes._buffer
            return (text(buffer), buffer.get_property('cursor-position'),
                    tuple(i.get_offset() for i in buffer.get_selection_bounds()),
                    window._notes.doc.dirty, text(window._chat._input.get_buffer()))

        def inside(widget, ancestor):
            ok, bounds = widget.compute_bounds(ancestor)
            return (ok and widget.get_mapped() and bounds.get_width() > 0 and bounds.get_height() > 0
                    and bounds.get_x() >= -1 and bounds.get_y() >= -1
                    and bounds.get_x() + bounds.get_width() <= ancestor.get_width() + 1
                    and bounds.get_y() + bounds.get_height() <= ancestor.get_height() + 1)

        def luminance(color):
            channels = (color.red, color.green, color.blue)
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))

        def layout(label):
            notes, chat = window._notes, window._chat
            print(f'{label}: 실제 {window.get_width()}x{window.get_height()}, '
                  f'메모 폭 {notes.get_width()}, 대화 폭 {chat.get_width()}', flush=True)
            check(f'{label} 메모·대화 입력과 전송 표시', all(inside(w, window) for w in
                  (notes._view, chat._input, chat.send_button, window._settings_button)))
            toolbar = notes.get_first_child()
            child = toolbar.get_first_child()
            while child is not None:
                if isinstance(child, (Gtk.Button, Gtk.MenuButton)):
                    check(f'{label} 메모 도구 {child.get_tooltip_text() or child.get_name()}', inside(child, window))
                child = child.get_next_sibling()
            a, note_bounds = notes.compute_bounds(window)
            b, chat_bounds = chat.compute_bounds(window)
            check(f'{label} 메모 위·대화 아래', a and b and
                  note_bounds.get_y() + note_bounds.get_height() <= chat_bounds.get_y() + 1)

        try:
            video = folder / '공통 화면 샘플.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=3', '-c:v', 'libx264',
                            '-preset', 'ultrafast', str(video)], check=True, timeout=30)
            video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:02,900\n공통 UI 검토용 자막\n', encoding='utf-8')
            app = BoraApplication(non_unique=True)
            app.register(None)
            app.activate()
            window = app.props.active_window
            # 기본 State도 XDG로 격리되며, 명시적으로 별도 테스트 State를 사용한다.
            window.state = State(folder / 'state')
            window.player.volume = 0
            # Xvfb는 실기 하드웨어 디코딩 검증 환경이 아니다.
            window.player._mpv.hwdec = 'no'
            window.open_path(video)
            pump(.5)
            window.player.paused = True
            window.toggle_notes(True)
            notes, chat = window._notes, window._chat
            notes._buffer.set_text('# 공통 화면 검토\n한국어 메모와 영상 학습\n[00:00:01] 참고 구간\n'
                                   '> 인용문 가독성 확인\n`코드 조각`과 **강조**\n- 목록 표시')
            notes._buffer.select_range(notes._buffer.get_iter_at_offset(12), notes._buffer.get_iter_at_offset(8))
            notes._retag()
            notes._cancel_autosave()
            chat.set_question('전송하지 않은 한국어 질문 초안')
            before = preservation()
            colors = []
            for name, scheme in [('light', Adw.ColorScheme.FORCE_LIGHT), ('dark', Adw.ColorScheme.FORCE_DARK)]:
                manager.set_color_scheme(scheme)
                pump(.3)
                check(f'{name} 시스템 테마 전환', manager.get_dark() == (name == 'dark'))
                check(f'{name} 메모·커서·선택·초안 보존', preservation() == before)
                tag = notes._buffer.get_tag_table().lookup(notes.STAMP_TAG)
                colors.append(tag.get_property('foreground-rgba').to_string())
                found, background = notes._view.get_style_context().lookup_color('view_bg_color')
                check(f'{name} 메모 배경 역할 색상 존재', found)
                for tag_name in (notes.STAMP_TAG, 'quote'):
                    foreground = notes._buffer.get_tag_table().lookup(tag_name).get_property('foreground-rgba')
                    values = sorted((luminance(foreground), luminance(background)))
                    ratio = (values[1] + .05) / (values[0] + .05)
                    print(f'{name} {tag_name} 대비 {ratio:.2f}:1', flush=True)
                    check(f'{name} {tag_name} 글자 대비', ratio >= 4.5)
                window.set_default_size(960, 700)
                pump(.3)
                layout(f'{name} 요청 960x700')
                shot(f'shared-{name}-960')
            check('테마별 메모 링크 색상 갱신', colors[0] != colors[1])
            window._blackout.set_visible(True)
            pump(.2)
            shot('shared-dark-korean-overlay')
            window._blackout.set_visible(False)
            window.set_default_size(640, 560)
            pump(.3)
            layout('최소 요청 640x560')
            print('요청 크기와 실제 GTK 콘텐츠 크기를 구분하며 동일 크기로 주장하지 않음', flush=True)
            shot('shared-dark-minimum')
            icons = set()
            for path in (ROOT / 'src/bora').rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('-symbolic'):
                        icons.add(node.value)
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            missing = sorted(icon for icon in icons if not theme.has_icon(icon))
            print(f'필수 symbolic 아이콘 {len(icons)}개, 누락: {missing}', flush=True)
            check('실제 소스의 필수 아이콘 존재', bool(icons) and not missing)
            from bora.ui import update_note_colors
            tags = notes._buffer.get_tag_table()
            update_note_colors(notes._view, notes._buffer, SimpleNamespace(
                get_dark=lambda: manager.get_dark(), get_high_contrast=lambda: True))
            stamp = tags.lookup(notes.STAMP_TAG)
            check('모의 고대비 정책 본문색·밑줄 유지',
                  stamp.get_property('foreground-rgba').equal(tags.lookup('quote').get_property('foreground-rgba'))
                  and int(stamp.get_property('underline')) != 0)
            check('모의 고대비 코드 배경 강화', tags.lookup('code').get_property('background-rgba').alpha > .1)
            check('모의 고대비 메모·초안 보존', preservation() == before)
            notes._update_colors()
            print('고대비는 함수 정책 검사이며 실제 OS 고대비 화면은 미검증', flush=True)
            for cycle in range(2):
                theme_manager = notes._theme_manager
                previous_handlers = list(notes._theme_signals)
                window._study.set_start_child(None)
                pump()
                check(f'분리 {cycle + 1} 테마 신호 정리', not notes._theme_signals
                      and notes._theme_manager is None
                      and all(not theme_manager.handler_is_connected(h) for h in previous_handlers))
                window._study.set_start_child(notes)
                pump()
                check(f'재부착 {cycle + 1} 신호 연결', len(notes._theme_signals) == 2
                      and all(notes._theme_manager.handler_is_connected(h) for h in notes._theme_signals))
                after = preservation()
                # GtkTextView의 완전 분리는 선택 소유권을 해제할 수 있다.
                # 테마 전환 자체의 선택 보존은 위에서 별도로 검사한다.
                check(f'재부착 {cycle + 1} 텍스트·커서·dirty·초안 보존',
                      (after[0], after[1], after[3], after[4]) == (before[0], before[1], before[3], before[4]))
                print(f'재부착 {cycle + 1} 선택 영역: {after[2]} (테마 전환과 구분)', flush=True)
            manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            pump(.2)
            check('재부착 후 테마 갱신', tags.lookup(notes.STAMP_TAG).get_property('foreground-rgba').to_string() == colors[0])
        except Exception as exc:
            import traceback
            traceback.print_exc()
            message = str(exc).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
            print(f'::error::Shared UI check failed: {message}', flush=True)
            return 1
        finally:
            manager.set_color_scheme(original_scheme)
            if window is not None:
                window._notes._cancel_autosave()
                window._notes.cancel_ask()
                window._on_close()
                if window.player.alive:
                    window.player.close()
                window.destroy()
                pump(.1)
            if app is not None:
                app.quit()
        print(f'{sum(results)}/{len(results)} 통과 — GTK 화면 검사, 실제 키입력·IME는 별도', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
