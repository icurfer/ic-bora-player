"""서버 즐겨찾기와 비동기 원격 파일 탐색 UI."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, Gtk
from .network import Server, ServerStore, server_uri
from .platform import paths, network


class NetworkWindow(Gtk.Window):
    def __init__(self, parent, open_file, *, backend=None, store=None, session=None):
        super().__init__(title='네트워크 서버 열기', transient_for=parent,
                         default_width=640, default_height=620, destroy_with_parent=True)
        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label='네트워크 서버 열기'))
        self.set_titlebar(header)
        self.open_file = open_file
        self.store = store or ServerStore(paths.config_dir())
        self.browser = backend or network.Browser(self, session=session)
        self.current = None
        self.closed = False
        self.busy = False
        self.generation = 0
        self.connect('close-request', self._close)
        self.connect('unrealize', self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.set_child(root)
        root.append(Gtk.Label(label='SMB · SFTP · FTP · NFS 서버에서 영상 열기', xalign=0, css_classes=['title-3']))
        self.name = Gtk.Entry(placeholder_text='서버 이름 (선택)')
        self.name.set_tooltip_text('즐겨찾기에 표시할 서버 이름')
        self.address = Gtk.Entry(placeholder_text='smb://서버/공유 · sftp://사용자@서버:포트/폴더 · ftp://서버/폴더 · nfs://서버/경로')
        self.address.set_tooltip_text('서버 주소 · 비밀번호는 연결할 때 입력합니다')
        self.address.connect('activate', lambda *_: self.connect_server())
        root.append(self.name)
        root.append(self.address)
        controls = Gtk.Box(spacing=6)
        self.connect_button = Gtk.Button(label='연결', css_classes=['suggested-action'])
        self.connect_button.connect('clicked', lambda *_: self.connect_server())
        save = Gtk.Button(label='서버 저장')
        save.connect('clicked', lambda *_: self.save_server())
        self.cancel_button = Gtk.Button(label='취소', sensitive=False)
        self.cancel_button.connect('clicked', lambda *_: self.cancel())
        for button in (self.connect_button, save, self.cancel_button):
            controls.append(button)
        root.append(controls)
        self.servers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        saved_scroll = Gtk.ScrolledWindow(min_content_height=40, max_content_height=100,
                                          propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        saved_scroll.set_child(self.servers)
        root.append(saved_scroll)
        try:
            self.saved = self.store.load()
            initial = '비밀번호는 서버 목록에 저장하지 않습니다. NFS는 서버의 내보내기 경로를 입력하세요.'
        except ValueError as error:
            self.saved = []
            initial = str(error)
            save.set_sensitive(False)
        self._saved_rows()
        navigation = Gtk.Box(spacing=6)
        self.up = Gtk.Button(label='상위 폴더', sensitive=False)
        self.up.connect('clicked', lambda *_: self._up())
        self.refresh = Gtk.Button(label='다시 읽기', sensitive=False)
        self.refresh.connect('clicked', lambda *_: self._browse(self.current))
        navigation.append(self.up)
        navigation.append(self.refresh)
        root.append(navigation)
        self.location = Gtk.Label(xalign=0, ellipsize=3, selectable=True)
        root.append(self.location)
        self.status = Gtk.Label(label=initial, wrap=True, xalign=0)
        root.append(self.status)
        self.files = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.files)
        root.append(scroll)
        root.append(Gtk.Label(label='메모·편집한 자막은 영상과 같은 서버 폴더에 저장됩니다.\n대화 기록은 이 컴퓨터에 저장됩니다. 읽기 전용 서버에서는 메모를 저장할 수 없습니다.',
                              xalign=0, wrap=True, css_classes=['dim-label']))
        if backend is None and not network.available():
            self.status.set_text(network.reason())
            self.connect_button.set_sensitive(False)

    def _saved_rows(self):
        while self.servers.get_first_child():
            self.servers.remove(self.servers.get_first_child())
        if not self.saved:
            self.servers.append(Gtk.Label(label='저장된 서버가 없습니다.', xalign=0, css_classes=['dim-label']))
        for server in self.saved:
            row = Gtk.Box(spacing=6)
            choose = Gtk.Button(label=server.name or server.uri, hexpand=True, has_frame=False)
            choose.set_tooltip_text(server.uri)
            choose.connect('clicked', lambda _b, s=server: self._select_server(s))
            remove = Gtk.Button(label='삭제')
            remove.connect('clicked', lambda _b, s=server: self.remove_server(s))
            row.append(choose)
            row.append(remove)
            self.servers.append(row)

    def _select_server(self, server):
        self.name.set_text(server.name)
        self.address.set_text(server.uri)
        self.connect_server()

    def save_server(self):
        try:
            uri = server_uri(self.address.get_text())
            updated = [s for s in self.saved if s.uri != uri]
            updated.append(Server(self.name.get_text().strip() or uri, uri))
            self.store.save(updated)
        except (OSError, ValueError):
            self.status.set_text('저장하지 못했습니다. 주소 형식과 저장 권한을 확인하세요. 비밀번호는 주소에 넣지 마세요.')
            return
        self.saved = updated
        self._saved_rows()
        self.status.set_text('서버를 저장했습니다. 비밀번호는 포함하지 않습니다.')

    def remove_server(self, server):
        updated = [s for s in self.saved if s != server]
        try:
            self.store.save(updated)
        except (OSError, ValueError):
            self.status.set_text('서버 목록을 저장하지 못했습니다. 기존 목록을 유지합니다.')
            return
        self.saved = updated
        self._saved_rows()

    def connect_server(self):
        try:
            file = Gio.File.new_for_uri(server_uri(self.address.get_text()))
        except ValueError as error:
            self.status.set_text(str(error))
            return
        self._browse(file)

    def _set_busy(self, busy):
        self.busy = busy
        self.connect_button.set_sensitive(not busy)
        self.cancel_button.set_sensitive(busy)
        self.files.set_sensitive(not busy)
        self.up.set_sensitive(not busy and self.current is not None and self.current.get_parent() is not None)
        self.refresh.set_sensitive(not busy and self.current is not None)

    def _browse(self, file):
        if file is None or self.closed:
            return
        self.generation += 1
        generation = self.generation
        self._set_busy(True)
        self.status.set_text('서버에 연결하고 폴더를 읽고 있습니다…')
        def done(result, message):
            if self.closed or generation != self.generation:
                return
            self._set_busy(False)
            if result is None:
                self.status.set_text(message)
                return
            self.current, entries = result
            self.location.set_text(self.current.get_parse_name())
            self._set_busy(False)
            while self.files.get_first_child():
                self.files.remove(self.files.get_first_child())
            for name, display, directory in entries:
                row = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6)
                row.append(Gtk.Image(icon_name='folder-symbolic' if directory else 'video-x-generic-symbolic'))
                row.append(Gtk.Label(label=display, xalign=0, ellipsize=3, hexpand=True))
                button = Gtk.Button(child=row, has_frame=False)
                button.set_tooltip_text(display)
                child = self.current.get_child(name)
                button.connect('clicked', lambda _b, f=child, d=directory: self._activate(f, d))
                self.files.append(button)
            self.status.set_text(message or ('폴더가 비어 있습니다.' if not entries else '폴더를 열거나 재생할 영상을 선택하세요.'))
        self.browser.browse(file.get_uri(), done)

    def _activate(self, file, directory):
        if directory:
            self._browse(file)
            return
        try:
            opened = self.open_file(network.local_path(file))
        except Exception:
            self.status.set_text('파일을 열지 못했습니다. 연결 상태와 gvfs-fuse 설치를 확인하세요.')
            return
        if opened is not False:
            self.close()

    def _up(self):
        if self.current:
            self._browse(self.current.get_parent())

    def cancel(self):
        self.generation += 1
        self.browser.stop()
        self._set_busy(False)
        self.status.set_text('연결을 취소했습니다. 다시 연결할 수 있습니다.')

    def _close(self, *_):
        self.closed = True
        self.generation += 1
        self.browser.stop()
        return False
