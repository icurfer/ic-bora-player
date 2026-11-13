#!/usr/bin/env python3
"""실제 GTK 키입력과 좁은 창·재생 전달. 원격 서버 응답은 모의다."""
import ctypes,os,subprocess,sys,tempfile,time
import faulthandler
faulthandler.dump_traceback_later(120, repeat=False)
from pathlib import Path
if os.environ.get('BORA_VERIFY_INSTALLED')!='1':
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
    from gi.repository import Adw,GdkX11,Gio,GLib,Gtk
    from PIL import ImageGrab
    from bora.network import ServerStore
    from bora.network_window import NetworkWindow
    from bora.window import BoraWindow
    Adw.init();app=Adw.Application(application_id='com.icurfer.Bora.NetworkTest',flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None);owner=BoraWindow(app);owner.present()
    video=root/'한글 영상.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                    'color=c=blue:s=320x180:d=3','-c:v','mpeg4','-y',str(video)],check=True)
    import shutil
    second=root/'다음 영상.mp4';shutil.copyfile(video,second)
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
    def press(widget,key='Return',delay=.2):
        assert widget.grab_focus()
        pump(.02)
        x.XSetInputFocus(display,GdkX11.X11Surface.get_xid(widget.get_root().get_surface()),2,0)
        code=x.XKeysymToKeycode(display,x.XStringToKeysym(key.encode()))
        assert xt.XTestFakeKeyEvent(display,code,1,0);assert xt.XTestFakeKeyEvent(display,code,0,0)
        x.XSync(display,False);pump(delay)
    def until(condition,seconds=3):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if condition():return True
            pump(.01)
        return bool(condition())
    class Backend:
        def __init__(self):self.calls=[]
        def browse(self,uri,done):self.calls.append((uri,done))
        def stop(self):pass
        def read_only(self,file):return True
        def display_location(self,file):return 'nfs://example.test/share'
        def can_go_up(self,file):return False
    def play(path):owner.open_path(path);return owner.current_path==path
    from bora.platform.linux.network import Session
    session=Session()
    window=NetworkWindow(owner,play,backend=Backend(),store=ServerStore(root/'config'),session=session)
    window.present();pump(.3)
    for scheme in ('smb','sftp','ftp','nfs'):
        window.address.set_text(f'{scheme}://example.test/share')
        press(window.connect_button);assert window.busy and window.browser.calls[-1][0].startswith(scheme+':')
        if scheme=='nfs':assert '관리자 인증' in window.status.get_text()
        press(window.cancel_button);assert not window.busy
    press(window.connect_button)
    window.browser.calls[-1][1]((Gio.File.new_for_path(str(root)),[(video.name,video.name,False)]),'');pump()
    assert '읽기 전용 NFS' in window.storage_notice.get_text() and not window.up.get_sensitive()
    assert window.location.get_text()=='nfs://example.test/share'
    shots=Path(os.environ.get('BORA_REVIEW_SHOTS','/data/github-icurfer/.bora-worktrees/network-shots'))
    shots.mkdir(parents=True,exist_ok=True)
    for width,height,name in ((640,620,'normal'),(480,580,'narrow')):
        window.set_default_size(width,height);pump()
        assert window.files.get_allocated_height()>0
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(shots/f'{name}.png')
    press(window.files.get_first_child().get_child());pump(.8)
    assert owner.current_path==video and owner.player.duration>0 and window.closed
    again=NetworkWindow(owner,play,backend=Backend(),store=ServerStore(root/'config'),session=session)
    again.present();pump(.2)
    assert again.browser.calls, (again.closed, session.last_location is not None)
    assert again.browser.calls[-1][0]==root.as_uri()
    assert again.address.get_text()=='nfs://example.test/share'
    again.browser.calls[-1][1]((Gio.File.new_for_path(str(root)),[(second.name,second.name,False)]),'')
    press(again.files.get_first_child().get_child());pump(.4)
    assert owner.current_path==second and again.closed
    owner.toggle_notes(True)
    panel=owner._notes
    note=panel.doc.path
    before=panel._text()
    press(panel._view,'a',.1);pump(.5)
    started=time.monotonic()
    press(panel._view,'b',.1);pump(.5)
    assert panel._text()==before+'ab' and (not note.exists() or note.read_text()!=panel._text()+'\n')
    assert until(lambda:note.exists() and note.read_text()==panel._text()+'\n',.8)
    elapsed=time.monotonic()-started
    assert .9<=elapsed<1.5 and not panel.doc.dirty
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(shots/'autosave-saved.png')
    print(f'actual-key autosave after last input: {elapsed:.3f}s',flush=True)
    # 실제 파일 버튼으로 전환하고 메모 입력도 XTest를 사용한다.
    # 서버 목록 응답은 모의이며 매번 다른 임시 영상/메모를 쓴다.
    expected={}
    for index in range(100):
        target=root/f'lecture-{index:03}.mp4'
        os.link(video,target)
        owner.player.speed=2.0
        picker=NetworkWindow(owner,play,backend=Backend(),store=ServerStore(root/'config'),session=session)
        picker.present();pump(.02)
        if not picker.browser.calls:
            press(picker.connect_button,delay=.02)
        picker.browser.calls[-1][1]((Gio.File.new_for_path(str(root)),[(target.name,target.name,False)]),'')
        press(picker.files.get_first_child().get_child(),delay=.03)
        assert until(lambda:owner.current_path==target and (owner.player.duration or 0)>0)
        assert picker.closed and owner.player.speed==1.0 and owner._chat._path==target
        assert panel.doc.path==target.with_suffix('.md')
        press(panel._view,'x',.02)
        assert panel._text().endswith('x'), (index,repr(panel._text()),owner.get_focus())
        expected[panel.doc.path]=panel._text()+'\n'
        picker.destroy()
        if index%20==19:print(f'actual-key file switch and memo: {index+1}/100',flush=True)
    assert until(lambda:not panel.doc.dirty and panel._save_id==0)
    assert all(path.read_text()==body for path,body in expected.items())
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(shots/'switch-100.png')
    print('100 actual-key file selections/edits: speed, note/chat context and saved bodies passed',flush=True)
    from types import SimpleNamespace
    released=[]
    def unmount(flags,operation,cancel,callback):
        released.append(flags)
        def finished():
            callback(mount,None)
            return False
        GLib.idle_add(finished)
    mount=SimpleNamespace(get_root=lambda:Gio.File.new_for_path(str(root)),
                          unmount_with_operation=unmount,
                          unmount_with_operation_finish=lambda result:True)
    owner._network_session=Session();owner._network_session.take(mount)
    owner._notes._buffer.insert(owner._notes._buffer.get_end_iter(),'복구해야 할 미저장 본문')
    expected=owner._notes._text()
    import errno
    def denied():raise OSError(errno.EROFS,'read-only fixture')
    owner._notes.doc.save=denied
    owner.close();pump(.25)
    dialog=owner._notes._save_failure_dialog
    assert dialog.get_visible() and owner.player.alive
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(shots/'save-failure.png')
    press(dialog._response_buttons[Gtk.ResponseType.CANCEL])
    assert owner._notes._text()==expected and owner.player.alive and not released
    owner.close();pump(.15)
    # 설정 파일까지 가득 찼더라도 명시적으로 보관한 뒤 자원 정리·종료할 수 있다.
    def full():raise OSError(errno.ENOSPC,'settings fixture')
    owner.state.save=full
    press(owner._notes._save_failure_dialog._response_buttons[Gtk.ResponseType.APPLY]);pump(.25)
    recovered=list((root/'DATA'/'bora'/'recovered-notes').glob('*.md'))
    assert len(recovered)==1 and recovered[0].read_text()==expected
    assert released==[Gio.MountUnmountFlags.NONE] and owner._network_session.callback is None
    owner.destroy();x.XCloseDisplay(display)
    control=Path('/sys/fs/cgroup'+Path('/proc/self/cgroup').read_text().strip().split('::')[1])
    print('test memory peak:',(control/'memory.peak').read_text().strip(),flush=True)
    assert 'oom_kill 0' in (control/'memory.events').read_text()
    print('network GUI: connect/cancel, reopen folder and second video, read-only save failure cancel/recover, settings failure shutdown cleanup passed; network responses mocked')
