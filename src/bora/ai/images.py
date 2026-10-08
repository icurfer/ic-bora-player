"""메모의 로컬 이미지 첨부. 네트워크 링크나 메모 폴더 밖 파일은 읽지 않는다."""
import base64
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_IMAGES = 4
MAX_BYTES = 20 * 1024 * 1024


class ImageError(ValueError):
    pass


def _destinations(text):
    text = re.sub(r'```.*?```|~~~.*?~~~|`[^`\n]*`', '', text, flags=re.S)
    for match in re.finditer(r'!\[[^\n]*?\]\(', text):
        start = match.end()
        depth, escape = 1, False
        for i in range(start, len(text)):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if not depth:
                    raw = text[start:i].strip()
                    if raw.startswith('<') and '>' in raw:
                        raw = raw[1:raw.index('>')]
                    else:
                        raw = re.sub(r'\s+[\"\'][^\"\']*[\"\']$', '', raw)
                    yield re.sub(r'\\([()\\ ])', r'\1', raw)
                    break
        else:
            raise ImageError('메모 이미지 링크가 닫히지 않았습니다. 링크를 수정하거나 이미지 첨부를 해제하세요.')


def _checked_path(path, root):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(root).resolve()):
        raise ImageError('메모 폴더 밖 이미지는 첨부할 수 없습니다. 이미지를 메모 폴더로 옮겨 주세요.')
    if not resolved.is_file():
        raise ImageError('메모 이미지 파일을 찾지 못했습니다. 링크를 수정하거나 이미지 첨부를 해제하세요.')
    return resolved


def find_images(text, note_path):
    """UI에서는 경로/크기만 검사한다. 이미지 데이터는 worker에서 읽는다."""
    destinations = list(_destinations(text))
    if not destinations:
        return []
    if note_path is None:
        raise ImageError('메모 파일 위치를 확인할 수 없습니다.')
    root = Path(note_path).parent
    result, size = [], 0
    try:
        for raw in destinations:
            parsed = urlsplit(raw)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ImageError('외부 이미지 링크는 전송하지 않습니다. 로컬 이미지로 바꾸거나 이미지 첨부를 해제하세요.')
            candidate = Path(unquote(raw))
            if candidate.is_absolute():
                candidate = _checked_path(candidate, root)
            else:
                candidate = _checked_path(root / candidate, root)
            if candidate in result:
                continue
            if candidate.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ImageError('이미지는 PNG·JPEG·WEBP만 첨부할 수 있습니다.')
            size += candidate.stat().st_size
            result.append(candidate)
            if len(result) > MAX_IMAGES or size > MAX_BYTES:
                raise ImageError('이미지는 최대 4장·합계 20MB입니다. 메모의 이미지 수를 줄이거나 첨부를 해제하세요.')
    except ImageError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise ImageError('메모 이미지 파일을 읽을 수 없습니다. 파일 접근 권한을 확인하세요.') from None
    return result


def load_images(paths, note_path):
    if not paths:
        return []
    if note_path is None or len(paths) > MAX_IMAGES:
        raise ImageError('이미지 첨부 개수나 메모 위치를 확인하세요.')
    result, total = [], 0
    try:
        for path in paths:
            safe = _checked_path(path, Path(note_path).parent)
            with safe.open('rb') as f:
                data = f.read(MAX_BYTES - total + 1)
            total += len(data)
            if total > MAX_BYTES:
                raise ImageError('이미지 크기가 20MB를 넘었습니다. 이미지 첨부를 줄여 주세요.')
            if data.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            elif data.startswith(b'\xff\xd8\xff'):
                mime = 'image/jpeg'
            elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                mime = 'image/webp'
            else:
                raise ImageError('이미지 파일 형식을 확인하지 못했습니다. PNG·JPEG·WEBP 파일로 바꿔 주세요.')
            result.append((safe.name, mime, data))
    except ImageError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise ImageError('이미지를 읽지 못했습니다. 파일을 확인하거나 이미지 첨부를 해제하세요.') from None
    return result


def api_input(text, attachments):
    if not attachments:
        return text
    content = [{'type': 'input_text', 'text': text}]
    for name, mime, data in attachments:
        content.extend([{'type': 'input_text', 'text': '첨부 이미지: ' + name},
                        {'type': 'input_image', 'image_url': 'data:' + mime + ';base64,' +
                         base64.b64encode(data).decode('ascii')}])
    return [{'role': 'user', 'content': content}]


def codex_input(text, attachments, directory):
    content = [{'type': 'text', 'text': text}]
    for index, (name, mime, data) in enumerate(attachments):
        suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}[mime]
        target = Path(directory) / ('attachment-' + str(index) + suffix)
        target.write_bytes(data)
        content.extend([{'type': 'text', 'text': '첨부 이미지: ' + name},
                        {'type': 'localImage', 'path': str(target)}])
    return content
