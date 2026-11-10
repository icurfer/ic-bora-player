"""Root의 로컬 경로가 NAS의 링크/교체를 통해 노출되지 않는지 실제 커널로 검사."""
import os
import errno
import stat
import pytest
import pyfuse3
import trio
from bora.platform.linux.nfs_view import beneath, operations


def test_atomic_root_boundary_and_non_regular_files(tmp_path):
    share=tmp_path/'share';share.mkdir()
    outside=tmp_path/'secret';outside.write_text('local secret')
    (share/'normal').write_bytes(b'video bytes')
    (share/'escape').symlink_to(outside)
    (share/'dirlink').symlink_to(tmp_path,target_is_directory=True)
    os.mkfifo(share/'fifo')
    root=os.open(share,os.O_PATH|os.O_DIRECTORY)
    try:
        fd=beneath(root,b'normal',os.O_RDONLY)
        assert os.read(fd,11)==b'video bytes';os.close(fd)
        for path in (b'../secret',b'/etc/passwd',b'escape',b'dirlink/secret',b'fifo',b'a//b'):
            with pytest.raises(OSError):beneath(root,path,os.O_PATH)
        # 정상 디렉터리 이름이 링크로 바뀐 후에도 같은 경로를 다시 열지 못한다.
        (share/'folder').mkdir();(share/'folder'/'file').write_bytes(b'ok')
        fd=beneath(root,b'folder/file',os.O_RDONLY);os.close(fd)
        (share/'folder').rename(share/'old')
        (share/'folder').symlink_to(tmp_path,target_is_directory=True)
        with pytest.raises(OSError):beneath(root,b'folder/secret',os.O_RDONLY)
    finally:os.close(root)


def test_view_owner_only_read_and_pinned_file_handle(tmp_path):
    (tmp_path/'movie').write_bytes(b'0123456789')
    root=os.open(tmp_path,os.O_PATH|os.O_DIRECTORY)
    view=operations(root,1234)
    async def scenario():
        node=await view.lookup(1,b'movie')
        assert node.st_uid==1234 and stat.S_IMODE(node.st_mode)==0o400
        assert stat.S_IMODE((await view.getattr(1)).st_mode)==0o500
        for flags in (os.O_WRONLY,os.O_RDWR,os.O_TRUNC,os.O_CREAT,os.O_APPEND):
            with pytest.raises(pyfuse3.FUSEError) as denied:await view.open(node.st_ino,flags,None)
            assert denied.value.errno==errno.EROFS
        handle=await view.open(node.st_ino,os.O_RDONLY,None)
        (tmp_path/'movie').unlink();(tmp_path/'movie').symlink_to('/etc/passwd')
        assert await view.read(handle.fh,3,4)==b'3456'
        with pytest.raises(pyfuse3.FUSEError):await view.getattr(node.st_ino)
        await view.release(handle.fh)
        await view.forget([(node.st_ino,1)])
        assert len(view.paths)==1
    try:trio.run(scenario)
    finally:os.close(root)
