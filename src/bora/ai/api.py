"""명시적으로 선택한 OpenAI BYOK 연결. Codex로 자동 전환하지 않는다."""
import json
import os
import re
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..platform import paths, credentials
from .context import build, to_request

DEFAULT_MODEL = 'gpt-4.1-mini'


class AIError(Exception):
    pass


def load_config():
    try:
        raw = json.loads((paths.config_dir() / 'ai.json').read_text())
        if not isinstance(raw, dict) or raw.get('provider') not in ('codex', 'openai'):
            raise ValueError()
        validate_model(raw.get('model', ''))
        return {'provider': raw['provider'], 'model': raw['model']}
    except FileNotFoundError:
        return {'provider': 'codex', 'model': DEFAULT_MODEL}
    except (OSError, ValueError, TypeError, AIError):
        raise AIError('AI 설정을 읽지 못했습니다. AI 연결에서 방식을 다시 적용하세요.') from None


def validate_model(model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,150}', model):
        raise AIError('모델 이름을 확인하세요. 영문·숫자·마침표·하이픈을 사용할 수 있습니다.')


def save_config(provider, model):
    if provider not in ('codex', 'openai'):
        raise AIError('사용 방식을 선택하세요.')
    validate_model(model)
    directory = paths.config_dir()
    temp = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as f:
            temp = f.name
            json.dump({'provider': provider, 'model': model}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, directory / 'ai.json')
    except OSError:
        raise AIError('AI 설정을 저장하지 못했습니다. 설정 폴더 권한을 확인하세요.') from None
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def _credential(action, *args):
    try:
        return action(*args)
    except Exception:
        raise AIError('OS 보안 저장소에 접근하지 못했습니다. 키 저장소 잠금을 해제한 뒤 다시 시도하세요.') from None


def get_key():
    return _credential(credentials.read)


def set_key(value):
    _validate_key(value)
    _credential(credentials.write, value.strip())


def delete_key():
    _credential(credentials.delete)


def _validate_key(key):
    if not key or any(c.isspace() for c in key.strip()) or not key.strip().isascii():
        raise AIError('OpenAI API 키를 입력하세요. 공백이나 줄바꿈 없이 붙여 넣어 주세요.')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AIError('API 연결 주소가 변경되었습니다. 연결을 중단했습니다.')


def _open(key, endpoint, body=None):
    _validate_key(key)
    request = Request('https://api.openai.com/v1/' + endpoint,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + key.strip(),
                               'Content-Type': 'application/json'})
    try:
        return build_opener(_NoRedirect()).open(request, timeout=30)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        hints = {401: 'API 키 인증에 실패했습니다. 키를 확인하거나 새 키를 입력하세요.',
                 403: 'API 접근 권한이 없습니다. 프로젝트와 모델 권한을 확인하세요.',
                 404: '모델을 찾지 못했습니다. 사용 가능한 모델 이름을 입력하세요.',
                 429: 'API 사용 한도 또는 잔액을 확인하고 잠시 후 다시 시도하세요.'}
        raise AIError(hints.get(code, 'OpenAI API 요청에 실패했습니다. 모델 설정과 서비스 상태를 확인하세요.')) from None
    except (URLError, OSError):
        raise AIError('OpenAI API에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.') from None


def check_api(key, model):
    validate_model(model)
    with _open(key, 'models/' + quote(model, safe='')) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get('id') != model:
        raise AIError('모델 조회 결과를 확인하지 못했습니다. 모델 이름을 확인하세요.')
    return 'API 인증·모델 조회 확인 완료 · 실제 질문은 보내지 않았습니다.'


class APIAskRunner:
    def __init__(self, on_delta=None, on_done=None, on_error=None, config=None):
        self.on_delta, self.on_done, self.on_error = on_delta, on_done, on_error
        self.config = dict(config or load_config())
        self._thread = None
        self._cancelled = threading.Event()
        self._response = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancelled.set()
        # socket close can block; keep playback and editing responsive.
        response = self._response
        if response is not None:
            threading.Thread(target=response.close, daemon=True).start()

    def ask(self, question):
        if self.running:
            return False
        self._cancelled.clear()
        self._thread = threading.Thread(target=self._pump, args=(question,), daemon=True)
        self._thread.start()
        return True

    def _pump(self, question):
        try:
            key = get_key()
            _validate_key(key)
            if self._cancelled.is_set():
                return
            body = to_request(build(question))
            body.update(model=self.config['model'], stream=True, store=False, max_output_tokens=4096)
            with _open(key, 'responses', body) as response:
                self._response = response
                seen = False
                for line in response:
                    if self._cancelled.is_set():
                        return
                    if not line.startswith(b'data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == b'[DONE]':
                        break
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind in ('response.output_text.delta', 'response.refusal.delta'):
                        delta = event.get('delta', '')
                        seen = seen or bool(delta)
                        if self.on_delta:
                            self.on_delta(delta)
                    elif kind == 'response.completed':
                        if not seen:
                            raise AIError('API가 답변을 보내지 않았습니다. 다시 질문하세요.')
                        if self.on_done:
                            self.on_done(None, (event.get('response') or {}).get('usage', {}))
                        return
                    elif kind in ('error', 'response.failed', 'response.incomplete'):
                        raise AIError('API가 답변을 완료하지 못했습니다. 사용 한도와 모델을 확인하고 다시 질문하세요.')
                raise AIError('API 연결이 답변 완료 전에 끊겼습니다. 다시 질문하세요.')
        except Exception as exc:
            if not self._cancelled.is_set() and self.on_error:
                self.on_error(str(exc) if isinstance(exc, AIError) else
                              'API 응답을 처리하지 못했습니다. 연결과 모델 설정을 확인하세요.')
        finally:
            self._response = None
