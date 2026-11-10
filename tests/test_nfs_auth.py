"""NFS 관리자 서비스의 입력·소유권·고정 명령·Polkit 경계."""
import stat
from types import SimpleNamespace
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from bora.platform.linux import nfs_service as service


@pytest.mark.parametrize('uri,expected',[
    ('nfs://192.168.0.5/volume1/video','192.168.0.5:/volume1/video'),
    ('nfs://nas.example/강의%20영상','nas.example:/강의 영상'),
    ('nfs://[::1]/export','[::1]:/export')])
def test_nfs_source(uri,expected):
    assert service.source_for(uri)==expected


@pytest.mark.parametrize('uri',['file:///etc','smb://host/share','nfs://u:password@host/x',
    'nfs://u@host/x','nfs://host:1234/x','nfs://host/x?options=rw','nfs://host/x#rw',
    'nfs://-o/rw','nfs://bad host/x','nfs://host/a/../x','nfs://host/a/%2e%2e/x',
    'nfs://host/x%00','nfs://host/a\n','nfs://host/a\\b','nfs://[fe80::1%25eth0]/x'])
def test_rejects_non_nfs_credentials_options_and_traversal(uri):
    with pytest.raises(ValueError):service.source_for(uri)


def test_runtime_directory_rejects_symlink_and_user_writable(monkeypatch):
    class Base:
        def mkdir(self,mode):raise FileExistsError
        def lstat(self):return SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_uid=0)
    monkeypatch.setattr(service,'BASE',Base())
    with pytest.raises(OSError):service.secure_base()
    service.BASE.lstat=lambda:SimpleNamespace(st_mode=stat.S_IFDIR|0o777,st_uid=0)
    with pytest.raises(OSError):service.secure_base()
    service.BASE.lstat=lambda:SimpleNamespace(st_mode=stat.S_IFDIR|0o711,st_uid=1000)
    with pytest.raises(OSError):service.secure_base()


def test_only_owner_can_release_and_mount_id_must_match(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'BASE',tmp_path)
    monkeypatch.setattr(service,'secure_base',lambda:None)
    calls=[]
    monkeypatch.setattr(service,'run_fixed',lambda argv,*args:calls.append(argv))
    records=lambda target: ('321','nfs4') if target.name=='share' else ('322','fuse.bora')
    monkeypatch.setattr(service,'mount_record',records)
    monkeypatch.setattr(service.Mounts,'start_view',lambda *args:(SimpleNamespace(wait=lambda **kw:None),('322','fuse.bora')))
    mounts=service.Mounts();token='a'*32
    target=mounts.create(':1.100',token,'nfs://192.168.0.5/volume1/video',1000)
    assert Path(target).parent.parent==tmp_path
    assert calls[0][0]=='/usr/bin/mount' and calls[0][-2]=='192.168.0.5:/volume1/video'
    assert set(('ro','nosuid','nodev','noexec','resvport')).issubset(service.OPTIONS.split(','))
    assert '--' in calls[0] and 'rw' not in service.OPTIONS.split(',')
    with pytest.raises(ValueError):mounts.release(':1.101',token)
    monkeypatch.setattr(service,'mount_record',lambda target:('999','nfs4'))
    with pytest.raises(OSError):mounts.release(':1.100',token)
    assert len(calls)==1
    monkeypatch.setattr(service,'mount_record',records)
    mounts.release(':1.100',token)
    assert calls[-2]==['/usr/bin/umount','-l','--',target] and not Path(target).exists()


def test_mount_failure_removes_only_own_temporary_directory(tmp_path,monkeypatch):
    existing=tmp_path/'other';existing.mkdir()
    monkeypatch.setattr(service,'BASE',tmp_path)
    monkeypatch.setattr(service,'secure_base',lambda:None)
    monkeypatch.setattr(service,'mount_record',lambda target:None)
    def fail(*args):raise OSError('expected')
    monkeypatch.setattr(service,'run_fixed',fail)
    with pytest.raises(OSError):service.Mounts().create(':1.1','b'*32,'nfs://host/export',1000)
    assert list(tmp_path.iterdir())==[existing]


def test_policy_requires_admin_each_active_connection_and_no_inactive_access():
    root=Path(__file__).resolve().parents[1]
    policy=ET.parse(root/'data/nfs/com.icurfer.Bora.nfs.policy')
    action=policy.find('action')
    assert action.get('id')==service.ACTION
    assert action.findtext('defaults/allow_any')=='no'
    assert action.findtext('defaults/allow_inactive')=='no'
    assert action.findtext('defaults/allow_active')=='auth_admin'
    unit=(root/'data/nfs/bora-nfs.service').read_text()
    assert 'NoNewPrivileges=yes' in unit and 'PrivateMounts=no' in unit
    launcher=(root/'data/nfs/nfs-service').read_text()
    assert '/usr/bin/python3 -I /usr/lib/bora/nfs_service.py' in launcher


def test_dbus_contract_has_no_mountpoint_uid_or_options_argument():
    tree=ET.fromstring(service.XML)
    methods=tree.findall('interface/method')
    assert [m.get('name') for m in methods]==['Mount','Cancel','Release']
    assert [a.get('name') for a in methods[0].findall('arg') if a.get('direction')=='in']==['uri','token']


def test_private_nfs_navigation_and_cancelled_completion_cleanup(tmp_path,monkeypatch):
    from gi.repository import Gio
    from bora.platform.linux import network,nfs_client
    root=Gio.File.new_for_path(str(tmp_path))
    mount=SimpleNamespace(token='a'*32,uri='nfs://nas/export',get_root=lambda:root)
    session=network.Session();browser=network.Browser(None,session)
    callbacks=[];requests=[]
    def connect(uri,done):
        callbacks.append(done);request={'token':'a'*32};requests.append(request);return request
    monkeypatch.setattr(nfs_client,'connect',connect)
    cancelled=[];monkeypatch.setattr(nfs_client,'cancel_request',lambda r:cancelled.append(r))
    listed=[];monkeypatch.setattr(browser,'_list',lambda *args:listed.append(args[0]))
    results=[]
    browser.browse('nfs://nas/export',lambda *args:results.append(args))
    browser.stop();callbacks[0](mount,'')
    assert cancelled==requests and not results and not listed
    assert session.pending==0 and session.owned
    browser.browse(root.get_child('강의').get_uri(),lambda *args:results.append(args))
    assert listed[-1].equal(root.get_child('강의'))
    assert browser.display_location(root.get_child('강의'))=='nfs://nas/export/%EA%B0%95%EC%9D%98'
    assert not browser.can_go_up(root) and browser.can_go_up(root.get_child('강의'))
    browser.browse(root.get_parent().get_uri(),lambda *args:results.append(args))
    assert results[-1][0] is None
    assert browser.read_only(root)
