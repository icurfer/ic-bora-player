"""저장된 대화를 학습메모 원문/요약으로 만든다. 원본 대화는 변경하지 않는다."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import quote

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk
from .context import Question
from ..notes.model import format_stamp


def question_for(messages, answer):
    reply = answer.get('reply_to')
    if reply:
        return next((m for m in messages if m.get('id') == reply and m['role'] == 'user'), None)
    # 이전 파일에는 ID가 없다. 해당 답변 앞의 질문만 찾고 이후 질문은 보지 않는다.
    previous = None
    for message in messages:
        if message is answer:
            return previous
        if message['role'] == 'user':
            previous = message
    return None


def message_text(message):
    text = message.get('content', '')
    attachments = message.get('attachments', [])
    if isinstance(attachments, list):
        names = [name for name in attachments if isinstance(name, str)]
        if names:
            text += '\n\n첨부: ' + ', '.join(names)
    references = message.get('image_refs', [])
    for reference in references if isinstance(references, list) else []:
        if not isinstance(reference, str):
            continue
        path = PurePosixPath(reference)
        if path.is_absolute() or '..' in path.parts or ':' in reference or '\\' in reference:
            continue
        text += '\n\n![대화 첨부](' + quote(reference, safe='/') + ')'
    return text


def qa_text(messages, answer):
    question = question_for(messages, answer)
    stamp = format_stamp(answer.get('timestamp', 0))
    partial = ' (미완료)' if answer.get('status') in ('error', 'interrupted') else ''
    author = 'OpenAI API' if answer.get('provider') == 'openai' else 'Codex'
    return (f'\n\n### {stamp} 질문과 답변{partial}\n\n**질문**\n\n'
            + (message_text(question) if question else '(이전 기록에 연결된 질문이 없습니다)')
            + '\n\n**' + author + ' 답변**\n\n' + message_text(answer) + '\n')


def transcript(messages):
    parts = ['## 학습 대화 원문']
    for message in messages:
        author = 'OpenAI API' if message.get('provider') == 'openai' else 'Codex'
        role = '질문' if message['role'] == 'user' else author + ' 답변'
        partial = ' (미완료)' if message.get('status') in ('error', 'interrupted') else ''
        parts.append(f"### {format_stamp(message.get('timestamp', 0))} {role}{partial}\n\n{message_text(message)}")
    return '\n\n'.join(parts) + '\n'


def message_marker(message, index):
    payload = json.dumps([index, message], ensure_ascii=False, sort_keys=True)
    return '<!-- bora-chat:' + hashlib.sha256(payload.encode()).hexdigest() + ' -->'


def pending_transcript(messages, note):
    """메모와 저장 표시를 함께 기록해 재시작과 저장 재시도에서도 중복을 막는다."""
    parts = []
    for index, message in enumerate(messages):
        marker = message_marker(message, index)
        if marker not in note:
            # 발언별 영상 시각을 유지한다. 답변만 나중에 도착해도 시각이 남는다.
            parts.append(transcript([message]).removeprefix('## 학습 대화 원문\n\n').strip() + '\n' + marker)
    return '\n\n' + '\n\n'.join(parts) + '\n' if parts else ''


class StudyPreview(Gtk.Window):
    """사용자가 확인한 텍스트만 메모에 추가한다. 생성 중에는 적용할 수 없다."""
    def __init__(self, panel):
        super().__init__(title='대화로 학습메모 만들기', transient_for=panel.window,
                         modal=False, default_width=660, default_height=520)
        self.panel, self.path = panel, panel._path
        self.messages = deepcopy(panel.doc.messages)
        self.source = transcript(self.messages)
        self.note_source = re.sub(r'<!-- bora-chat:[0-9a-f]{64} -->\n?', '', panel.window._notes._text())
        self.runner = None
        self.generation = 0
        self.closed = False
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.set_child(root)
        row = Gtk.Box(spacing=8)
        self.original_button = Gtk.Button(label='대화 원문')
        self.original_button.connect('clicked', lambda *_: self.original())
        row.append(self.original_button)
        self.summary_button = Gtk.Button(label='전체 메모 AI 요약')
        self.summary_button.set_tooltip_text('현재 선택한 AI로 대화를 요약합니다. 해당 연결의 사용량이 발생합니다.')
        self.summary_button.connect('clicked', lambda *_: self.summarize())
        row.append(self.summary_button)
        self.stop_button = Gtk.Button(label='중지', sensitive=False)
        self.stop_button.connect('clicked', lambda *_: self.stop())
        row.append(self.stop_button)
        root.append(row)
        self.include_notes = Gtk.CheckButton(label='현재 메모도 요약에 포함', active=True)
        self.include_notes.set_tooltip_text('이 창을 열 때의 메모를 함께 정리합니다. 창을 다시 열면 최신 메모가 반영됩니다.')
        root.append(self.include_notes)
        self.status = Gtk.Label(label='원문을 확인하거나 AI 요약을 만든 뒤 메모에 추가하세요.', wrap=True, xalign=0)
        root.append(self.status)
        self.buffer = Gtk.TextBuffer()
        self.buffer.set_text(self.source)
        self.view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        root.append(Gtk.ScrolledWindow(child=self.view, vexpand=True))
        self.apply_button = Gtk.Button(label='메모 끝에 추가', css_classes=['suggested-action'])
        self.apply_button.connect('clicked', lambda *_: self.apply())
        root.append(self.apply_button)
        self.connect('close-request', self._close)

    def _close(self, *_args):
        self.closed = True
        self.stop()
        if self.panel._study_preview is self:
            self.panel._study_preview = None
        return False

    def stop(self):
        self.generation += 1
        if self.runner is not None:
            self.runner.cancel()
            self.runner = None
            self.status.set_text('요약을 중지했습니다. 원문으로 돌아가거나 다시 생성하세요.')
            self.apply_button.set_sensitive(False)
        self.summary_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.view.set_editable(True)

    def original(self):
        self.stop()
        self.buffer.set_text(self.source)
        self.apply_button.set_sensitive(True)
        self.status.set_text('대화 원문 · 내용을 수정한 뒤 추가할 수 있습니다.')

    def summarize(self):
        from .api import load_config, AIError, APIAskRunner
        from .client import AskRunner, ensure_ready
        self.stop()
        source = self.source
        if self.include_notes.get_active() and self.note_source.strip():
            source = '## 전체 학습메모\n\n' + self.note_source
        if len(source) > 60000:
            self.status.set_text('기록이 너무 깁니다(60,000자 초과). 원문 메모를 사용하세요. 내용을 잘라서 보내지 않았습니다.')
            return
        try:
            config = load_config()
            if config['provider'] == 'codex':
                ready, hint = ensure_ready()
                if not ready:
                    raise AIError(hint)
        except AIError as exc:
            self.status.set_text(str(exc))
            return
        self.generation += 1
        generation = self.generation
        self.buffer.set_text('')
        self.apply_button.set_sensitive(False)
        self.summary_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.view.set_editable(False)
        self.status.set_text('학습메모 요약 중… 원문 대화는 그대로 보존됩니다.')
        def dispatch(handler, *args):
            if not self.closed and generation == self.generation and self.path == self.panel._path:
                handler(*args)
            return False
        runner_class = APIAskRunner if config['provider'] == 'openai' else AskRunner
        self.runner = runner_class(
            **({'config': config} if config['provider'] == 'openai' else {}),
            on_delta=lambda text: GLib.idle_add(dispatch, self.delta, text),
            on_done=lambda *_: GLib.idle_add(dispatch, self.complete),
            on_error=lambda error: GLib.idle_add(dispatch, self.failed, error))
        question = Question(video_title=self.path.stem, text=(
            '아래 메모와 대화 기록을 한국어 학습메모로 정리해 주세요. 영상 시각과 아이디어의 연결을 유지하고 핵심 개념, 질문과 답변 요지, '
            '예시, 복습 질문, 미해결 사항을 마크다운으로 작성하세요. 기록 밖 사실을 추가하지 말고 '
            '미완료 답변은 미완료로 표시하세요. 첨부 파일 이름만으로 이미지 내용을 추측하지 마세요.\n\n'
            + source))
        if not self.runner.ask(question):
            self.failed('요약을 시작하지 못했습니다. 다시 시도하세요.')

    def delta(self, text):
        self.buffer.insert(self.buffer.get_end_iter(), text)

    def complete(self):
        self.runner = None
        self.summary_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.view.set_editable(True)
        has_text = bool(self.buffer.get_text(*self.buffer.get_bounds(), True).strip())
        self.apply_button.set_sensitive(has_text)
        self.status.set_text('AI 요약 · 사실과 누락을 검토한 뒤 추가하세요.' if has_text else '요약 응답이 비어 있습니다. 다시 시도하세요.')

    def failed(self, error):
        self.stop()
        self.apply_button.set_sensitive(False)
        self.status.set_text(str(error) + ' 원문은 보존되었습니다.')

    def apply(self):
        if self.runner is not None or not self.apply_button.get_sensitive():
            return
        text = self.buffer.get_text(*self.buffer.get_bounds(), True).strip()
        if not text or self.path != self.panel._path:
            return
        if self.panel.append_note('\n\n' + text + '\n', self.path):
            self.close()
        else:
            self.status.set_text(self.panel._status.get_text())
