"""앱 내 AI 방식 설정과 로컬 Codex 로그인. 비밀값 처리는 별도 작업 스레드에서 한다."""
import threading
import time
from urllib.parse import urlparse
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk
from .client import Session, CodexError, check_connection
from . import api


class AISettingsWindow(Adw.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title='AI 연결',
                         default_width=480, default_height=580)
        self._owner = parent
        self._closed = False
        self._busy = False
        self._cancelled = threading.Event()
        self._applied_provider = 'codex'
        self._last_model = api.DEFAULT_MODEL
        self._loading_config = False
        self._key_checked = False
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_start=20, margin_end=20, margin_top=16, margin_bottom=20)
        self.current = Gtk.Label(label='저장된 설정을 읽고 있습니다…', xalign=0, wrap=True)
        self.current.add_css_class('heading')
        box.append(self.current)
        box.append(Gtk.Label(label='앱 안 대화의 사용 방식', xalign=0))
        self.provider = Gtk.DropDown.new_from_strings(['로컬 Codex (기본)', 'OpenAI API (내 키)'])
        self.provider.update_property([Gtk.AccessibleProperty.LABEL], ['AI 사용 방식'])
        box.append(self.provider)
        box.append(Gtk.Label(label='방식을 고른 뒤 적용을 누르면 다음 질문부터 사용합니다. 진행 중인 답변은 기존 방식으로 계속됩니다.',
                             xalign=0, wrap=True))

        self.codex_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for text in ('로컬 Codex · ChatGPT 계정 사용',
                     '모델 응답은 온라인으로 처리되며 ChatGPT 사용 한도가 적용됩니다. API 키로 자동 전환하지 않습니다.',
                     '메모 폴더에서 여는 Codex 터미널은 이 설정과 별개로 계속 로컬 Codex를 사용합니다.'):
            self.codex_box.append(Gtk.Label(label=text, xalign=0, wrap=True))
        self.login = Gtk.Button(label='ChatGPT 로그인', halign=Gtk.Align.START)
        self.codex_box.append(self.login)
        self.codex_box.append(Gtk.LinkButton(uri='https://learn.chatgpt.com/docs/quickstart', label='Codex 설치 안내'))
        box.append(self.codex_box)

        self.api_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.api_box.append(Gtk.Label(label='OpenAI API는 ChatGPT 구독과 별도로 사용량에 따라 과금됩니다. 질문과 선택한 자막·메모 문맥이 OpenAI로 전송됩니다.',
                                      xalign=0, wrap=True))
        self.api_box.append(Gtk.Label(label='새 API 키', xalign=0))
        self.key_entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        self.key_entry.set_tooltip_text('새 키를 입력하세요. 비워 두면 저장된 키를 유지합니다.')
        self.key_entry.update_property([Gtk.AccessibleProperty.LABEL], ['OpenAI API 키'])
        self.api_box.append(self.key_entry)
        self.key_status = Gtk.Label(label='키 저장 상태를 확인하고 있습니다…', xalign=0, wrap=True)
        self.api_box.append(self.key_status)
        self.api_box.append(Gtk.Label(label='키는 시스템 키 저장소에 보관합니다. 저장소를 사용할 수 없으면 평문 파일로 대체하지 않습니다.',
                                      xalign=0, wrap=True))
        self.api_box.append(Gtk.Label(label='모델', xalign=0))
        self.model_entry = Gtk.Entry(text='gpt-4.1-mini', hexpand=True)
        self.model_entry.update_property([Gtk.AccessibleProperty.LABEL], ['OpenAI API 모델'])
        self.api_box.append(self.model_entry)
        self.delete = Gtk.Button(label='저장된 API 키 삭제', halign=Gtk.Align.START)
        self.api_box.append(self.delete)
        self.api_box.append(Gtk.Label(label='키를 삭제하면 다음 API 질문을 보낼 수 없습니다. 로컬 Codex 로그인과 대화 기록은 유지됩니다.',
                                      xalign=0, wrap=True))
        box.append(self.api_box)
        root.append(Gtk.ScrolledWindow(child=box, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        root.append(Gtk.Separator())
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                         margin_start=20, margin_end=20, margin_top=16, margin_bottom=16)
        row = Gtk.Box(spacing=8)
        self.check = Gtk.Button(label='연결 확인')
        self.apply = Gtk.Button(label='적용', css_classes=['suggested-action'])
        row.append(self.check)
        row.append(self.apply)
        footer.append(row)
        self.status = Gtk.Label(label='', xalign=0, wrap=True, selectable=True)
        footer.append(self.status)
        root.append(footer)
        self.set_content(root)
        self._controls = (self.provider, self.key_entry, self.model_entry,
                          self.check, self.login, self.apply, self.delete)
        self.provider.connect('notify::selected', self._provider_changed)
        self.check.connect('clicked', self._check)
        self.login.connect('clicked', lambda *_: self._run(self._sign_in, busy='브라우저 로그인을 준비하고 있습니다…'))
        self.apply.connect('clicked', self._apply)
        self.delete.connect('clicked', self._delete)
        self.connect('close-request', self._close)
        self._show_provider()
        self._run(api.load_config, self._loaded, '저장된 AI 설정을 읽고 있습니다…', self._load_failed)

    def _selected_provider(self):
        return 'openai' if self.provider.get_selected() == 1 else 'codex'

    def _show_provider(self):
        use_api = self._selected_provider() == 'openai'
        self.codex_box.set_visible(not use_api)
        self.api_box.set_visible(use_api)

    def _provider_changed(self, *_):
        self._show_provider()
        if not self._busy and not self._loading_config:
            self.status.set_label('아직 적용하지 않았습니다. 연결 확인은 설정을 저장하지 않습니다.')
            if self._selected_provider() == 'openai':
                self._query_key()

    def _query_key(self):
        if self._key_checked:
            return
        def work():
            return '저장된 키가 있습니다. 새 키를 비워 두면 유지합니다.' if api.get_key() else '저장된 키가 없습니다.'
        def finish(note):
            self._key_checked = True
            self.key_status.set_label(note)
            self.status.set_label('연결 확인은 설정을 저장하지 않습니다. 변경하려면 적용을 누르세요.')
        self._run(work, finish, '시스템 키 저장소를 확인하고 있습니다…', self.key_status.set_label)

    def _load_failed(self, message):
        self.current.set_label('적용된 설정을 읽지 못했습니다')
        self.status.set_label(message + ' 로컬 Codex를 선택하고 적용하면 설정을 다시 저장할 수 있습니다.')

    def _loaded(self, config):
        self._applied_provider = config.get('provider', 'codex')
        self._loading_config = True
        self.provider.set_selected(1 if self._applied_provider == 'openai' else 0)
        self._loading_config = False
        self._last_model = config.get('model') or api.DEFAULT_MODEL
        self.model_entry.set_text(self._last_model)
        self.key_entry.set_text('')
        self.key_status.set_label('OpenAI API를 선택하면 저장된 키 여부를 확인합니다.')
        self._show_provider()
        self._show_current()
        self.status.set_label('연결 확인으로 선택한 방식의 준비 상태를 확인할 수 있습니다.')
        if self._applied_provider == 'openai':
            self._query_key()

    def _show_current(self):
        self.current.set_label('현재 적용: ' + ('OpenAI API (내 키)' if self._applied_provider == 'openai' else '로컬 Codex'))

    def _check(self, *_):
        if self._selected_provider() == 'codex':
            self._run(check_connection, busy='Codex 설치·로그인 상태를 확인하고 있습니다…')
            return
        entered, model = self.key_entry.get_text().strip(), self.model_entry.get_text().strip()
        def work():
            if not model:
                raise api.AIError('사용할 모델을 입력해 주세요.')
            api.validate_model(model)
            key = entered or api.get_key()
            if not key:
                raise api.AIError('API 키를 입력한 뒤 연결을 확인해 주세요.')
            return api.check_api(key, model)
        self._run(work, lambda result: self.status.set_label(str(result) + ' 설정을 저장하려면 적용을 누르세요.'),
                  'API 인증·모델 접근을 확인하고 있습니다. 질문은 전송하지 않습니다…')

    def _apply(self, *_):
        provider = self._selected_provider()
        entered, model = self.key_entry.get_text().strip(), self.model_entry.get_text().strip()
        effective_model = model if provider == 'openai' else self._last_model
        def work():
            api.validate_model(effective_model)
            key_saved = False
            if provider == 'openai':
                if not model:
                    raise api.AIError('사용할 모델을 입력해 주세요.')
                if entered:
                    api.set_key(entered)
                    key_saved = True
                elif not api.get_key():
                    raise api.AIError('OpenAI API를 사용하려면 키를 입력해 주세요.')
            try:
                api.save_config(provider, effective_model)
            except Exception:
                if key_saved:
                    raise api.AIError('API 키는 저장됐지만 사용 방식 적용에 실패했습니다. 설정 저장 위치를 확인한 뒤 다시 적용해 주세요.') from None
                raise
            return provider
        def applied(result):
            self._applied_provider = result
            self._last_model = effective_model
            self.key_entry.set_text('')
            if result == 'openai':
                self.key_status.set_label('저장된 키가 있습니다. 새 키를 비워 두면 유지합니다.')
            self._show_current()
            self._owner._chat.refresh_provider()
            self.status.set_label('적용했습니다. 다음 질문부터 사용하며, 진행 중인 답변은 기존 방식으로 계속됩니다.')
        self._run(work, applied, 'AI 설정을 저장하고 있습니다…')

    def _delete(self, *_):
        def work():
            api.delete_key()
            return '저장된 API 키를 삭제했습니다. API를 다시 사용하려면 새 키를 입력하세요.'
        def deleted(result):
            self.key_entry.set_text('')
            self.key_status.set_label('저장된 키가 없습니다.')
            self.status.set_label(result)
            self._owner._chat.refresh_provider()
        self._run(work, deleted, '저장된 API 키를 삭제하고 있습니다…')

    def _close(self, *_):
        self._closed = True
        self._cancelled.set()
        self.key_entry.set_text('')
        return False

    def _open_login(self, url):
        if not self._closed:
            self.status.set_label('브라우저에서 ChatGPT 로그인을 완료하세요. 이 창을 닫으면 연결 대기를 중지합니다.')
            Gtk.show_uri(self, url, 0)
        return False

    def _sign_in(self):
        with Session(self._cancelled) as session:
            result = session.rpc('account/login/start', {'type': 'chatgpt'})
            url = result.get('authUrl', '')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in ('auth.openai.com', 'auth0.openai.com'):
                raise CodexError('Codex가 로그인 주소를 제공하지 못했습니다. 설치 안내에서 로그인 방법을 확인하세요.')
            GLib.idle_add(self._open_login, url)
            deadline = time.monotonic() + 240
            while True:
                event = session.pending.pop(0) if session.pending else session.receive(deadline)
                if event.get('method') == 'account/login/completed':
                    params = event.get('params') or {}
                    if params.get('loginId') != result.get('loginId'):
                        continue
                    if not params.get('success'):
                        raise CodexError('로그인을 완료하지 못했습니다. 다시 시도하세요.')
                    session.require_chatgpt()
                    return 'ChatGPT 로그인 완료 · 로컬 Codex를 선택하고 적용하면 앱 대화에서 사용할 수 있습니다.'

    def _run(self, work, finish=None, busy='처리하고 있습니다…', on_error=None):
        if self._busy or self._closed:
            return
        self._busy = True
        for control in self._controls:
            control.set_sensitive(False)
        self.status.set_label(busy)
        def run():
            try:
                result, error = work(), None
            except (CodexError, api.AIError) as exc:
                result, error = None, str(exc)
            except Exception:
                result, error = None, '처리하지 못했습니다. 연결 상태와 시스템 키 저장소를 확인한 뒤 다시 시도하세요.'
            GLib.idle_add(done, result, error)
        def done(result, error):
            self._busy = False
            if self._closed:
                return False
            for control in self._controls:
                control.set_sensitive(True)
            if error:
                self.status.set_label(error)
                if on_error:
                    on_error(error)
            elif finish:
                finish(result)
            else:
                self.status.set_label(str(result))
            return False
        threading.Thread(target=run, daemon=True).start()
