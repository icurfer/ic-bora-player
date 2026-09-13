# -*- coding: utf-8 -*-
"""기획서 §8-3 스파이크 — python-mpv 렌더 컨텍스트 + GtkGLArea 가 실제로 도는가.
   PyOpenGL 없이 ctypes 만으로 붙인다(의존성 하나를 줄일 수 있는지도 같이 본다).
   3초 재생 후 자동 종료하고 관찰값을 출력한다."""
import ctypes, sys, time
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk
import mpv

_gl  = ctypes.CDLL('libGL.so.1')
_egl = ctypes.CDLL('libEGL.so.1')
_egl.eglGetProcAddress.restype  = ctypes.c_void_p
_egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6

def current_fbo():
    v = ctypes.c_int()
    _gl.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(v))
    return v.value

def get_proc_address(_ctx, name):
    return _egl.eglGetProcAddress(name)

class Spike(Adw.Application):
    def __init__(self, path):
        super().__init__(application_id='com.icurfer.BoraSpike')
        self.path = path
        self.frames = 0
        self.ctx = None
        self.report = {}

    def do_activate(self):
        print('[spike] activate', flush=True)
        win = Adw.ApplicationWindow(application=self, default_width=960, default_height=540)
        win.set_title('Bora 렌더 스파이크')
        self.area = Gtk.GLArea(hexpand=True, vexpand=True)
        self.area.set_auto_render(False)
        self.area.connect('realize', self.on_realize)
        self.area.connect('render', self.on_render)
        win.set_content(self.area)
        win.present()

    def on_realize(self, area):
        print('[spike] realize', flush=True)
        area.make_current()
        err = area.get_error()
        print('[spike] GLArea error:', err, flush=True)
        self.mpv = mpv.MPV(hwdec='auto-safe', really_quiet=True, vo='libmpv')
        self.ctx = mpv.MpvRenderContext(
            self.mpv, 'opengl',
            opengl_init_params={'get_proc_address': mpv.MpvGlGetProcAddressFn(get_proc_address)})
        self.ctx.update_cb = lambda: GLib.idle_add(self.area.queue_render,
                                                   priority=GLib.PRIORITY_HIGH)
        print('[spike] render ctx ok', flush=True)
        self.mpv.play(self.path)
        GLib.timeout_add_seconds(4, self.finish)

    def on_render(self, area, gl_ctx):
        if not self.ctx:
            return True
        scale = area.get_scale_factor()
        w = area.get_width() * scale
        h = area.get_height() * scale
        self.ctx.render(flip_y=True, opengl_fbo={'w': w, 'h': h, 'fbo': current_fbo()})
        self.frames += 1
        return True

    def finish(self):
        print('[spike] finish', flush=True)
        m = self.mpv
        g = lambda name, default='(없음)': (getattr(m, name, None) or default)
        self.report = {
            'GDK 백엔드': type(self.area.get_native().get_surface()).__name__,
            '렌더 콜백 호출': self.frames,
            'mpv 버전': g('mpv_version'),
            '재생 위치(초)': round(g('time_pos', 0) or 0, 2),
            'hwdec 요청': g('hwdec'),
            'hwdec 실제': g('hwdec_current'),
            '영상 코덱': g('video_codec'),
            '해상도': '%sx%s' % (g('width', '?'), g('height', '?')),
            '드랍 프레임': g('frame_drop_count', 0),
            'vo': g('current_vo'),
        }
        try:
            self.ctx.free()
        except Exception:
            pass
        m.terminate()
        self.quit()
        return False

app = Spike(sys.argv[1])
app.run([])
print('=== §8-3 스파이크 결과 ===')
for k, v in app.report.items():
    print('  %-14s %s' % (k, v))
print('  결론: 렌더 콜백이 0 이면 실패, 수십 회 이상이면 GLArea 경로가 동작한 것')
