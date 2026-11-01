"""비밀번호 없는 서버 즐겨찾기. 통신은 플랫폼 어댑터에 위임한다."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit, quote, unquote

PROTOCOLS = ('smb', 'sftp', 'nfs')


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
        raise ValueError('smb://서버/공유, sftp://사용자@서버:포트/폴더 또는 nfs://서버/내보낸경로 형식으로 입력하세요. 비밀번호는 주소에 넣지 마세요.') from None


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
