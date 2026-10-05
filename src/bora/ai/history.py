"""영상별 Codex 대화. 사용자 메모와 분리하여 원자적으로 저장한다."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ..platform import paths


class Conversation:
    def __init__(self, video, directory=None):
        identity = str(Path(video).resolve())
        self.path = (Path(directory) if directory else paths.data_dir() / 'conversations') / (
            hashlib.sha256(identity.encode()).hexdigest() + '.json')
        self.messages = []
        self._original = self.path.read_bytes() if self.path.exists() else None
        if self._original is not None:
            try:
                raw = json.loads(self._original)
                if not isinstance(raw, list) or any(
                    not isinstance(m, dict) or m.get('role') not in ('user', 'assistant')
                    or not isinstance(m.get('content'), str) for m in raw
                ):
                    raise ValueError()
                for message in raw:
                    stamp = message.get('timestamp', 0)
                    if not isinstance(stamp, (float, int)) or not 0 <= stamp < 1e12:
                        message['timestamp'] = 0
                    if message.get('status', 'completed') not in ('completed', 'interrupted', 'error'):
                        message['status'] = 'interrupted'
                self.messages = raw
            except (ValueError, TypeError):
                raise OSError('대화 기록을 읽지 못했습니다. 기존 파일을 보존했습니다.') from None

    def save(self):
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self._original:
            raise OSError('다른 창에서 대화 기록이 바뀌었습니다. 기존 파일을 보존했습니다.')
        content = json.dumps(self.messages, ensure_ascii=False, indent=2).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.conversation-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            os.replace(name, self.path)
            self._original = content
        finally:
            if os.path.exists(name):
                os.unlink(name)
