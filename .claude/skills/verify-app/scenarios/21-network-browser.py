#!/usr/bin/env python3
"""실제 GTK 키입력과 좁은 창·재생 전달. 원격 서버 응답은 모의다."""
import ctypes,os,subprocess,sys,tempfile,time
import faulthandler
faulthandler.dump_traceback_later(15, repeat=False)
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'src'))
assert os.environ.get('BORA_TEST_ISOLATED_X11')=='1'
with tempfile.TemporaryDirectory(prefix='bora-network-ui-') as directory:
    root=Path(directory)
    for name in ('CONFIG','CACHE','DATA'):os.environ[f'XDG_{name}_HOME']=str(root/name)
    os.environ['GSETTINGS_BACKEND']='memory'
    os.environ['ADW_DISABLE_PORTAL']='1'
    os.environ['GTK_USE_PORTAL']='0'
    os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path='+str(root/'no-session-bus')
    import gi
    gi.require_version('Adw','1');gi.require_version('Gtk','4.0');gi.require_version('GdkX11','4.0')
    from gi.repository import Adw,GdkX11,Gio,GLib
    from PIL import ImageGrab
    from bora.network import ServerStore
    from bora.network_window import NetworkWindow
    from bora.window import BoraWindow
    Adw.init();app=Adw.Application(application_id='com.icurfer.Bora.NetworkTest',flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None);owner=BoraWindow(app);owner.present()
    video=root/'한글 영상.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'color=c=blue:s=320x180:d=3','-c:v','mpeg4','-y',str(video)],check=True)
    x=ctypes.CDLL('libX11.so.6');xt=ctypes.CDLL('libXtst.so.6')
    x.XOpenDisplay.restype=ctypes.c_void_p
    x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
    x.XStringToKeysym.argtypes=[ctypes.c_char_p];x.XStringToKeysym.restype=ctypes.c_ulong
    x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_uint
    x.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
    xt.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
    display=x.XOpenDisplay(None);assert display
    def pump(seconds=.2):
        end=time.monotonic()+seconds;context=GLib.MainContext.default()
        while time.monotonic()<end:context.iteration(False);time.sleep(.005)
    def press(widget):
        widget.grab_focus();x.XSetInputFocus(display,GdkX11.X11Surface.get_xid(window.get_surface()),2,0)
        code=x.XKeysymToKeycode(display,x.XStringToKeysym(b'Return'))
        assert xt.XTestFakeKeyEvent(display,code,1,0);assert xt.XTestFakeKeyEvent(display,code,0,0)
        x.XSync(display,False);pump()
    class Backend:
        def __init__(self):self.calls=[]
        def browse(self,uri,done):self.calls.append((uri,done))
        def stop(self):pass
    def play(path):owner.open_path(path);return owner.current_path==path
    window=NetworkWindow(owner,play,backend=Backend(),store=ServerStore(root/'config'))
    window.present();pump(.3)
    for scheme in ('smb','sftp','nfs'):
        window.address.set_text(f'{scheme}://example.test/share')
        press(window.connect_button);assert window.busy and window.browser.calls[-1][0].startswith(scheme+':')
        press(window.cancel_button);assert not window.busy
    press(window.connect_button)
    window.browser.calls[-1][1]((Gio.File.new_for_path(str(root)),[(video.name,video.name,False)]),'');pump()
    shots=Path(os.environ.get('BORA_REVIEW_SHOTS','/data/github-icurfer/.bora-worktrees/network-shots'))
    shots.mkdir(parents=True,exist_ok=True)
    for width,height,name in ((640,620,'normal'),(480,580,'narrow')):
        window.set_default_size(width,height);pump()
        assert window.files.get_allocated_height()>0
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(shots/f'{name}.png')
    press(window.files.get_first_child().get_child());pump(.8)
    assert owner.current_path==video and owner.player.duration>0 and window.closed
    owner.player.close();owner.destroy();x.XCloseDisplay(display)
    print('network GUI: three protocol entries, real Return connect/cancel/open, two layouts and libmpv playback passed; server responses mocked')
