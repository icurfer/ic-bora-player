"""비밀번호 없는 서버 즐겨찾기. 통신은 플랫폼 어댑터에 위임한다."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit, quote, unquote

PROTOCOLS = ('smb', 'sftp', 'ftp', 'nfs')
_remote_roots = {}
_remote_files = {}


def remember_remote(path, uri, *, root=False):
    """프로세스 안에서만 임시 파일 경로를 비밀번호 없는 원격 주소에 대응시킨다."""
    uri = server_uri(uri)
    (_remote_roots if root else _remote_files)[Path(path).resolve()] = uri


def remote_uri(path):
    path = Path(path).resolve()
    if path in _remote_files:
        return _remote_files[path]
    for root in sorted(_remote_roots, key=lambda p: len(p.parts), reverse=True):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return _remote_roots[root].rstrip('/') + ('/' + quote(relative.as_posix(), safe='/')
                                                 if relative.parts else '')
    return None


def media_identity(path):
    return remote_uri(path) or str(Path(path).resolve())


def relative_media(connection, media):
    """같은 계정/서버의 연결 폴더 안에 있는 파일만 상대 경로로 돌려준다."""
    base, target = urlsplit(server_uri(connection)), urlsplit(server_uri(media))
    prefix = base.path.rstrip('/') + '/'
    if ((base.scheme, base.netloc) != (target.scheme, target.netloc)
            or not target.path.startswith(prefix)):
        raise ValueError('최근 파일 주소가 연결 폴더와 일치하지 않습니다.')
    relative = unquote(target.path[len(prefix):])
    if (not relative or '\\' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('최근 파일 경로를 확인할 수 없습니다.')
    return relative


def remote_location(path):
    """마운트 임시 경로 대신 파일 주소와 재접속 기준 폴더를 보관한다."""
    uri = remote_uri(path)
    if uri is None:
        return '', ''
    path = Path(path).resolve()
    for root in sorted(_remote_roots, key=lambda p: len(p.parts), reverse=True):
        if path.is_relative_to(root):
            connection = _remote_roots[root]
            try:
                relative_media(connection, uri)
                return uri, connection
            except ValueError:
                continue
    parsed = urlsplit(uri)
    if parsed.scheme == 'nfs':
        return uri, ''  # 내보내기 루트는 파일 주소만으로 추정하지 않는다.
    parent = parsed.path.rsplit('/', 1)[0] or '/'
    return uri, urlunsplit((parsed.scheme, parsed.netloc, parent, '', ''))


def server_uri(value):
    try:
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise ValueError
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in PROTOCOLS or not parsed.hostname or parsed.password is not None
                or parsed.query or parsed.fragment or '\\' in value):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        if (':' in unquote(parsed.username or '') or '@' in unquote(parsed.hostname)
                or any(c.isspace() for c in unquote(parsed.hostname))):
            raise ValueError
        if parsed.scheme == 'nfs' and parsed.username is not None:
            raise ValueError
        path = unquote(parsed.path)
        if any(ord(c) < 32 for c in path):
            raise ValueError
        return urlunsplit((parsed.scheme, parsed.netloc, quote(path or '/', safe='/'), '', ''))
    except ValueError:
        raise ValueError('smb://서버/공유, sftp://사용자@서버:포트/폴더 ftp://사용자@서버/폴더 또는 nfs://서버/내보낸경로 형식으로 입력하세요. 비밀번호는 주소에 넣지 마세요.') from None


@dataclass(frozen=True)
class Server:
    name: str
    uri: str


class ServerStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'network-servers.json'

    def load(self):
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, list) or len(raw) > 100:
                raise ValueError
            return [Server(str(s['name'])[:120], server_uri(s['uri'])) for s in raw]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError('서버 목록을 읽지 못했습니다. 기존 파일을 보존했습니다.') from None

    def save(self, servers):
        raw = [{'name': s.name.strip()[:120], 'uri': server_uri(s.uri)} for s in servers]
        if len(raw) > 100:
            raise ValueError('서버는 최대 100개까지 저장할 수 있습니다.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.network-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(raw, stream, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
