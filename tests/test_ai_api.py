"""BYOK는 모의 통신/저장소로만 검사하고 사용자 키를 읽지 않는다."""
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from bora.ai import api
from bora.ai.context import Question


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(api.paths, 'config_dir', lambda: tmp_path)
    return tmp_path


def test_default_and_roundtrip_no_secret(config):
    assert api.load_config()['provider'] == 'codex'
    api.save_config('openai', 'gpt-4.1-mini')
    raw = json.loads((config / 'ai.json').read_text())
    assert raw == {'provider': 'openai', 'model': 'gpt-4.1-mini'}
    assert api.load_config() == raw


def test_corrupt_config_does_not_silently_switch(config):
    (config / 'ai.json').write_text('[]')
    with pytest.raises(api.AIError):
        api.load_config()


def test_failed_save_preserves_previous(config):
    api.save_config('codex', api.DEFAULT_MODEL)
    with patch.object(api.os, 'replace', side_effect=OSError):
        with pytest.raises(api.AIError):
            api.save_config('openai', api.DEFAULT_MODEL)
    assert api.load_config()['provider'] == 'codex'
    assert len(list(config.iterdir())) == 1


def test_secret_storage_failure_no_plaintext_fallback(config):
    with patch.object(api.credentials, 'write', side_effect=RuntimeError('sensitive body')):
        with pytest.raises(api.AIError) as exc:
            api.set_key('test-value')
    assert 'sensitive' not in str(exc.value)
    assert not list(config.iterdir())


def test_model_check_get_only():
    with patch.object(api, '_open', return_value=io.BytesIO(b'{"id":"gpt-4.1-mini"}')) as request:
        assert '실제 질문은 보내지 않았습니다' in api.check_api('test-value', 'gpt-4.1-mini')
    assert request.call_args.args == ('test-value', 'models/gpt-4.1-mini')


@pytest.mark.parametrize('code', [401, 403, 404, 429, 500])
def test_http_errors_hide_server_body(code):
    error = HTTPError('https://api.openai.com', code, 'private', {}, io.BytesIO(b'secret-value'))
    with patch.object(api, 'build_opener') as opener:
        opener.return_value.open.side_effect = error
        with pytest.raises(api.AIError) as exc:
            api._open('test-value', 'models/x')
    assert 'secret-value' not in str(exc.value) and 'private' not in str(exc.value)


def event(kind, **rest):
    return ('data: ' + json.dumps({'type': kind, **rest}) + '\n\n').encode()


def run_stream(payload, config=None):
    deltas, done, errors = [], [], []
    runner = api.APIAskRunner(deltas.append, lambda *a: done.append(a), errors.append,
                              config=config or {'provider': 'openai', 'model': 'gpt-4.1-mini'})
    with patch.object(api, 'get_key', return_value='test-value'), patch.object(api, '_open', return_value=io.BytesIO(payload)) as request:
        runner._pump(Question('질문', note_text='메모'))
    return runner, deltas, done, errors, request


def test_stream_context_model_and_completion():
    _, deltas, done, errors, request = run_stream(event('response.output_text.delta', delta='답변') + event('response.completed', response={'usage': {'input_tokens': 10}}))
    assert deltas == ['답변'] and len(done) == 1 and not errors
    body = request.call_args.args[2]
    assert body['model'] == 'gpt-4.1-mini' and body['stream'] and not body['store']
    assert '질문' in body['input'] and '메모' in body['input']


@pytest.mark.parametrize('ending', [b'', event('response.incomplete'), b'data: invalid\n'])
def test_partial_never_reported_complete(ending):
    _, deltas, done, errors, _ = run_stream(event('response.output_text.delta', delta='일부') + ending)
    assert deltas == ['일부'] and not done and errors


def test_cancel_suppresses_callbacks_and_request():
    runner = api.APIAskRunner(on_delta=lambda *_: pytest.fail(), on_error=lambda *_: pytest.fail(), config={'model': 'gpt-4.1-mini'})
    runner.cancel()
    with patch.object(api, 'get_key', return_value='test-value'), patch.object(api, '_open') as request:
        runner._pump(Question('질문'))
    request.assert_not_called()


def test_no_redirect_of_authorization():
    with pytest.raises(api.AIError):
        api._NoRedirect().redirect_request(None)
