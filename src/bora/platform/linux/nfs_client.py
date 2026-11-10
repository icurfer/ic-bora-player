"""비밀번호를 취급하지 않는 시스템 NFS 서비스 클라이언트."""
from uuid import uuid4
from gi.repository import Gio, GLib

NAME = 'com.icurfer.Bora.NFS'
OBJECT = '/com/icurfer/Bora/NFS'


class NativeMount:
    def __init__(self, connection, token, path, uri):
        self.connection, self.token, self.path, self.uri = connection, token, path, uri

    def get_root(self):
        return Gio.File.new_for_path(self.path)

    def unmount_with_operation(self, flags, operation, cancel, callback):
        def finished(connection, result):
            callback(self, result)
        self.connection.call(NAME, OBJECT, NAME, 'Release', GLib.Variant('(s)', (self.token,)),
                             None, Gio.DBusCallFlags.NONE, 10000, cancel, finished)

    def unmount_with_operation_finish(self, result):
        self.connection.call_finish(result)
        return True


def cancel(connection, token):
    connection.call(NAME, OBJECT, NAME, 'Cancel', GLib.Variant('(s)', (token,)),
                    None, Gio.DBusCallFlags.NONE, 3000, None, None)


def connect(uri, done):
    """연결은 비동기이며 종료한 UI에서도 결과를 받아 정리할 수 있다."""
    token = uuid4().hex
    state = {'connection': None, 'cancelled': False, 'token': token}
    def got_bus(source, result):
        try:
            connection = Gio.bus_get_finish(result)
            state['connection'] = connection
            if state['cancelled']:
                done(None, '연결을 취소했습니다.')
                return
        except GLib.Error:
            done(None, '시스템 연결 서비스에 접근하지 못했습니다.')
            return
        def mounted(connection, result):
            try:
                path = connection.call_finish(result).unpack()[0]
                mount = NativeMount(connection, token, path, uri)
                if state['cancelled']:
                    cancel(connection, token)
                    done(None, '연결을 취소했습니다.')
                else:
                    done(mount, '')
            except GLib.Error as error:
                if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    message = '연결을 취소했습니다.'
                elif 'ServiceUnknown' in error.message or 'Spawn' in error.message:
                    message = 'NFS 관리자 연결 서비스가 없습니다. 보라 패키지를 업데이트하세요.'
                else:
                    message = 'NFS 연결이 허용되지 않았거나 실패했습니다. 관리자 인증·서버 경로·접근 권한을 확인하세요.'
                done(None, message)
        connection.call(NAME, OBJECT, NAME, 'Mount', GLib.Variant('(ss)', (uri, token)),
                        GLib.VariantType.new('(s)'), Gio.DBusCallFlags.NONE, 145000, None, mounted)
    Gio.bus_get(Gio.BusType.SYSTEM, None, got_bus)
    return state


def cancel_request(state):
    state['cancelled'] = True
    if state['connection'] is not None:
        cancel(state['connection'], state['token'])
