"""승인된 NFS 디렉터리만 일반 사용자에게 읽기 전용으로 전달한다.

경로를 문자열로 이어 열지 않는다. 커널 openat2가 고정된 공유 루트 아래에서
링크와 다른 마운트로의 이동을 원자적으로 차단한다. 로컬 파일 프록시가 아니다.
"""
import ctypes
import errno
import os
import platform
import stat


def beneath(root, path, flags):
    if (path.startswith(b'/') or b'\0' in path
            or any(p in (b'..', b'') for p in path.split(b'/'))):
        raise OSError(errno.EACCES, '공유 밖 경로')
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise OSError(errno.ENOSYS, '검증되지 않은 openat2 플랫폼')
    class How(ctypes.Structure):
        _fields_ = [('flags', ctypes.c_uint64), ('mode', ctypes.c_uint64),
                    ('resolve', ctypes.c_uint64)]
    # NO_XDEV | NO_MAGICLINKS | NO_SYMLINKS | BENEATH
    how = How(flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0, 0x01 | 0x02 | 0x04 | 0x08)
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(ctypes.c_long(437), ctypes.c_int(root), ctypes.c_char_p(path),
                      ctypes.byref(how), ctypes.sizeof(how))
    if fd < 0:
        raise OSError(ctypes.get_errno(), '공유 안의 일반 파일·폴더만 읽을 수 있습니다.')
    info = os.fstat(fd)
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        os.close(fd)
        raise OSError(errno.EACCES, '일반 파일·폴더만 읽을 수 있습니다.')
    return fd


def operations(root, uid):
    import pyfuse3 as fuse
    from contextlib import contextmanager

    class View(fuse.Operations):
        def __init__(self):
            super().__init__()
            self.paths = {1: b'.'}
            self.inodes = {b'.': 1}
            self.refs = {1: 1}
            self.serial = 1
            self.handles = {}
            self.handle_serial = 0

        @contextmanager
        def opened(self, inode, flags):
            fd = None
            try:
                fd = beneath(root, self.paths[inode], flags)
                yield fd
            except KeyError:
                raise fuse.FUSEError(errno.ENOENT) from None
            except OSError as error:
                raise fuse.FUSEError(error.errno) from None
            finally:
                if fd is not None:
                    os.close(fd)

        def handle(self, value):
            self.handle_serial += 1
            self.handles[self.handle_serial] = value
            return self.handle_serial

        def node(self, path):
            if path not in self.inodes:
                if len(self.paths) >= 65536:
                    raise fuse.FUSEError(errno.ENOSPC)
                self.serial += 1
                self.inodes[path] = self.serial
                self.paths[self.serial] = path
                self.refs[self.serial] = 0
            return self.inodes[path]

        async def getattr(self, inode, ctx=None):
            with self.opened(inode, os.O_PATH) as fd:
                info = os.fstat(fd)
            result = fuse.EntryAttributes()
            result.st_ino = inode
            result.st_mode = (stat.S_IFDIR | 0o500) if stat.S_ISDIR(info.st_mode) else (stat.S_IFREG | 0o400)
            result.st_uid = uid
            result.st_gid = 0
            for name in ('st_size', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns'):
                setattr(result, name, getattr(info, name))
            result.st_nlink = 1
            result.entry_timeout = result.attr_timeout = 0
            return result

        async def lookup(self, parent, name, ctx=None):
            if name == b'.':
                inode = parent
            elif name == b'..':
                path = self.paths.get(parent, b'.')
                inode = self.node(path.rsplit(b'/', 1)[0] if b'/' in path else b'.')
            else:
                if not name or b'/' in name or b'\0' in name:
                    raise fuse.FUSEError(errno.EACCES)
                inode = self.node(self.paths[parent] + b'/' + name)
            try:
                result = await self.getattr(inode)
            except fuse.FUSEError:
                await self.forget([(inode, 0)])
                raise
            self.refs[inode] += 1
            return result

        async def forget(self, values):
            for inode, count in values:
                self.refs[inode] = max(0, self.refs.get(inode, 0) - count)
                if inode != 1 and not self.refs[inode]:
                    path = self.paths.pop(inode, None)
                    self.inodes.pop(path, None)
                    self.refs.pop(inode, None)

        async def opendir(self, inode, ctx):
            with self.opened(inode, os.O_RDONLY | os.O_DIRECTORY) as fd:
                with os.scandir(fd) as items:
                    names = []
                    for item in items:
                        if len(names) >= 50000:
                            raise fuse.FUSEError(errno.EOVERFLOW)
                        names.append(os.fsencode(item.name))
            return self.handle((self.paths[inode], names))

        async def readdir(self, fh, start, token):
            parent, names = self.handles[fh]
            for i in range(start, len(names)):
                inode = self.node(parent + b'/' + names[i])
                try:
                    attr = await self.getattr(inode)
                except fuse.FUSEError:
                    await self.forget([(inode, 0)])
                    continue
                if not fuse.readdir_reply(token, names[i], attr, i + 1):
                    await self.forget([(inode, 0)])
                    break
                self.refs[inode] += 1

        async def releasedir(self, fh):
            self.handles.pop(fh, None)

        async def open(self, inode, flags, ctx):
            if flags & (os.O_ACCMODE | os.O_TRUNC | os.O_CREAT | os.O_APPEND):
                raise fuse.FUSEError(errno.EROFS)
            with self.opened(inode, os.O_RDONLY | os.O_NONBLOCK) as fd:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise fuse.FUSEError(errno.EACCES)
                return fuse.FileInfo(fh=self.handle(os.dup(fd)))

        async def read(self, fh, offset, size):
            try:
                return os.pread(self.handles[fh], min(size, 1024 * 1024), offset)
            except OSError as error:
                raise fuse.FUSEError(error.errno) from None

        async def release(self, fh):
            os.close(self.handles.pop(fh))

    return View()


def main():
    import sys
    import pyfuse3
    import trio
    if os.geteuid() != 0 or len(sys.argv) != 4:
        raise SystemExit('시스템 NFS 서비스 전용 프로그램입니다.')
    root, uid, target = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    view = operations(root, uid)
    options = set(pyfuse3.default_options) | {'fsname=bora-nfs', 'ro', 'nosuid', 'nodev',
                                             'noexec', 'allow_other', 'default_permissions'}
    pyfuse3.init(view, target, options)
    # FUSE 설치 후 자식은 mount 등 관리자 capability를 더 사용하지 않는다.
    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
    class Caps(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32),
                    ('inheritable', ctypes.c_uint32)]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.capset(ctypes.byref(Header(0x20080522, 0)), (Caps * 2)()) != 0:
        raise OSError(ctypes.get_errno(), '권한 축소 실패')
    try:
        trio.run(pyfuse3.main)
    finally:
        pyfuse3.close(unmount=False)
        os.close(root)


if __name__ == '__main__':
    main()
