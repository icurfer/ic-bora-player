import base64
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from bora.ai import api, client
from bora.ai.context import Question
from bora.ai.images import ImageError, find_images, load_images, api_input, codex_input

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1sAAAAASUVORK5CYII=')


@pytest.fixture
def note(tmp_path):
    assets = tmp_path / '강의(1).assets'
    assets.mkdir()
    (assets / '그림 1.png').write_bytes(PNG)
    return tmp_path / '강의(1).md'


def test_generated_markdown_nested_stamp_and_parentheses(note):
    text = '질문\n![[00:00:40]](강의(1).assets/그림 1.png)'
    found = find_images(text, note)
    assert found == [note.parent / '강의(1).assets/그림 1.png']
    assert load_images(found, note) == [('그림 1.png', 'image/png', PNG)]


def test_encoded_and_angle_and_duplicate_links(note):
    text = '![a](<강의(1).assets/그림 1.png>)\n![b](강의%281%29.assets/그림%201.png "title")'
    assert len(find_images(text, note)) == 1


def test_ignore_code_example(note):
    assert find_images('```\n![x](missing.png)\n```\n`![x](missing.png)`', note) == []


@pytest.mark.parametrize('link', ['https://example.com/a.png', '../outside.png', 'missing.png'])
def test_bad_references_are_not_silently_dropped(note, link):
    with pytest.raises(ImageError):
        find_images('![image](' + link + ')', note)


def test_symlink_escape(note, tmp_path):
    target = tmp_path.parent / (tmp_path.name + '-outside.png')
    target.write_bytes(PNG)
    try:
        try:
            (tmp_path / 'link.png').symlink_to(target)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                pytest.skip('Windows 파일 symlink 권한 필요')
            raise
        with pytest.raises(ImageError):
            find_images('![image](link.png)', note)
    finally:
        target.unlink()


def test_too_many_and_total_size(note):
    text = ''
    for i in range(5):
        (note.parent / f'{i}.png').write_bytes(PNG)
        text += f'![{i}]({i}.png)\n'
    with pytest.raises(ImageError, match='4장'):
        find_images(text, note)
    with patch('bora.ai.images.MAX_BYTES', 1):
        with pytest.raises(ImageError):
            find_images('![0](0.png)', note)


def test_invalid_bytes_and_removed_file(note):
    path = note.parent / 'bad.png'
    path.write_bytes(b'not an image')
    with pytest.raises(ImageError):
        load_images([path], note)
    path.unlink()
    with pytest.raises(ImageError):
        load_images([path], note)


def test_provider_content_contains_real_bytes(note, tmp_path):
    attachments = [('그림.png', 'image/png', PNG)]
    content = api_input('질문', attachments)[0]['content']
    assert base64.b64decode(content[2]['image_url'].split(',', 1)[1]) == PNG
    local = codex_input('질문', attachments, tmp_path)[2]
    assert local['type'] == 'localImage' and Path(local['path']).read_bytes() == PNG
    assert api_input('질문', []) == '질문'
    assert codex_input('질문', [], tmp_path) == [{'type': 'text', 'text': '질문'}]


def test_api_runner_image_body(note):
    image = note.parent / '강의(1).assets/그림 1.png'
    stream = b'data: {"type":"response.output_text.delta","delta":"image answer"}\n\ndata: {"type":"response.completed"}\n\n'
    errors = []
    runner = api.APIAskRunner(on_error=errors.append, config={'model': 'gpt-4.1-mini'})
    with patch.object(api, 'get_key', return_value='test-placeholder'), patch.object(api, '_open', return_value=io.BytesIO(stream)) as request:
        runner._pump(Question('이미지 질문', note_path=note, image_paths=[image]))
    assert not errors
    assert request.call_args.args[2]['input'][0]['content'][2]['type'] == 'input_image'


def test_codex_runner_image_and_temporary_cleanup(note):
    image = note.parent / '강의(1).assets/그림 1.png'
    class Session:
        def __init__(self, *args):
            import tempfile
            self.work = tempfile.TemporaryDirectory()
            self.pending = [
                {'method': 'item/agentMessage/delta', 'params': {'threadId': 't', 'turnId': 'r', 'delta': '답변'}},
                {'method': 'turn/completed', 'params': {'threadId': 't', 'turnId': 'r', 'turn': {'status': 'completed'}}}]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.work.cleanup()
        def require_chatgpt(self):
            pass
        def rpc(self, method, params):
            if method == 'thread/start':
                return {'thread': {'id': 't'}}
            local = params['input'][2]
            assert local['type'] == 'localImage'
            assert Path(local['path']).read_bytes() == PNG
            copied.append(Path(local['path']))
            return {'turn': {'id': 'r'}}
    errors, done, copied = [], [], []
    runner = client.AskRunner(on_error=errors.append, on_done=lambda *a: done.append(a))
    with patch.object(client, 'Session', Session):
        runner._pump(Question('이미지 질문', note_path=note, image_paths=[image]))
    assert not errors and done and copied and not copied[0].exists()
