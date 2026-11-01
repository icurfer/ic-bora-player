"""URI·즐겨찾기·취소 및 실제 GIO 목록 경계 검사. 원격 서버 응답은 모의다."""
import time
from types import SimpleNamespace
import gi
import pytest
gi.require_version('Gtk','4.0')
from gi.repository import Gio,GLib,Gtk
from bora.network import Server,ServerStore,server_uri
from bora.network_window import NetworkWindow


@pytest.mark.parametrize('uri',['smb://nas/강의 폴더','sftp://u@nas:2222/강의','nfs://nas/export/강의','ftp://user@nas:2121/강의','sftp://[::1]:2222/'])
def test_uri_roundtrip(uri):
    canonical=server_uri(uri)
    assert server_uri(canonical)==canonical and ' ' not in canonical


@pytest.mark.parametrize('uri',['http://host/a','sftp://','sftp://u:secret@host/',
    'smb://host/a?password=x','sftp://host/a#x','sftp://host:99999/a','sftp://host:abc/a',
    'sftp://host/a\n','sftp://u%3Asecret@host/','smb://host/a%00b','nfs://u@host/export',
    'nfs://bad host/a'])
def test_unsafe_uri_rejected(uri):
    with pytest.raises(ValueError) as exc:server_uri(uri)
    assert 'secret' not in str(exc.value)


def test_store_preserves_original_on_invalid_or_corrupt_data(tmp_path):
    store=ServerStore(tmp_path)
    store.save([Server('NAS','nfs://host/export')])
    assert store.load()==[Server('NAS','nfs://host/export')]
    assert store.path.stat().st_mode&0o077==0
    original=store.path.read_bytes()
    with pytest.raises(ValueError):store.save([Server('bad','sftp://u:secret@host/')])
    assert store.path.read_bytes()==original
    store.path.write_text('{broken')
    with pytest.raises(ValueError):store.load()
    assert store.path.read_text()=='{broken'


def test_mapped_path_fallback(tmp_path):
    from bora.platform.linux.network import local_path
    root=SimpleNamespace(get_path=lambda:str(tmp_path),get_relative_path=lambda _: '강의/영상.mp4')
    file=SimpleNamespace(get_path=lambda:None,find_enclosing_mount=lambda _:SimpleNamespace(get_default_location=lambda:root))
    assert local_path(file)==tmp_path/'강의/영상.mp4'


def test_real_gio_enumeration(tmp_path):
    from bora.platform.linux.network import Browser
    (tmp_path/'영상.mp4').touch();(tmp_path/'강의').mkdir()
    browser=Browser(None);result=[]
    browser._list(Gio.File.new_for_path(str(tmp_path)),browser.generation,browser.cancel,
                  lambda value,error:result.append((value,error)))
    context=GLib.MainContext.default();end=time.monotonic()+3
    while not result and time.monotonic()<end:
        context.iteration(False);time.sleep(.005)
    assert result and result[0][1]==''
    assert result[0][0][1]==[('강의','강의',True),('영상.mp4','영상.mp4',False)]
    browser.stop()


class Backend:
    def __init__(self):self.calls=[];self.stops=0
    def browse(self,uri,done):self.calls.append((uri,done))
    def stop(self):self.stops+=1


@pytest.fixture
def window(tmp_path):
    Gtk.init();parent=Gtk.Window();opened=[]
    w=NetworkWindow(parent,lambda path:opened.append(path),backend=Backend(),store=ServerStore(tmp_path))
    w.opened=opened
    yield w
    w.close();w.destroy();parent.destroy()


@pytest.mark.parametrize('scheme',['smb','sftp','ftp','nfs'])
def test_cancel_ignores_late_result(window,scheme):
    w=window;w.address.set_text(f'{scheme}://host/share');w.connect_button.emit('clicked')
    assert w.busy
    callback=w.browser.calls[-1][1];w.cancel_button.emit('clicked')
    callback((Gio.File.new_for_uri(f'{scheme}://host/share'),[('late','late',False)]),'')
    assert w.current is None and w.files.get_first_child() is None and not w.busy


def test_retry_navigation_and_playback_dispatch(window,tmp_path,monkeypatch):
    w=window;w.address.set_text('smb://host/share');w.connect_server()
    w.browser.calls[-1][1](None,'권한 확인');assert '권한' in w.status.get_text()
    w.connect_server();root=Gio.File.new_for_uri('smb://host/share')
    w.browser.calls[-1][1]((root,[('강의','강의',True),('영상.mp4','영상.mp4',False)]),'')
    w.files.get_first_child().get_child().emit('clicked')
    assert '%EA%B0%95%EC%9D%98' in w.browser.calls[-1][0]
    w.cancel();monkeypatch.setattr('bora.network_window.network.local_path',lambda _:tmp_path/'영상.mp4')
    w.files.get_first_child().get_next_sibling().get_child().emit('clicked')
    assert w.opened==[tmp_path/'영상.mp4']


def test_save_and_delete_without_password(window):
    w=window;w.address.set_text('sftp://u:secret@host/');w.save_server()
    assert not w.store.path.exists() and 'secret' not in w.status.get_text()
    w.address.set_text('nfs://host/export');w.name.set_text('NAS');w.save_server()
    assert w.store.load()[0].uri=='nfs://host/export'
    w.remove_server(w.saved[0]);assert w.store.load()==[]


@pytest.mark.parametrize('created',[False,True])
def test_only_bora_created_mounts_disconnect(created,tmp_path,monkeypatch):
    from bora.platform.linux import network
    events=[]
    class Mount:
        def get_root(self):return Gio.File.new_for_path(str(tmp_path))
        def unmount_with_operation(self,flags,operation,cancel,callback):
            events.append(flags)
            callback(self,None)
        def unmount_with_operation_finish(self,result):return True
    mount=Mount()
    class File:
        def get_uri_scheme(self):return 'smb'
        def mount_enclosing_volume(self,flags,op,cancel,callback):callback(self,None)
        def mount_enclosing_volume_finish(self,result):
            if not created:
                raise GLib.Error.new_literal(Gio.io_error_quark(),'borrowed',Gio.IOErrorEnum.ALREADY_MOUNTED)
            return True
        def find_enclosing_mount_async(self,priority,cancel,callback):callback(self,None)
        def find_enclosing_mount_finish(self,result):return mount
    session=network.Session();browser=network.Browser(None,session)
    monkeypatch.setattr(network.Gio.Vfs,'get_default',lambda:SimpleNamespace(get_supported_uri_schemes=lambda:['smb']))
    monkeypatch.setattr(network.Gtk.MountOperation,'new',lambda _:Gio.MountOperation())
    original=network.Gio.File.new_for_uri
    monkeypatch.setattr(network.Gio.File,'new_for_uri',lambda _:File())
    monkeypatch.setattr(browser,'_list',lambda *args:None)
    browser.browse('smb://host/share',lambda *args:None)
    # 탐색창 닫기는 연결을 끊지 않으며 플레이어의 세션 종료가 해제한다.
    browser.stop()
    assert events==[]
    completed=[]
    store=ServerStore(tmp_path);store.save([Server('NAS','smb://host/share')]);before=store.path.read_bytes()
    session.close(lambda errors:completed.append(errors))
    assert completed==[[]]
    assert len(events)==int(created)
    if events:assert events[0]==Gio.MountUnmountFlags.NONE
    assert store.path.read_bytes()==before


def test_shutdown_waits_for_connection_already_in_flight(tmp_path):
    from bora.platform.linux.network import Session
    session=Session();session.begin();done=[];calls=[]
    mount=SimpleNamespace(get_root=lambda:Gio.File.new_for_path(str(tmp_path)),
         unmount_with_operation=lambda flags,op,cancel,callback:calls.append(callback),
         unmount_with_operation_finish=lambda result:True)
    session.close(lambda errors:done.append(errors))
    assert done==[]
    session.take(mount);session.end();assert done==[]
    calls[0](mount,None)
    assert done==[[]]
