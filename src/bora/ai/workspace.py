"""메모 폴더를 로컬 Codex의 작업 경로로 연다."""
import json
from pathlib import Path
from ..platform import integration
from .client import codex_command, worker_env


def launch(video, note, subtitle=None, question=None):
    command = codex_command()
    if not command:
        raise OSError('Codex가 설치되지 않았습니다.')
    note = Path(note).resolve()
    if not note.is_file():
        raise OSError('메모가 저장되지 않았습니다.')
    context = {'메모': str(note), '영상': str(Path(video).resolve())}
    if subtitle:
        context['자막'] = str(Path(subtitle).resolve())
    prompt = ('보라 영상 플레이어에서 이어지는 학습 작업입니다. 아래 파일을 맥락으로 사용하세요. '
              '메모를 먼저 읽고 사용자의 요청에 따라 편집하세요. 영상 원본은 수정하지 마세요. '
              '메모를 수정하기 직전에 파일을 다시 읽어 다른 편집기의 변경을 보존하세요.\n'
              + json.dumps(context, ensure_ascii=False) + '\n'
              + (f'사용자 요청: {question}' if question else '메모를 읽고 다음 요청을 기다려 주세요.'))
    argv = [command, '--cd', str(note.parent), '--sandbox', 'workspace-write',
            '--ask-for-approval', 'on-request', '-c', 'forced_login_method="chatgpt"',
            '-c', 'model_provider="openai"', prompt]
    integration.launch_terminal(argv, note.parent, worker_env())
