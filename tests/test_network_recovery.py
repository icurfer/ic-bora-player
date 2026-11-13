"""같은 영상 재열기와 실제 저장 실패 뒤 종료 선택의 데이터 경계."""
import errno
import os
import time
from pathlib import Path
from types import SimpleNamespace
import gi
import pytest
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,Gio,GLib
from bora.network import remember_remote
from bora.network_window import NetworkWindow
from bora.network import ServerStore
from bora.notes.model import NoteDocument
from bora.notes import recovery


def pump():
    context=GLib.MainContext.default()
    end=time.monotonic()+.05
    while time.monotonic()<end:
        context.iteration(False);time.sleep(.001)


def test_nfs_note_and_assets_survive_mount_path_change(tmp_path,monkeypatch):
    from bora.platform import paths
    from bora.state import _key
    from bora.ai.history import Conversation
    monkeypatch.setattr(paths,'data_dir',lambda:tmp_path/'data')
    first=tmp_path/'mount1';second=tmp_path/'mount2';first.mkdir();second.mkdir()
    remember_remote(first,'nfs://nas/export',root=True)
    remember_remote(second,'nfs://nas/export',root=True)
    a,b=first/'영상.mp4',second/'영상.mp4'
    a.with_suffix('.md').write_text('원격 원본',encoding='utf-8')
    note=NoteDocument.load_for(a);note.text+='\n로컬 추가';note.save()
    assert note.path.is_relative_to(tmp_path/'data'/'network-notes')
    assert NoteDocument.load_for(b).text=='원격 원본\n로컬 추가\n'
    assert a.with_suffix('.md').read_text()=='원격 원본'
    assert NoteDocument.assets_dir_for(a)==NoteDocument.assets_dir_for(b)
    assert _key(a)==_key(b) and Conversation(a).path==Conversation(b).path
    assert NoteDocument.path_for(tmp_path/'local.mp4')==tmp_path/'local.md'


def test_reopen_browser_restores_folder_and_remembers_server(tmp_path):
    Gtk.init();parent=Gtk.Window();store=ServerStore(tmp_path)
    session=SimpleNamespace(last_location=None,last_server=None)
    class Backend:
        def __init__(self):self.calls=[]
        def browse(self,uri,done):self.calls.append(uri);done((Gio.File.new_for_uri(uri),[]),'')
        def stop(self):pass
    w=NetworkWindow(parent,lambda _:True,backend=Backend(),store=store,session=session)
    w.address.set_text('sftp://user@host/share');w.connect_server()
    w._browse(Gio.File.new_for_uri('sftp://user@host/share/folder'))
    w.close()
    backend=Backend();again=NetworkWindow(parent,lambda _:True,backend=backend,store=store,session=session)
    pump()
    assert backend.calls==['sftp://user@host/share/folder']
    assert again.address.get_text()=='sftp://user@host/share' and len(store.load())==1
    again.remove_server(again.saved[0]);again.close()
    # 현재 연결 위치 복원은 삭제한 즐겨찾기를 몰래 재등록하지 않는다.
    third=NetworkWindow(parent,lambda _:True,backend=Backend(),store=store,session=session);pump()
    assert store.load()==[]
    for window in (w,again,third):window.destroy()
    parent.destroy()


@pytest.fixture
def failing_panel(tmp_path):
    Gtk.init();window=Gtk.Window();events=[]
    window.toast=lambda text:events.append(text)
    window.close=lambda:events.append('closed')
    doc=NoteDocument(tmp_path/'original.md','initial')
    doc.text='미저장 본문'
    panel=SimpleNamespace(doc=doc,window=window,_text=lambda:doc.text,
                          prepare_leave=lambda:False,_cancel_autosave=lambda:None)
    yield panel,events
    dialog=getattr(panel,'_save_failure_dialog',None)
    if dialog:dialog.destroy()
    window.destroy()


def test_failed_save_close_cancel_and_recovery(failing_panel,tmp_path,monkeypatch):
    panel,events=failing_panel
    from bora.platform import paths
    monkeypatch.setattr(paths,'data_dir',lambda:tmp_path/'data')
    assert recovery.prepare_close(panel) is False
    panel._save_failure_dialog.response(Gtk.ResponseType.CANCEL);pump()
    assert panel.doc.dirty and 'closed' not in events
    assert recovery.prepare_close(panel) is False
    panel._save_failure_dialog.response(Gtk.ResponseType.APPLY);pump()
    files=list((tmp_path/'data'/'recovered-notes').glob('*.md'))
    assert len(files)==1 and files[0].read_text()=='미저장 본문'
    assert files[0].stat().st_mode&0o077==0 and not panel.doc.path.exists()
    assert recovery.prepare_close(panel) is True and events[-1]=='closed'
    panel.doc.text+='more'
    assert recovery.prepare_close(panel) is False # 사본 저장 뒤 새 편집은 다시 보호한다.


def test_recovery_failure_does_not_exit_but_explicit_discard_can(failing_panel,monkeypatch):
    panel,events=failing_panel
    def denied(*args,**kwargs):raise OSError(errno.ENOSPC,'full')
    monkeypatch.setattr(recovery,'copy_text',denied)
    assert recovery.prepare_close(panel) is False
    panel._save_failure_dialog.response(Gtk.ResponseType.APPLY);pump()
    assert 'closed' not in events and panel.doc.dirty
    assert panel._save_failure_dialog is not None
    panel._save_failure_dialog.response(Gtk.ResponseType.REJECT);pump()
    assert events[-1]=='closed' and recovery.prepare_close(panel) is True


def test_copy_error_keeps_original_and_cleans_temporary(tmp_path,monkeypatch):
    dest=tmp_path/'chosen.md';dest.write_text('original')
    def full(*args):raise OSError(errno.ENOSPC,'full')
    monkeypatch.setattr(os,'fsync',full)
    with pytest.raises(OSError):recovery.copy_text('new body',dest)
    assert dest.read_text()=='original' and list(tmp_path.iterdir())==[dest]


def test_nfs_second_browser_reuses_connection_without_auth(tmp_path,monkeypatch):
    from bora.platform.linux import network,nfs_client
    session=network.Session();calls=[]
    mount=SimpleNamespace(token='a'*32,uri='nfs://nas/export',get_root=lambda:Gio.File.new_for_path(str(tmp_path)))
    def connect(uri,done):
        calls.append(uri);done(mount,'');return {'token':'a'*32}
    monkeypatch.setattr(nfs_client,'connect',connect)
    monkeypatch.setattr(nfs_client,'cancel_request',lambda r:None)
    for _ in range(2):
        browser=network.Browser(None,session)
        monkeypatch.setattr(browser,'_list',lambda *args:None)
        browser.browse('nfs://nas/export',lambda *args:None)
        browser.stop()
    assert calls==['nfs://nas/export'] and len(session.owned)==1


def test_saved_chat_note_transcription_failure_does_not_block_close():
    from bora.ai.panel import ChatPanel
    messages=[]
    panel=SimpleNamespace(cancel=lambda:None,_save=lambda:True,record_notes=lambda:False,
                          window=SimpleNamespace(toast=messages.append))
    assert ChatPanel.prepare_close(panel) is True and messages


def test_save_elsewhere_close_keeps_original(failing_panel,tmp_path,monkeypatch):
    panel,events=failing_panel
    dest=tmp_path/'selected.md'
    class Chooser:
        def __init__(self,**kwargs):pass
        def set_current_name(self,name):pass
        def connect(self,signal,callback):self.callback=callback
        def show(self):pass
        def destroy(self):pass
        def get_file(self):return Gio.File.new_for_path(str(dest))
    monkeypatch.setattr(recovery.Gtk,'FileChooserNative',Chooser)
    assert recovery.prepare_close(panel) is False
    panel._save_failure_dialog.response(Gtk.ResponseType.ACCEPT)
    chooser=panel._save_failure_dialog
    chooser.callback(chooser,Gtk.ResponseType.ACCEPT);pump()
    assert dest.read_text()=='미저장 본문' and not panel.doc.path.exists()
    assert events[-1]=='closed'


@pytest.fixture
def autosave_panel(tmp_path):
    from bora.notes.panel import NotePanel
    Gtk.init()
    panel=NotePanel.__new__(NotePanel)
    Gtk.Box.__init__(panel)
    panel.window=SimpleNamespace(toast=lambda _:None)
    panel.doc=NoteDocument(tmp_path/'autosave.md')
    panel._save_id=0;panel._loading=False;panel._last_line=-1
    panel._ask=None;panel._ask_generation=0;panel._answer_mark=None
    panel._buffer=Gtk.TextBuffer();panel._status=Gtk.Label()
    panel._make_tags()
    panel._buffer.connect('changed',panel._on_changed)
    yield panel
    panel._cancel_autosave()


def run_until(condition,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        GLib.MainContext.default().iteration(False)
        if condition():return True
        time.sleep(.005)
    return bool(condition())


def test_autosave_one_second_after_last_input(autosave_panel):
    panel=autosave_panel;path=panel.doc.path
    panel._buffer.insert_at_cursor('# 한글 메모\n')
    run_until(lambda:False,.65)
    panel._buffer.insert_at_cursor('추가 입력')
    run_until(lambda:False,.55)
    assert not path.exists() # 첫 입력에서1초가 지나도 추가입력의 대기시간을 지킨다.
    assert run_until(path.exists,.7) # 기존2초 지연이면 여기까지 저장되지 않는다.
    assert path.read_text()=='# 한글 메모\n추가 입력\n'
    assert not panel.doc.dirty and '저장됨' in panel._status.get_label()
    assert panel._save_id==0


@pytest.mark.parametrize('code',[errno.EROFS,errno.ENOSPC])
def test_autosave_failure_preserves_body_and_can_retry(autosave_panel,monkeypatch,code):
    panel=autosave_panel;original=panel.doc.save
    def fail():raise OSError(code,'fixture')
    monkeypatch.setattr(panel.doc,'save',fail)
    panel._buffer.insert_at_cursor('보존할 본문')
    assert run_until(lambda:'저장 실패' in panel._status.get_label(),1.5)
    assert panel.doc.dirty and panel._text()=='보존할 본문' and not panel.doc.path.exists()
    assert panel._save_id==0 # 실패한 저장을 무한 반복하지 않는다.
    monkeypatch.setattr(panel.doc,'save',original)
    panel._buffer.insert_at_cursor(' 다시 편집')
    assert run_until(panel.doc.path.exists,1.5)
    assert panel.doc.path.read_text()=='보존할 본문 다시 편집\n' and not panel.doc.dirty


def test_pending_autosave_flushes_before_switch_and_protects_external_change(autosave_panel,tmp_path):
    panel=autosave_panel;first=panel.doc.path
    panel._buffer.insert_at_cursor('이전 영상 메모')
    assert panel.load_for(tmp_path/'second.mp4')
    assert first.read_text()=='이전 영상 메모\n' and panel._save_id==0
    panel._buffer.insert_at_cursor('새 영상 메모')
    second=panel.doc.path
    second.write_text('외부에서 작성한 원본')
    assert run_until(lambda:panel._save_id==0,1.5)
    assert second.read_text()=='외부에서 작성한 원본'
    assert '새 영상 메모' in panel._text() and panel.doc.dirty
    assert '외부 변경' in panel._status.get_label()
