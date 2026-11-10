"""Root 전용 NFS 브로커. 입력은 URI와 요청 ID뿐이며 작업·경로·옵션은 고정이다.

설치된 복사본은 /usr/bin/python3 -I로 시작한다. 사용자 Python 경로를 읽지 않는다.
"""
import ipaddress
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit

NAME = 'com.icurfer.Bora.NFS'
OBJECT = '/com/icurfer/Bora/NFS'
ACTION = 'com.icurfer.Bora.nfs-connect'
BASE = Path('/run/bora-nfs')
OPTIONS = 'ro,nosuid,nodev,noexec,soft,timeo=50,retrans=2,retry=0,resvport'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}
TOKEN = re.compile(r'^[0-9a-f]{32}$')
XML = '''<node><interface name="com.icurfer.Bora.NFS">
<method name="Mount"><arg type="s" direction="in" name="uri"/><arg type="s" direction="in" name="token"/><arg type="s" direction="out" name="path"/></method>
<method name="Cancel"><arg type="s" direction="in" name="token"/></method>
<method name="Release"><arg type="s" direction="in" name="token"/></method>
</interface></node>'''


def source_for(uri):
    if not isinstance(uri, str) or len(uri) > 4096 or any(ord(c) < 32 for c in uri):
        raise ValueError('잘못된 NFS 주소입니다.')
    parsed = urlsplit(uri)
    if (parsed.scheme != 'nfs' or not parsed.hostname or parsed.username is not None
            or parsed.query or parsed.fragment or parsed.port is not None):
        raise ValueError('nfs://서버/내보낸경로 형식으로 입력하세요. 사용자·비밀번호·옵션은 넣을 수 없습니다.')
    host = parsed.hostname
    if '%' in host:
        raise ValueError('서버 주소에 영역 식별자를 넣을 수 없습니다.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if (len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host)
                or any(not part or len(part) > 63 or part.startswith('-') or part.endswith('-') for part in host.split('.'))):
            raise ValueError('잘못된 서버 이름입니다.') from None
    path = unquote(parsed.path)
    if (not path.startswith('/') or any(ord(c) < 32 for c in path)
            or '\\' in path or any(p in ('.', '..') for p in path.split('/'))):
        raise ValueError('잘못된 내보내기 경로입니다.')
    return ('[' + host + ']' if ':' in host else host) + ':' + path


def secure_base():
    try:
        BASE.mkdir(mode=0o711)
    except FileExistsError:
        pass
    info = BASE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise OSError('안전한 NFS 전용 경로를 준비하지 못했습니다.')


def mount_record(target):
    """커널이 기록한 정확한 마운트 ID와 파일시스템만 확인한다."""
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        decoded = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
        if decoded == str(target):
            after = fields[fields.index('-') + 1:]
            return fields[0], after[0]
    return None


def run_fixed(argv, seconds=18):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=ENV, cwd='/', start_new_session=True)
    try:
        out, err = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise OSError('NFS 연결 작업 시간이 초과됐습니다.') from None
    if process.returncode:
        # mount 오류 원문에는 사용자 경로 등이 들어갈 수 있어 반환하지 않는다.
        raise OSError('NFS 작업을 완료하지 못했습니다. 서버 경로·접근 권한과 연결 상태를 확인하세요.')


class Mounts:
    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def start_view(self, raw, view, uid):
        fd = os.open(raw, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            program = Path(__file__).with_name('nfs_view.py')
            process = subprocess.Popen(['/usr/bin/python3', '-I', str(program), str(fd),
                str(uid), str(view)], pass_fds=(fd,), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, cwd='/')
        finally:
            os.close(fd)
        for unused in range(100):
            record = mount_record(view)
            if record and record[1].startswith('fuse'):
                return process, record
            if process.poll() is not None:
                break
            time.sleep(0.05)
        process.terminate()
        process.wait(timeout=3)
        record = mount_record(view)
        if record and record[1].startswith('fuse'):
            run_fixed(['/usr/bin/umount', '--', str(view)], 6)
        raise OSError('NFS 읽기 전용 전달 경로를 준비하지 못했습니다.')

    def create(self, owner, token, uri, uid):
        source = source_for(uri)
        secure_base()
        session = Path(tempfile.mkdtemp(prefix='session-', dir=BASE))
        os.chmod(session, 0o711)
        private = session / 'private'
        private.mkdir(mode=0o700)
        raw, view = private / 'share', session / 'files'
        raw.mkdir(mode=0o700)
        view.mkdir(mode=0o700)
        try:
            run_fixed(['/usr/bin/mount', '-t', 'nfs', '-o', OPTIONS, '--', source, str(raw)])
            record = mount_record(raw)
            if record is None or record[1] not in ('nfs', 'nfs4'):
                raise OSError('NFS 연결을 확인하지 못했습니다.')
            process, view_record = self.start_view(raw, view, uid)
            with self.lock:
                self.entries[(owner, token)] = (session, record, view_record, process)
            return str(view)
        except Exception:
            record = mount_record(raw)
            if record and record[1] in ('nfs', 'nfs4'):
                run_fixed(['/usr/bin/umount', '--', str(raw)], 6)
            view.rmdir()
            raw.rmdir()
            private.rmdir()
            session.rmdir()
            raise

    def release(self, owner, token):
        with self.lock:
            entry = self.entries.get((owner, token))
            if entry is None:
                raise ValueError('이 호출자가 소유한 연결이 아닙니다.')
            session, expected, view_expected, process = entry
            raw, view = session / 'private/share', session / 'files'
            if mount_record(raw) != expected or mount_record(view) != view_expected:
                raise OSError('연결의 마운트 ID가 바뀌어 해제하지 않았습니다.')
            # 열린 플레이어 fd가 있어도 이 앱 전용 읽기 경로를 분리한다.
            # 로컬/NAS의 다른 마운트에는 적용하지 않는다.
            if view_expected is not None:
                run_fixed(['/usr/bin/umount', '-l', '--', str(view)], 6)
                self.entries[(owner, token)] = (session, expected, None, process)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            run_fixed(['/usr/bin/umount', '--', str(raw)], 6)
            view.rmdir()
            raw.rmdir()
            raw.parent.rmdir()
            session.rmdir()
            del self.entries[(owner, token)]


class Broker:
    def __init__(self, connection, loop):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.connection, self.loop = connection, loop
        self.mounts = Mounts()
        self.pending = {}
        self.releasing = set()
        self.stopping = False
        self.owner_uids = {}
        self.disconnected = set()
        self.last_busy = GLib.get_monotonic_time()
        connection.register_object(OBJECT, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.method, None, None)
        connection.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
                                    '/org/freedesktop/DBus', None, Gio.DBusSignalFlags.NONE, self.owner_changed)
        GLib.timeout_add_seconds(15, self.idle)

    def fail(self, invocation, message):
        invocation.return_dbus_error(NAME + '.Error', message)

    def uid(self, owner):
        result = self.connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'GetConnectionUnixUser', self.GLib.Variant('(s)', (owner,)),
            self.GLib.VariantType.new('(u)'), self.Gio.DBusCallFlags.NONE, 2000, None)
        return result.unpack()[0]

    def method(self, connection, owner, path, interface, method, parameters, invocation):
        self.last_busy = self.GLib.get_monotonic_time()
        args = parameters.unpack()
        token = args[-1]
        if not TOKEN.fullmatch(token):
            self.fail(invocation, '잘못된 요청 ID입니다.')
            return
        key = (owner, token)
        if method == 'Mount':
            uri = args[0]
            try:
                source_for(uri)
                uid = self.uid(owner)
                if self.stopping:
                    raise ValueError('연결 서비스를 종료하는 중입니다.')
                if key in self.pending or key in self.mounts.entries:
                    raise ValueError('이미 사용 중인 요청 ID입니다.')
                if len(self.pending) + len(self.mounts.entries) >= 16:
                    raise ValueError('연결 수 제한에 도달했습니다.')
                if sum(v['uid'] == uid for v in self.pending.values()) + sum(self.owner_uids.get(k[0]) == uid for k in list(self.mounts.entries)) >= 4:
                    raise ValueError('이 사용자의 연결 수 제한에 도달했습니다.')
            except Exception as error:
                self.fail(invocation, str(error))
                return
            request = {'uid': uid, 'cancelled': False, 'working': False, 'id': uuid.uuid4().hex}
            self.pending[key] = request
            self.owner_uids[owner] = uid
            subject = ('system-bus-name', {'name': self.GLib.Variant('s', owner)})
            values = (subject, ACTION, {}, 1, request['id'])
            def authorized(source, result):
                try:
                    answer = source.call_finish(result).unpack()[0]
                    if not answer[0] or request['cancelled']:
                        raise ValueError('관리자 인증을 취소했거나 허용되지 않았습니다.')
                except Exception:
                    self.pending.pop(key, None)
                    self.fail(invocation, '관리자 인증을 취소했거나 허용되지 않았습니다.')
                    return
                request['working'] = True
                def work():
                    try:
                        mount_path = self.mounts.create(owner, token, uri, uid)
                        error = None
                    except Exception as exc:
                        mount_path, error = None, str(exc)
                    def finish():
                        self.pending.pop(key, None)
                        if request['cancelled'] and mount_path:
                            self.release(key, None)
                            self.fail(invocation, '연결을 취소했습니다.')
                        elif error:
                            self.fail(invocation, error)
                        else:
                            invocation.return_value(self.GLib.Variant('(s)', (mount_path,)))
                        return False
                    self.GLib.idle_add(finish)
                threading.Thread(target=work, daemon=True).start()
            self.connection.call('org.freedesktop.PolicyKit1', '/org/freedesktop/PolicyKit1/Authority',
                'org.freedesktop.PolicyKit1.Authority', 'CheckAuthorization',
                self.GLib.Variant('((sa{sv})sa{ss}us)', values), self.GLib.VariantType.new('((bba{ss}))'),
                self.Gio.DBusCallFlags.NONE, 120000, None, authorized)
        elif method == 'Cancel':
            if key in self.pending:
                self.cancel(key)
            elif key in self.mounts.entries:
                self.release(key, None)
            invocation.return_value(None)
        elif method == 'Release':
            self.release(key, invocation)

    def cancel(self, key):
        request = self.pending[key]
        request['cancelled'] = True
        if not request['working']:
            self.connection.call('org.freedesktop.PolicyKit1', '/org/freedesktop/PolicyKit1/Authority',
                'org.freedesktop.PolicyKit1.Authority', 'CancelCheckAuthorization',
                self.GLib.Variant('(s)', (request['id'],)), None, self.Gio.DBusCallFlags.NONE, 2000, None, None)

    def release(self, key, invocation):
        if key not in self.mounts.entries or key in self.releasing:
            if invocation:
                self.fail(invocation, '이 호출자가 소유한 연결이 아니거나 해제 중입니다.')
            return
        self.releasing.add(key)
        def work():
            try:
                self.mounts.release(*key)
                error = None
            except Exception as exc:
                error = str(exc)
            def finish():
                self.releasing.discard(key)
                if invocation:
                    if error:
                        self.fail(invocation, error)
                    else:
                        invocation.return_value(None)
                elif error:
                    print('Bora NFS 연결 정리 실패: ' + error, flush=True)
                return False
            self.GLib.idle_add(finish)
        threading.Thread(target=work, daemon=True).start()

    def owner_changed(self, connection, sender, path, interface, signal_name, parameters, *unused):
        owner, before, after = parameters.unpack()
        if before and not after and owner in self.owner_uids:
            self.disconnected.add(owner)
            for key in list(self.pending):
                if key[0] == owner:
                    self.cancel(key)
            for key in list(self.mounts.entries):
                if key[0] == owner:
                    self.release(key, None)

    def shutdown(self):
        self.stopping = True
        for key in list(self.pending):
            self.cancel(key)
        for key in list(self.mounts.entries):
            self.release(key, None)
        self.GLib.timeout_add_seconds(40, lambda: (self.loop.quit(), False)[1])
        return False

    def idle(self):
        active = {key[0] for key in list(self.pending) + list(self.mounts.entries)}
        self.owner_uids = {owner: uid for owner, uid in self.owner_uids.items() if owner in active}
        self.disconnected.intersection_update(active)
        for key in list(self.mounts.entries):
            if self.stopping or key[0] in self.disconnected:
                self.release(key, None)
        if self.stopping and not self.pending and not self.mounts.entries and not self.releasing:
            self.loop.quit()
            return False
        if not self.pending and not self.mounts.entries and not self.releasing:
            if self.GLib.get_monotonic_time() - self.last_busy > 30000000:
                self.loop.quit()
                return False
        return True


def main():
    if os.geteuid() != 0:
        raise SystemExit('이 프로그램은 시스템 서비스로만 실행됩니다.')
    import gi
    from gi.repository import Gio, GLib
    loop = GLib.MainLoop()
    instances = []
    def acquired(connection, name):
        broker = Broker(connection, loop)
        instances.append(broker)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, broker.shutdown)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, broker.shutdown)
    Gio.bus_own_name(Gio.BusType.SYSTEM, NAME, Gio.BusNameOwnerFlags.NONE, acquired,
                     None, lambda *args: loop.quit())
    loop.run()


if __name__ == '__main__':
    main()
