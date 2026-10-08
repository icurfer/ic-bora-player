"""메모 폴더를 선택한 로컬 CLI의 작업 경로로 연다."""
import json
import os
import shutil
from pathlib import Path
from ..platform import integration
from .client import codex_command, worker_env


PROVIDERS = {"codex": "Codex", "claude": "Claude Code"}


def terminal_command(provider):
    if provider == 'codex':
        return codex_command()
    if provider != 'claude':
        raise ValueError('알 수 없는 터미널 도구입니다.')
    command = shutil.which('claude')
    local = Path.home() / '.local/bin/claude'
    return command or (str(local) if local.is_file() and os.access(local, os.X_OK) else None)


def launch(video, note, subtitle=None, question=None, provider='codex'):
    command = terminal_command(provider)
    if not command:
        raise OSError(f'{PROVIDERS[provider]}가 설치되지 않았습니다. 메모 상단 도구 메뉴의 설치 안내를 확인하세요.')
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
    if provider == 'codex':
        argv = [command, '--cd', str(note.parent), '--sandbox', 'workspace-write',
                '--ask-for-approval', 'on-request', '-c', 'forced_login_method="chatgpt"',
                '-c', 'model_provider="openai"', prompt]
    else:
        # 원본 대화형 CLI가 로그인·승인을 처리한다. headless/API로 중계하지 않는다.
        argv = [command, '--permission-mode', 'manual', '--settings',
                json.dumps({'forceLoginMethod': 'claudeai'}), prompt]
    env = worker_env()
    for key in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX',
                'CLAUDE_CODE_USE_FOUNDRY', 'CLAUDE_CODE_OAUTH_TOKEN'):
        env.pop(key, None)
    integration.launch_terminal(argv, note.parent, env)
