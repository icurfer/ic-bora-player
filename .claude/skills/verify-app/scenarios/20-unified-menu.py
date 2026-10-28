#!/usr/bin/env python3
"""공통 메뉴의 실제 클릭·키·전체화면 및 위치 유지 검사. 사용자 설정은 격리한다."""
import os
import shutil
import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
if os.environ.get('BORA_VERIFY_INSTALLED') != '1':
    sys.path.insert(0, os.environ.get('BORA_VERIFY_SOURCE', str(ROOT / 'src')))


def main():
    with tempfile.TemporaryDirectory(prefix='bora-unified-menu-') as directory:
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
        from bora.state import State
        results = []
        window = app = wm = None

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

        def actual_click(widget, button=1, fraction=(.5, .5)):
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
                native = widget.get_native()
                xid = GdkX11.X11Surface.get_xid(native.get_surface())
                left, top, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
                assert x.XTranslateCoordinates(display, xid, x.XDefaultRootWindow(display), 0, 0,
                                              ctypes.byref(left), ctypes.byref(top), ctypes.byref(child))
                ok, bounds = widget.compute_bounds(native)
                assert ok and widget.get_mapped()
                offset_x, offset_y = native.get_surface_transform()
                assert xt.XTestFakeMotionEvent(display, -1, left.value + int(bounds.get_x() - offset_x + bounds.get_width() * fraction[0]),
                                              top.value + int(bounds.get_y() - offset_y + bounds.get_height() * fraction[1]), 0)
                assert xt.XTestFakeButtonEvent(display, button, 1, 0)
                assert xt.XTestFakeButtonEvent(display, button, 0, 0)
                x.XSync(display, False)
            finally:
                x.XCloseDisplay(display)
            pump(.2)

        def labels(root):
            return [w.get_text() for w in descendants(root) if isinstance(w, Gtk.Label)]

        def choose(label):
            root = window._active_menu
            for widget in descendants(root.get_child().get_visible_child()):
                if isinstance(widget, Gtk.Button) and label in labels(widget):
                    ancestor = widget.get_parent()
                    while ancestor is not None and not isinstance(ancestor, Gtk.ScrolledWindow):
                        ancestor = ancestor.get_parent()
                    if ancestor is not None:
                        for _ in range(40):
                            ok, bounds = widget.compute_bounds(ancestor)
                            assert ok
                            if bounds.get_y() >= 0 and bounds.get_y() + bounds.get_height() <= ancestor.get_height():
                                break
                            actual_click(ancestor, button=4 if bounds.get_y() < 0 else 5, fraction=(.85,.5))
                        else:
                            raise AssertionError('휠로 메뉴 항목에 접근 불가: ' + label)
                    actual_click(widget)
                    return
            raise AssertionError('메뉴 항목 없음: ' + label)

        def geometry(root):
            from gi.repository import GdkX11
            surface = root.get_surface()
            # X11 팝업의 실제 루트 좌표와 크기. 위젯 위치만 비교하지 않는다.
            x = ctypes.CDLL('libX11.so.6')
            x.XOpenDisplay.restype = ctypes.c_void_p
            x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x.XDefaultRootWindow.restype = ctypes.c_ulong
            x.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong)]
            x.XCloseDisplay.argtypes = [ctypes.c_void_p]
            connection = x.XOpenDisplay(None)
            try:
                left, top, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
                assert x.XTranslateCoordinates(connection, GdkX11.X11Surface.get_xid(surface), x.XDefaultRootWindow(connection), 0, 0, ctypes.byref(left), ctypes.byref(top), ctypes.byref(child))
                return left.value, top.value, surface.get_width(), surface.get_height()
            finally:
                x.XCloseDisplay(connection)

        try:
            assert os.environ.get('BORA_TEST_ISOLATED_X11') == '1', '격리 X11 명시 필요'
            executable = os.environ.get('BORA_TEST_WINDOW_MANAGER') or shutil.which('openbox')
            assert executable, '실제 전체화면 검사를 위한 격리 openbox 필요'
            command = [executable, '--sm-disable']
            if os.environ.get('BORA_OPENBOX_CONFIG'):
                command += ['--config-file', os.environ['BORA_OPENBOX_CONFIG']]
            wm = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pump(.5)
            assert wm.poll() is None, '격리 창 관리자 초기화 실패'
            video = folder / 'menu-sample.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=10:duration=12', '-c:v', 'libx264', '-preset', 'ultrafast', str(video)], check=True, timeout=30)
            video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:11,900\n메뉴 검토 자막\n')
            app = BoraApplication(non_unique=True)
            app.register(None)
            app.activate()
            window = app.props.active_window
            window.state = State(folder / 'state')
            window.player.volume = 0
            pump(.3)
            actual_click(window._menu_button)
            empty_main = labels(window._main_popover.get_child())
            window._main_popover.popdown()
            pump(.4)
            actual_click(window._video, button=3)
            empty_context = labels(window._menu_popover.get_child())
            if os.environ.get('BORA_MENU_DIAGNOSE') == '1':
                print('빈 창 메뉴 기능 불일치:', sorted(set(empty_main) ^ set(empty_context)), flush=True)
            else:
                check('빈 창 두 진입점의 동일 메뉴', empty_main == empty_context)
                check('빈 창 파일 열기가 첫 항목', empty_main[0] == '파일 열기')
            window._menu_popover.popdown()
            window.open_path(video)
            pump(.6)
            window.player.paused = True
            actual_click(window._menu_button)
            main = labels(window._main_popover.get_child())
            window._main_popover.popdown()
            pump(.4)
            actual_click(window._video, button=3)
            context = labels(window._menu_popover.get_child())
            if os.environ.get('BORA_MENU_DIAGNOSE') == '1':
                print('영상 메뉴 기능 불일치:', sorted(set(main) ^ set(context)), flush=True)
                window._menu_popover.popdown()
                window.fullscreen()
                pump(.8)
                assert window.is_fullscreen(), '실제 전체화면 전환 실패'
                actual_click(window._menu_button)
                pump(4.2)
                print('전체화면 열린 하단 메뉴:', window._main_popover.get_visible(), '하단바:', window._controls_revealer.get_reveal_child(), flush=True)
                return 1
            if main != context:
                print('차이', [(i,a,b) for i,(a,b) in enumerate(zip(main,context)) if a!=b],len(main),len(context),flush=True)
            check('영상 두 진입점의 동일 기능과 상태', main == context)
            check('기존 양쪽 기능 모두 보존', all(text in context for text in ('재생 속도 느리게', '오디오 트랙', '학습 에이전트', '로그', '이 구간 클립으로 담기')))
            shot('unified-context', window._menu_popover)
            scroller = window._menu_popover.get_child().get_visible_child()
            start_scroll = scroller.get_vadjustment().get_value()
            actual_click(scroller, button=5, fraction=(.8,.7))
            check('실제 휠로 긴 메뉴 스크롤', scroller.get_vadjustment().get_value() > start_scroll)

            for entry in ('context', 'bottom'):
                window._close_menus()
                pump(.2)
                if entry == 'context':
                    actual_click(window._video, button=3, fraction=(.15,.25))
                else:
                    actual_click(window._menu_button)
                root = window._active_menu
                pump(.3)
                for title in ('자막', '오디오 트랙', '화면·속도·자막 모양', '핀 목록', '로그', '음성에서 자막 만들기'):
                    before = geometry(root)
                    choose(title)
                    pump(.2)
                    after = geometry(root)
                    print(entry, title, '이동 전후', before, after, flush=True)
                    check(entry + ' 하위 메뉴 동일 팝오버: ' + title, window._active_menu is root and root.get_visible() and root.get_child().get_visible_child_name() == 'page')
                    check(entry + ' 페이지 위치·크기 유지: ' + title, before == after)
                    choose('‹ 전체 메뉴')
                    check(entry + ' 전체 메뉴 복귀: ' + title, root.get_child().get_visible_child_name() == 'main')
                choose('자막')
                actual_key('Escape')
                check(entry + ' Escape는 하위 페이지에서 복귀', root.get_visible() and root.get_child().get_visible_child_name() == 'main')
                actual_key('Escape')
                check(entry + ' 전체 메뉴 Escape 닫기', not root.get_visible())
            window.set_default_size(640,560)
            pump(.4)
            print('작은 창 실제 크기',window.get_width(),window.get_height(),flush=True)
            for fraction in ((.05,.05),(.95,.05),(.05,.95),(.95,.95)):
                actual_click(window._video, button=3, fraction=fraction)
                root=window._menu_popover
                g=geometry(root)
                print('edge',fraction,root.get_visible(),g,flush=True)
                check('가장자리에서 메뉴 표시 ' + str(fraction), root.get_visible() and g[0]>=0 and g[1]>=0 and g[0]+g[2]<=Gdk.Display.get_default().get_monitors().get_item(0).get_geometry().width and g[1]+g[3]<=Gdk.Display.get_default().get_monitors().get_item(0).get_geometry().height)
                choose('자막')
                check('가장자리 하위 메뉴 유지 ' + str(fraction), root.get_visible())
                window._close_menus()
                pump(.2)
            window.fullscreen()
            pump(.8)
            check('실제 창 관리자 전체화면 전환', window.is_fullscreen())
            for entry in ('bottom','context'):
                window._reveal_ui()
                pump(.2)
                actual_click(window._menu_button if entry=='bottom' else window._video, button=1 if entry=='bottom' else 3)
                root=window._active_menu
                pump(4.2)
                check('전체화면 자동 숨김 보호 ' + entry, root.get_visible() and window._controls_revealer.get_reveal_child())
                choose('자막')
                pump(4.2)
                check('전체화면 하위 페이지 숨김 보호 ' + entry, root.get_visible() and window._controls_revealer.get_reveal_child())
                choose('‹ 전체 메뉴')
                window._close_menus()
                pump(4.2)
                check('닫은 뒤 전체화면 자동 숨김 복귀 ' + entry, not window._controls_revealer.get_reveal_child())
            window.unfullscreen()
            window.set_default_size(960,700)
            pump(.5)
            actual_click(window._menu_button)
            speed=window.player.speed
            choose('재생 속도 빠르게')
            check('직접 동작 한 번 실행 후 메뉴 닫기', window.player.speed==speed+.25 and not window._main_popover.get_visible())
            actual_click(window._video,button=3)
            choose('학습 메모')
            check('통합 메뉴 메모 열기와 원본 보호', window._notes_open and window._notes.doc.path==video.with_suffix('.md'))
            shot('unified-player')
        except Exception as exc:
            import traceback
            traceback.print_exc()
            message = str(exc).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
            print(f'::error::Unified menu failed: {message}', flush=True)
            return 1
        finally:
            if window is not None:
                window._notes._cancel_autosave()
                window._on_close()
                window.destroy()
                pump(.1)
            if app is not None:
                app.quit()
            if wm is not None:
                wm.terminate()
                wm.wait(timeout=5)
        print(f'{sum(results)}/{len(results)} 통과 — 격리 실제 GTK·XTest 메뉴',flush=True)
        return 0


if __name__=='__main__':
    raise SystemExit(main())
