"""로컬 Codex 연결과 ChatGPT 로그인. 보라는 비밀값을 읽거나 저장하지 않는다."""
import threading
import time
from urllib.parse import urlparse
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk
from .client import Session, CodexError, check_connection


class AISettingsWindow(Adw.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title='Codex 연결',
                         default_width=460, default_height=360)
        self._closed = False
        self._busy = False
        self._cancelled = threading.Event()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_start=20, margin_end=20, margin_top=16, margin_bottom=20)
        for text in ('로컬 Codex · ChatGPT 계정 사용',
                     '모델 응답은 온라인으로 처리되며 ChatGPT 사용 한도가 적용됩니다. API 키로 자동 전환하지 않습니다.',
                     '기본은 메모 폴더에서 Codex 터미널로 질문·파일 작업을 합니다. 앱에서는 위쪽 메모와 아래쪽 대화를 함께 볼 수 있습니다.'):
            box.append(Gtk.Label(label=text, xalign=0, wrap=True))
        row = Gtk.Box(spacing=8)
        self.check = Gtk.Button(label='연결 확인')
        self.login = Gtk.Button(label='ChatGPT 로그인', css_classes=['suggested-action'])
        row.append(self.check); row.append(self.login); box.append(row)
        self.status = Gtk.Label(label='연결 상태를 확인하세요.', xalign=0, wrap=True, selectable=True)
        box.append(self.status)
        box.append(Gtk.LinkButton(uri='https://learn.chatgpt.com/docs/quickstart', label='Codex 설치 안내'))
        root.append(Gtk.ScrolledWindow(child=box, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.set_content(root)
        self.check.connect('clicked', lambda *_: self._run(check_connection))
        self.login.connect('clicked', lambda *_: self._run(self._sign_in))
        self.connect('close-request', self._close)
        self._run(check_connection)

    def _close(self, *_):
        self._closed = True
        self._cancelled.set()
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
                    return 'ChatGPT 로그인 완료 · 이제 아래쪽 Codex 대화에서 질문할 수 있습니다.'

    def _run(self, work):
        if self._busy:
            return
        self._busy = True
        self.check.set_sensitive(False); self.login.set_sensitive(False)
        self.status.set_label('Codex에 연결하고 있습니다…')
        def run():
            try:
                result = work()
            except CodexError as exc:
                result = str(exc)
            except Exception:
                result = 'Codex에 연결하지 못했습니다. 설치와 네트워크를 확인하세요.'
            GLib.idle_add(done, result)
        def done(result):
            self._busy = False
            if not self._closed:
                self.check.set_sensitive(True); self.login.set_sensitive(True)
                self.status.set_label(result)
            return False
        threading.Thread(target=run, daemon=True).start()
