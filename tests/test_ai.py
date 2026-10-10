"""로컬 Codex의 맥락·인증·스트리밍·취소 계약. 실제 서비스를 호출하지 않는다."""
import json
import os
import time
import sys
import subprocess
from pathlib import Path

import pytest
from bora.ai import Question, build, to_request
from bora.ai import client
from bora.ai.context import SYSTEM
from bora.ai.history import Conversation
from bora.ai.workspace import launch


def test_context_limits_and_conversation():
    q = Question(text='이번 질문', video_title='강의', position=65,
                 history=[{'role':'user','content':f'과거{i}'} for i in range(30)],
                 note_text='메모내용')
    request = to_request(build(q))
    assert request['instructions'] == SYSTEM
    assert '과거0"' not in request['input'] and '과거29' in request['input']
    assert '메모내용' in request['input'] and '이번 질문' in request['input']
    assert '00:01:05' in request['input']


def test_subtitle_window_and_no_full_video(tmp_path):
    sub=tmp_path/'lecture.srt'
    sub.write_text('1\n00:00:01,000 --> 00:00:02,000\n가까운 자막\n\n2\n01:00:00,000 --> 01:00:10,000\n먼 자막\n')
    q=build(Question(text='질문',position=10,subtitle_path=sub))
    assert '가까운 자막' in q.nearby_subtitle and '먼 자막' not in q.nearby_subtitle
    assert not q.full_subtitle
    assert '질문' in to_request(build(Question(text='질문',subtitle_path=tmp_path/'missing')))['input']


def test_context_budget():
    q=Question(text='질문',history=[{'role':'user','content':'x'*25000}],note_text='n'*20000)
    assert len(to_request(build(q))['input']) < 10000


def test_missing_cli(monkeypatch):
    monkeypatch.setattr(client,'codex_command',lambda:None)
    errors=[]
    assert not client.AskRunner(on_error=errors.append).ask(Question(text='질문'))
    assert '설치' in errors[0]


def test_no_api_environment(monkeypatch):
    for key in ('OPENAI_API_KEY','OPENAI_BASE_URL','CODEX_API_KEY','ANTHROPIC_API_KEY','CODEX_THREAD_ID'):
        monkeypatch.setenv(key,'test-value')
        assert key not in client.worker_env()
    monkeypatch.setenv('CODEX_HOME','/tmp/codex-test')
    assert client.worker_env()['CODEX_HOME']=='/tmp/codex-test'


@pytest.fixture
def fake_server(tmp_path,monkeypatch):
    script=tmp_path/'codex'
    script.write_text('''#!/usr/bin/python3
import json,os,sys,time
mode=os.environ.get('BORA_TEST_MODE','success')
def send(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 with open(os.environ['BORA_TEST_TRACE'],'a') as f:f.write(json.dumps(r)+'\\n')
 m=r.get('method')
 if m=='initialized':continue
 result={}
 if m=='account/read':result={'account':{'type':'apiKey' if mode=='api' else 'chatgpt'}}
 if m=='thread/start':result={'thread':{'id':'thread-test'}}
 if m=='turn/start':
  if mode=='stall':time.sleep(30)
  send({'method':'item/agentMessage/delta','params':{'threadId':'thread-test','turnId':'turn-test','itemId':'answer','delta':'답변'}})
  result={'turn':{'id':'turn-test'}}
 send({'id':r['id'],'result':result})
 if m=='turn/start':
  send({'method':'item/completed','params':{'threadId':'thread-test','turnId':'turn-test','item':{'id':'answer','type':'agentMessage','text':'답변'}}})
  send({'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'failed' if mode=='failed' else 'completed'}}})
''')
    script.chmod(0o755)
    trace=tmp_path/'trace.jsonl'
    monkeypatch.setenv('BORA_TEST_TRACE',str(trace))
    monkeypatch.setattr(client,'codex_command',lambda:str(script))
    native_popen = subprocess.Popen
    def python_server(argv, **kwargs):
        return native_popen([sys.executable, str(script), *argv[1:]], **kwargs)
    monkeypatch.setattr(client.subprocess, 'Popen', python_server)
    return trace


def run_question():
    deltas,done,errors=[],[],[]
    runner=client.AskRunner(on_delta=deltas.append,on_done=lambda *v:done.append(v),on_error=errors.append)
    assert runner.ask(Question(text='이번 질문'))
    runner._thread.join(4)
    assert not runner.running
    return deltas,done,errors


def test_real_process_protocol_stream_and_cleanup(fake_server):
    deltas,done,errors=run_question()
    assert deltas==['답변'] and len(done)==1 and not errors
    events=[json.loads(s) for s in fake_server.read_text().splitlines()]
    thread=next(e['params'] for e in events if e.get('method')=='thread/start')
    assert thread['sandbox']=='read-only' and thread['ephemeral']
    assert not Path(thread['cwd']).exists()


def test_api_login_is_rejected_before_inference(fake_server,monkeypatch):
    monkeypatch.setenv('BORA_TEST_MODE','api')
    deltas,done,errors=run_question()
    assert not deltas and not done and 'ChatGPT' in errors[0]
    assert 'turn/start' not in fake_server.read_text()


def test_failure_is_not_done(fake_server,monkeypatch):
    monkeypatch.setenv('BORA_TEST_MODE','failed')
    deltas,done,errors=run_question()
    assert deltas and not done and errors


def test_cancel_stalled_process(fake_server,monkeypatch):
    monkeypatch.setenv('BORA_TEST_MODE','stall')
    errors=[]
    runner=client.AskRunner(on_error=errors.append)
    runner.ask(Question(text='질문'))
    end=time.monotonic()+3
    while time.monotonic()<end:
        if fake_server.exists() and 'turn/start' in fake_server.read_text():break
        time.sleep(.02)
    runner.cancel();runner._thread.join(4)
    assert not runner.running and not errors


def test_conversation_save_restore_and_conflict(tmp_path):
    video=tmp_path/'강의.mp4';directory=tmp_path/'data'
    one=Conversation(video,directory)
    one.messages=[{'role':'user','content':'질문'}];one.save()
    two=Conversation(video,directory)
    assert two.messages==one.messages
    if os.name == 'posix':
        assert one.path.stat().st_mode & 0o077 == 0
    two.messages.append({'role':'assistant','content':'답변'});two.save()
    with pytest.raises(OSError):one.save()
    assert Conversation(tmp_path/'other.mp4',directory).messages==[]


def test_broken_history_preserved(tmp_path):
    one=Conversation(tmp_path/'a.mp4',tmp_path)
    one.path.write_text('broken')
    with pytest.raises(OSError):Conversation(tmp_path/'a.mp4',tmp_path)
    assert one.path.read_text()=='broken'


def test_workspace_exact_paths_no_shell(tmp_path,monkeypatch):
    from bora.ai import workspace
    folder=tmp_path/'공백 $(touch nope)';folder.mkdir()
    note=folder/'강의.md';note.write_text('메모')
    calls=[]
    monkeypatch.setattr(workspace,'codex_command',lambda:'/local/codex')
    monkeypatch.setattr(workspace.integration,'launch_terminal',lambda *a:calls.append(a))
    launch(folder/'강의.mp4',note,question='설명해줘')
    argv,cwd,env=calls[0]
    assert cwd==folder and argv[argv.index('--cd')+1]==str(folder)
    assert 'workspace-write' in argv and 'on-request' in argv
    assert json.loads(argv[-1].split('\n')[1])['메모'] == str(note)
    assert '설명해줘' in argv[-1]
    assert 'forced_login_method="chatgpt"' in argv


def test_terminal_platform_command_keeps_arguments(tmp_path,monkeypatch):
    from bora.platform.linux.integration import terminal_command
    monkeypatch.setattr('shutil.which',lambda name:'/usr/bin/gnome-terminal' if name=='gnome-terminal' else None)
    command=terminal_command(['/bin/codex','질문; echo nope'],tmp_path/'a b')
    assert command[-1]=='질문; echo nope' and command[2]==str(tmp_path/'a b')


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_workspace_provider_missing_does_not_launch(tmp_path, monkeypatch, provider):
    from bora.ai import workspace
    monkeypatch.setattr(workspace, 'terminal_command', lambda _p: None)
    with pytest.raises(OSError, match='설치 안내'):
        workspace.launch(tmp_path/'video.mp4', tmp_path/'memo.md', provider=provider)


def test_claude_workspace_uses_interactive_cli_and_preserves_arguments(tmp_path, monkeypatch):
    from bora.ai import workspace
    folder = tmp_path/'한글 공백 $(touch nope)'; folder.mkdir()
    note = folder/'메모.md'; note.write_text('기존 메모')
    calls = []
    monkeypatch.setattr(workspace, 'terminal_command', lambda p: '/local/claude' if p == 'claude' else None)
    monkeypatch.setattr(workspace.integration, 'launch_terminal', lambda *args: calls.append(args))
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_OAUTH_TOKEN'):
        monkeypatch.setenv(key, 'test-value')
    workspace.launch(folder/'영상.mp4', note, question='왜?; echo nope', provider='claude')
    argv, cwd, env = calls[0]
    assert argv[0] == '/local/claude' and cwd == folder
    assert '--print' not in argv and '-p' not in argv
    assert argv[argv.index('--permission-mode')+1] == 'manual'
    assert json.loads(argv[argv.index('--settings')+1])['forceLoginMethod'] == 'claudeai'
    assert '왜?; echo nope' in argv[-1]
    assert json.loads(argv[-1].split('\n')[1])['메모'] == str(note)
    assert not any(k in env for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_OAUTH_TOKEN'))
    assert note.read_text() == '기존 메모'


def test_workspace_rejects_unsaved_note(tmp_path, monkeypatch):
    from bora.ai import workspace
    monkeypatch.setattr(workspace, 'terminal_command', lambda _p: '/local/claude')
    with pytest.raises(OSError, match='저장되지'):
        workspace.launch(tmp_path/'video.mp4', tmp_path/'missing.md', provider='claude')
