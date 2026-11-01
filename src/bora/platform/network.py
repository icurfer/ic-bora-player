"""원격 파일 어댑터 선택. 플랫폼 분기는 이 폴더에 둔다."""
from . import IS_LINUX

if IS_LINUX:
    from .linux.network import Browser, Session, available, local_path, reason
else:
    def available():
        return False

    def reason():
        return '네트워크 서버 연결은 현재 Linux에서만 제공됩니다.'

    def local_path(file):
        raise ValueError(reason())

    class Browser:
        def __init__(self, parent, session=None):
            pass

        def stop(self):
            pass

        def browse(self, uri, done):
            done(None, reason())

if not IS_LINUX:
    class Session:
        def close(self, callback):
            callback([])
