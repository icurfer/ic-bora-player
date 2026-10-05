"""로컬 Codex app-server 연결. ChatGPT 로그인만 사용하며 API로 전환하지 않는다."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from .context import Question, build, to_request

MODELS = ()  # 모델은 사용자의 Codex 설정을 따른다.
DEFAULT_MODEL = ''


def codex_command():
    found = shutil.which('codex')
    if found:
        return found
    local = Path.home() / '.local/bin/codex'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


def sdk_installed():
    return codex_command() is not None


def ensure_ready():
    if not codex_command():
        return False, 'Codex가 설치되지 않았습니다. 메뉴 → Codex 연결에서 설치 안내를 확인하세요.'
    return True, '로컬 Codex 준비됨'


def worker_env():
    # 기존 로그인은 Codex가 직접 읽는다. API 키·세션 주입으로 과금 경로가 바뀌지 않게 한다.
    return {k: v for k, v in os.environ.items()
            if not k.startswith(('OPENAI_', 'ANTHROPIC_', 'CODEX_')) or k == 'CODEX_HOME'}


class CodexError(RuntimeError):
    pass


class Session:
    def __init__(self, cancelled=None):
        self.cancelled = cancelled or threading.Event()
        self.proc = None
        self.events = queue.Queue()
        self.next_id = 0
        self.pending = []
        self._write_lock = threading.Lock()

    def __enter__(self):
        command = codex_command()
        if not command:
            raise CodexError(ensure_ready()[1])
        self.work = tempfile.TemporaryDirectory(prefix='bora-codex-')
        args = [command, 'app-server', '--listen', 'stdio://']
        overrides = {
            'model_provider': 'openai', 'forced_login_method': 'chatgpt',
            'approval_policy': 'never', 'sandbox_mode': 'read-only',
            'web_search': 'disabled', 'mcp_servers': {}, 'plugins': {},
            'features.apps': False, 'features.hooks': False,
            'features.multi_agent': False, 'features.shell_tool': False,
            'features.code_mode_host': False,
        }
        for key, value in overrides.items():
            # JSON scalar syntax is TOML-compatible. Empty tables are TOML inline tables.
            args.extend(['-c', f'{key}={json.dumps(value)}'])
        try:
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, env=worker_env(),
                                         cwd=self.work.name)
            threading.Thread(target=self._read, daemon=True).start()
            self.rpc('initialize', {'clientInfo': {'name': 'bora', 'title': 'Bora', 'version': '0.26.3'}})
            self.send({'method': 'initialized'})
            return self
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.proc.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self.events.put(value)
                except ValueError:
                    continue
        finally:
            self.events.put(None)

    def send(self, value):
        with self._write_lock:
            self.proc.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.proc.stdin.flush()

    def receive(self, deadline):
        while not self.cancelled.is_set():
            if time.monotonic() >= deadline:
                raise CodexError('Codex 응답을 기다리는 시간이 길어졌습니다. 연결을 확인하고 다시 시도하세요.')
            try:
                event = self.events.get(timeout=.2)
            except queue.Empty:
                continue
            if event is None:
                raise CodexError('Codex 연결이 종료됐습니다. 연결 상태를 확인해 주세요.')
            if 'method' in event and 'id' in event:
                # 학습 대화에서 파일 변경·외부 도구 승인을 자동으로 허용하지 않는다.
                self.send({'id': event['id'], 'error': {'code': -32601, 'message': 'Bora supports conversation only'}})
                continue
            return event
        raise CodexError('대화를 중지했습니다.')

    def rpc(self, method, params=None, timeout=25):
        self.next_id += 1
        request_id = self.next_id
        self.send({'id': request_id, 'method': method, 'params': params or {}})
        deadline = time.monotonic() + timeout
        while True:
            event = self.receive(deadline)
            if event.get('id') == request_id:
                if 'error' in event:
                    raise CodexError('Codex 요청에 실패했습니다. 로그인 또는 Codex 버전을 확인해 주세요.')
                return event.get('result') or {}
            self.pending.append(event)

    def require_chatgpt(self):
        account = self.rpc('account/read', {'refreshToken': True}).get('account') or {}
        if account.get('type') != 'chatgpt':
            raise CodexError('ChatGPT 로그인이 필요합니다. 메뉴 → Codex 연결에서 다시 로그인하세요. API 키는 사용하지 않습니다.')

    def close(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            for pipe in (self.proc.stdin, self.proc.stdout):
                if pipe:
                    pipe.close()
        if hasattr(self, 'work'):
            self.work.cleanup()

    def __exit__(self, *_):
        self.close()


def check_connection():
    try:
        with Session() as session:
            session.require_chatgpt()
        return 'ChatGPT 로그인 확인됨 · 구독 사용 한도 적용 · API 자동 전환 없음'
    except CodexError as exc:
        return str(exc)
    except Exception:
        return 'Codex에 연결하지 못했습니다. 설치 상태와 네트워크를 확인하세요.'


class AskRunner:
    def __init__(self, on_delta=None, on_done=None, on_error=None):
        self.on_delta, self.on_done, self.on_error = on_delta, on_done, on_error
        self._thread = None
        self._cancelled = threading.Event()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancelled.set()

    def ask(self, question):
        if self.running:
            return False
        ready, message = ensure_ready()
        if not ready:
            if self.on_error:
                self.on_error(message)
            return False
        self._cancelled.clear()
        self._thread = threading.Thread(target=self._pump, args=(question,), daemon=True)
        self._thread.start()
        return True

    def _pump(self, question):
        try:
            with Session(self._cancelled) as session:
                session.require_chatgpt()
                request = to_request(build(question))
                thread = session.rpc('thread/start', {
                    'cwd': session.work.name, 'ephemeral': True,
                    'approvalPolicy': 'never', 'sandbox': 'read-only',
                    'baseInstructions': request['instructions'],
                    'developerInstructions': '제공된 학습 자료로 대화만 한다. 도구 실행, 파일 읽기나 수정, 웹 검색을 하지 않는다.',
                })['thread']['id']
                result = session.rpc('turn/start', {'threadId': thread, 'input': [
                    {'type': 'text', 'text': request['input']}], 'serviceTierForTurn': 'default'})
                turn = result['turn']['id']
                deadline = time.monotonic() + 180
                text_seen = {}
                while True:
                    event = session.pending.pop(0) if session.pending else session.receive(deadline)
                    method, params = event.get('method'), event.get('params') or {}
                    if params.get('threadId') != thread or params.get('turnId', turn) != turn:
                        continue
                    if method == 'item/agentMessage/delta':
                        item = params.get('itemId', '')
                        delta = params.get('delta', '')
                        text_seen[item] = text_seen.get(item, '') + delta
                        if self.on_delta:
                            self.on_delta(delta)
                    elif method == 'item/completed':
                        item = params.get('item') or {}
                        if item.get('type') == 'agentMessage' and item.get('id') not in text_seen:
                            text_seen[item.get('id')] = item.get('text', '')
                            if self.on_delta:
                                self.on_delta(item.get('text', ''))
                    elif method == 'turn/completed':
                        if (params.get('turn') or {}).get('status') != 'completed':
                            raise CodexError('Codex가 답변을 완료하지 못했습니다. 로그인·사용 한도·연결 상태를 확인하세요.')
                        if not any(text_seen.values()):
                            raise CodexError('Codex가 답변을 보내지 않았습니다. 다시 질문해 주세요.')
                        if self.on_done:
                            self.on_done(None, {})
                        return
        except CodexError as exc:
            if not self._cancelled.is_set() and self.on_error:
                self.on_error(str(exc))
        except Exception:
            if not self._cancelled.is_set() and self.on_error:
                self.on_error('Codex 연결에 실패했습니다. 메뉴 → Codex 연결에서 확인하세요.')
