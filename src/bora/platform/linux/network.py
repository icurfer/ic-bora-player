"""GIO/GVfs 비동기 서버 연결·탐색. 자체 네트워크 프로토콜은 구현하지 않는다."""
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk


def available():
    return any(s in Gio.Vfs.get_default().get_supported_uri_schemes() for s in ('smb', 'sftp', 'nfs'))


def reason():
    return '네트워크 파일 기능이 없습니다. gvfs-backends와 gvfs-fuse 설치를 확인하세요.'


def local_path(file):
    path = file.get_path()
    if path:
        return Path(path)
    root = file.find_enclosing_mount(None).get_default_location()
    base, relative = root.get_path(), root.get_relative_path(file)
    if base and relative is not None:
        return Path(base) / relative
    raise ValueError('재생용 원격 경로를 열 수 없습니다. gvfs-fuse 설치 후 다시 연결하세요.')


class Browser:
    def __init__(self, parent):
        self.parent = parent
        self.cancel = Gio.Cancellable()
        self.generation = 0
        self.operation = None

    def stop(self):
        self.generation += 1
        self.cancel.cancel()
        self.cancel = Gio.Cancellable()
        if self.operation is not None:
            self.operation.emit('aborted')
            self.operation = None

    def browse(self, uri, done):
        self.stop()
        generation, cancel = self.generation, self.cancel
        file = Gio.File.new_for_uri(uri)
        if file.get_uri_scheme() not in Gio.Vfs.get_default().get_supported_uri_schemes():
            done(None, reason())
            return
        operation = Gtk.MountOperation.new(self.parent)
        operation.set_password_save(Gio.PasswordSave.NEVER)
        self.operation = operation
        def mounted(source, result):
            if generation != self.generation:
                return
            self.operation = None
            try:
                source.mount_enclosing_volume_finish(result)
            except GLib.Error as error:
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                    done(None, '연결하지 못했습니다. 서버 주소·계정·공유 권한을 확인하세요. NFS는 서버의 내보내기 설정과 클라이언트 접근 권한도 확인하세요.')
                    return
            self._list(file, generation, cancel, done)
        file.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, cancel, mounted)

    def _list(self, file, generation, cancel, done):
        entries = []
        def opened(source, result):
            try:
                iterator = source.enumerate_children_finish(result)
            except GLib.Error:
                if generation == self.generation:
                    done(None, '폴더를 읽지 못했습니다. 경로·접근 권한·연결 상태를 확인하세요.')
                return
            if generation != self.generation:
                iterator.close_async(GLib.PRIORITY_DEFAULT, None, None)
                return
            def batch(source, result):
                try:
                    infos = source.next_files_finish(result)
                except GLib.Error:
                    source.close_async(GLib.PRIORITY_DEFAULT, None, None)
                    if generation == self.generation:
                        done(None, '목록을 읽는 중 연결이 끊겼습니다. 다시 읽기를 눌러주세요.')
                    return
                if generation != self.generation:
                    source.close_async(GLib.PRIORITY_DEFAULT, None, None)
                    return
                for info in infos:
                    kind = info.get_file_type()
                    if kind in (Gio.FileType.DIRECTORY, Gio.FileType.REGULAR):
                        entries.append((info.get_name(), info.get_display_name(), kind == Gio.FileType.DIRECTORY))
                if not infos or len(entries) >= 1000:
                    source.close_async(GLib.PRIORITY_DEFAULT, None, None)
                    entries.sort(key=lambda x: (not x[2], x[1].casefold()))
                    done((file, entries[:1000]), '항목이 많아 처음 1000개까지만 표시합니다.' if len(entries) >= 1000 else '')
                else:
                    source.next_files_async(100, GLib.PRIORITY_DEFAULT, cancel, batch)
            iterator.next_files_async(100, GLib.PRIORITY_DEFAULT, cancel, batch)
        file.enumerate_children_async('standard::name,standard::display-name,standard::type',
                                      Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT, cancel, opened)
