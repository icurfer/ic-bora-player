"""외부 터미널 선택과 저장 경계의 GTK 통합 검사. 실제 서비스는 호출하지 않는다."""
from types import SimpleNamespace
from unittest.mock import Mock

import gi
import pytest

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk
from bora.ai import workspace
from bora.notes.panel import NotePanel
from bora.state import State
from bora.window import BoraWindow


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, 'terminal_command', lambda p: '/local/' + p)
    h = SimpleNamespace(state=State(tmp_path/'config'), _current=tmp_path/'영상.mp4',
                        _plan=None, toast=Mock(), toggle_notes=Mock(), show_ai_settings=Mock())
    h.open_agent_terminal = lambda question=None: BoraWindow.open_agent_terminal(h, question)
    h._notes = NotePanel(h)
    h._notes.load_for(h._current)
    monkeypatch.setattr('threading.Thread', lambda target, **kwargs: SimpleNamespace(start=target))
    yield h
    h._notes._cancel_autosave()


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_selection_and_shortcut_save_before_launch(host, monkeypatch, provider):
    panel = host._notes
    panel._terminal_choices[provider].set_active(True)
    panel._buffer.set_text('왜 이런 결과가 나오나요?')
    calls = []
    def launch(video, note, subtitle, question, **options):
        calls.append((video, note.read_text(), question, options['provider']))
    monkeypatch.setattr(workspace, 'launch', launch)
    assert panel._on_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType.CONTROL_MASK)
    assert calls == [(host._current, '왜 이런 결과가 나오나요?\n', '왜 이런 결과가 나오나요?', provider)]
    assert State(host.state.dir).settings.terminal_provider == provider
    assert panel._ask_btn.get_label() == ('Claude' if provider == 'claude' else 'Codex')


def test_uninstalled_tool_shows_install_guidance(host, monkeypatch):
    host._notes._terminal_choices['claude'].set_active(True)
    monkeypatch.setattr(workspace, 'terminal_command', lambda p: None)
    host._notes._refresh_terminal_choice()
    launch = Mock(); monkeypatch.setattr(workspace, 'launch', launch)
    assert not host.open_agent_terminal()
    assert '설치 필요' in host._notes._terminal_hint.get_text()
    assert 'code.claude.com' in host._notes._terminal_install.get_uri()
    assert '설치 안내' in host.toast.call_args.args[0]
    launch.assert_not_called()


def test_external_edit_conflict_blocks_selected_terminal(host, monkeypatch):
    panel = host._notes
    panel._terminal_choices['claude'].set_active(True)
    panel._buffer.set_text('처음 저장'); panel.save()
    panel._buffer.set_text('사용자의 미저장 편집')
    panel.doc.path.write_text('외부 변경 내용')
    launch = Mock(); monkeypatch.setattr(workspace, 'launch', launch)
    assert not host.open_agent_terminal('설명해줘')
    assert panel._text() == '사용자의 미저장 편집'
    assert panel.doc.path.read_text() == '외부 변경 내용'
    launch.assert_not_called()


def test_failed_save_blocks_terminal(host, monkeypatch):
    panel = host._notes
    panel._buffer.set_text('보존할 질문')
    monkeypatch.setattr(panel.doc, 'save', Mock(side_effect=OSError('test failure')))
    launch = Mock(); monkeypatch.setattr(workspace, 'launch', launch)
    assert not host.open_agent_terminal()
    assert panel._text() == '보존할 질문'
    launch.assert_not_called()
