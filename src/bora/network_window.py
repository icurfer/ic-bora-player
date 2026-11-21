"""서버 즐겨찾기와 비동기 원격 파일 탐색 UI."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, Gtk, GLib
from .network import (Server, ServerStore, server_uri, PROTOCOLS, DEFAULT_PORTS,
                      connection_fields, connection_uri)
from .platform import paths, network
from .log import redact
from urllib.parse import urlsplit, unquote


def server_label(server):
    """이전 자동 이름에 주소가 들어 있어도 상시 표시하지 않는다."""
    name = server.name.strip()
    return name if name and redact(name) == name else f"{urlsplit(server.uri).scheme.upper()} 서버"


def location_label(uri):
    return unquote(urlsplit(uri).path) or "/"


class NetworkWindow(Gtk.Window):
    def __init__(self, parent, open_file, *, backend=None, store=None, session=None, restore=True):
        super().__init__(title='네트워크 서버 열기', transient_for=parent,
                         default_width=800, default_height=720, destroy_with_parent=True)
        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label='네트워크 서버 열기'))
        self.set_titlebar(header)
        self.open_file = open_file
        self.store = store or ServerStore(paths.config_dir())
        self.browser = backend or network.Browser(self, session=session)
        self.session = session
        self.current = None
        self.closed = False
        self.busy = False
        self.generation = 0
        self._recent_request = None
        self._loading_fields = False
        self._source_uri = None
        self._source_fields = None
        self.connect('close-request', self._close)
        self.connect('unrealize', self._close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                       margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        self.set_child(root)
        root.append(Gtk.Label(label='SMB · SFTP · FTP · NFS 서버에서 영상 열기', xalign=0, css_classes=['title-3']))
        self.name = Gtk.Entry(placeholder_text='서버 이름 (선택)')
        self.name.set_tooltip_text('즐겨찾기에 표시할 서버 이름')
        self.protocol = Gtk.DropDown.new_from_strings([s.upper() for s in PROTOCOLS])
        self.protocol.set_tooltip_text('연결 방식')
        self.protocol.update_property([Gtk.AccessibleProperty.LABEL], ['연결 방식'])
        self.port = Gtk.Entry(width_chars=6, max_width_chars=7, input_purpose=Gtk.InputPurpose.DIGITS)
        self.port.update_property([Gtk.AccessibleProperty.LABEL], ['포트'])
        self.port.connect('activate', lambda *_: self.connect_server())
        protocol_row = Gtk.Box(spacing=8)
        for widget in (Gtk.Label(label='연결 방식'), self.protocol,
                       Gtk.Label(hexpand=True), Gtk.Label(label='포트'), self.port):
            protocol_row.append(widget)
        self.protocol.connect('notify::selected', self._protocol_changed)
        self._protocol_changed()
        self.address = Gtk.Entry(placeholder_text='192.0.2.10/video 또는 nas.example.com/폴더')
        self.address.set_tooltip_text('서버/경로 · 필요하면 사용자@서버/폴더 · 비밀번호는 인증 창에서 입력합니다')
        self.address.update_property([Gtk.AccessibleProperty.LABEL], ['서버 / 경로'])
        self.address.connect('changed', self._address_changed)
        self.address.connect('activate', lambda *_: self.connect_server())
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        form_scroll = Gtk.ScrolledWindow(min_content_height=80, max_content_height=300,
                                          propagate_natural_height=True,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER)
        form_scroll.set_child(form)
        self.connection_form = Gtk.Expander(label='연결 정보 · 서버 변경', expanded=True, child=form_scroll)
        root.append(self.connection_form)
        form.append(self.name)
        form.append(protocol_row)
        form.append(Gtk.Label(label='서버 / 경로', xalign=0))
        form.append(self.address)
        controls = Gtk.Box(spacing=6)
        self.connect_button = Gtk.Button(label='연결', css_classes=['suggested-action'])
        self.connect_button.connect('clicked', lambda *_: self.connect_server())
        save = Gtk.Button(label='서버 저장')
        self.save_button = save
        save.connect('clicked', lambda *_: self.save_server())
        self.cancel_button = Gtk.Button(label='취소', sensitive=False)
        self.cancel_button.connect('clicked', lambda *_: self.cancel())
        for button in (self.connect_button, save):
            controls.append(button)
        form.append(controls)
        self.servers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        saved_scroll = Gtk.ScrolledWindow(min_content_height=40, max_content_height=100,
                                          propagate_natural_height=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        saved_scroll.set_child(self.servers)
        form.append(saved_scroll)
        try:
            self.saved = self.store.load()
            self.can_save_servers = True
            initial = '비밀번호는 서버 목록에 저장하지 않습니다. NFS는 시스템 관리자 인증으로 읽기 전용 연결합니다.'
        except ValueError as error:
            self.saved = []
            self.can_save_servers = False
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
        navigation.append(Gtk.Label(hexpand=True))
        navigation.append(self.cancel_button)
        root.append(navigation)
        self.location = Gtk.Label(xalign=0, ellipsize=3, selectable=True)
        root.append(self.location)
        self.status = Gtk.Label(label=initial, wrap=True, xalign=0)
        root.append(self.status)
        self.files = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.files_scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=160,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.files_scroll.set_child(self.files)
        self.content = Gtk.Stack(vexpand=True)
        self.content.add_named(self.files_scroll, 'files')
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=16, margin_start=12, margin_end=12)
        heading = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        heading.append(self.spinner)
        heading.append(Gtk.Label(label='폴더 목록을 불러오는 중…', xalign=0))
        loading.append(heading)
        for width in (280, 210, 250, 180):
            row = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8)
            row.append(Gtk.Image(icon_name='folder-symbolic', css_classes=['dim-label']))
            bar = Gtk.ProgressBar(fraction=1, width_request=width, opacity=.18, valign=Gtk.Align.CENTER)
            row.append(bar)
            loading.append(row)
        self.content.add_named(loading, 'loading')
        root.append(self.content)
        self.storage_notice = Gtk.Label(label='메모·편집한 자막은 영상과 같은 서버 폴더에 저장됩니다.\n대화 기록은 이 컴퓨터에 저장됩니다. 읽기 전용 서버에서는 메모를 저장할 수 없습니다.',
                                        xalign=0, wrap=True, css_classes=['dim-label'])
        self.storage_default = self.storage_notice.get_text()
        root.append(self.storage_notice)
        if backend is None and not network.available():
            self.status.set_text(network.reason())
            self.connect_button.set_sensitive(False)
        if restore and session is not None and getattr(session, 'last_location', None) is not None:
            if session.last_server:
                self.name.set_text(server_label(session.last_server))
                self._load_uri(session.last_server.uri)
            def restore():
                self._browse(session.last_location)
                return False
            GLib.timeout_add(1, restore)

    def _protocol_changed(self, *_):
        if self._loading_fields:
            return
        default = DEFAULT_PORTS[PROTOCOLS[self.protocol.get_selected()]]
        self.port.set_text(str(default) if default else '자동')
        self.port.set_sensitive(default is not None)
        self.port.set_tooltip_text('기본 포트 · 직접 변경할 수 있습니다' if default else 'NFS 포트는 시스템이 자동으로 정합니다')

    def _fields(self):
        return PROTOCOLS[self.protocol.get_selected()], self.address.get_text(), self.port.get_text()

    def _load_uri(self, uri):
        try:
            uri = server_uri(uri)
            scheme, address, port = connection_fields(uri)
        except ValueError as error:
            self.status.set_text(str(error))
            return False
        self._loading_fields = True
        try:
            self.protocol.set_selected(PROTOCOLS.index(scheme))
            self.address.set_text(address)
            self.port.set_text(port)
            self.port.set_sensitive(scheme != 'nfs')
            self.port.set_tooltip_text('NFS 포트는 시스템이 자동으로 정합니다' if scheme == 'nfs' else '포트 · 직접 변경할 수 있습니다')
        finally:
            self._loading_fields = False
        self._source_uri, self._source_fields = uri, self._fields()
        return True

    def _address_changed(self, *_):
        if not self._loading_fields and '://' in self.address.get_text():
            self._load_uri(self.address.get_text())

    def _connection_uri(self):
        if self._source_uri is not None and self._fields() == self._source_fields:
            return self._source_uri  # 명시적 기본 포트도 기존 영상 식별 주소를 유지한다.
        return connection_uri(*self._fields())

    def _saved_rows(self):
        while self.servers.get_first_child():
            self.servers.remove(self.servers.get_first_child())
        if not self.saved:
            self.servers.append(Gtk.Label(label='저장된 서버가 없습니다.', xalign=0, css_classes=['dim-label']))
        for server in self.saved:
            row = Gtk.Box(spacing=6)
            choose = Gtk.Button(label=server_label(server), hexpand=True, has_frame=False)
            choose.set_tooltip_text('저장한 서버에 연결')
            choose.connect('clicked', lambda _b, s=server: self._select_server(s))
            remove = Gtk.Button(label='삭제')
            remove.connect('clicked', lambda _b, s=server: self.remove_server(s))
            row.append(choose)
            row.append(remove)
            self.servers.append(row)

    def _select_server(self, server):
        self._recent_request = None  # 즐겨찾기 선택은 이전 파일 재시도와 별개의 탐색이다.
        self.name.set_text(server_label(server))
        if self._load_uri(server.uri):
            self.connect_server()

    def save_server(self):
        try:
            uri = self._connection_uri()
            updated = [s for s in self.saved if s.uri != uri]
            updated.append(Server(self.name.get_text().strip() or f'{urlsplit(uri).scheme.upper()} 서버', uri))
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
            file = Gio.File.new_for_uri(self._connection_uri())
        except ValueError as error:
            self.status.set_text(str(error))
            return
        if self._recent_request and file.equal(Gio.File.new_for_uri(self._recent_request[1])):
            self.reopen_recent(*self._recent_request)
            return
        self._recent_request = None
        self._browse(file, remember=True)

    def reopen_recent(self, uri, connection):
        """사용자가 고른 최근 항목만 연결한다. 앱 시작/메뉴 표시에서는 부르지 않는다."""
        if self.closed:
            return
        from .network import relative_media
        try:
            relative = relative_media(connection, uri)
        except ValueError:
            self.status.set_text('최근 파일의 연결 폴더를 확인할 수 없습니다. 저장된 서버에서 영상을 다시 선택하세요.')
            return
        self._recent_request = (uri, connection)
        if not self._load_uri(connection):
            return
        self._browse(Gio.File.new_for_uri(connection), target=relative)

    def _set_busy(self, busy):
        self.busy = busy
        self.content.set_visible_child_name('loading' if busy else 'files')
        self.spinner.set_spinning(busy)
        for widget in (self.name, self.address, self.protocol):
            widget.set_sensitive(not busy)
        self.port.set_sensitive(not busy and PROTOCOLS[self.protocol.get_selected()] != 'nfs')
        self.connect_button.set_sensitive(not busy)
        self.cancel_button.set_sensitive(busy)
        self.files.set_sensitive(not busy)
        self.up.set_sensitive(not busy and self.current is not None and self.current.get_parent() is not None
                              and (not hasattr(self.browser, 'can_go_up') or self.browser.can_go_up(self.current)))
        self.refresh.set_sensitive(not busy and self.current is not None)

    def _browse(self, file, remember=False, target=None):
        if file is None or self.closed:
            return
        self.generation += 1
        generation = self.generation
        self._set_busy(True)
        self.status.set_text('이 컴퓨터의 관리자 인증 후 읽기 전용 NFS 연결을 준비합니다…'
                             if file.has_uri_scheme('nfs') else '서버에 연결하고 폴더를 읽고 있습니다…')
        def done(result, message):
            if self.closed or generation != self.generation:
                return
            self._set_busy(False)
            if result is None:
                self.status.set_text(redact(message))
                return
            self.current, entries = result
            if self.session is not None:
                self.session.last_location = self.current
            if remember:
                server = Server(self.name.get_text().strip() or f'{file.get_uri_scheme().upper()} 서버', file.get_uri())
                if self.session is not None:
                    self.session.last_server = server
                if self.can_save_servers and not any(s.uri == server.uri for s in self.saved):
                    try:
                        self.store.save(self.saved + [server])
                        self.saved.append(server)
                        self._saved_rows()
                    except (OSError, ValueError):
                        message = (message + '\n' if message else '') + '연결했지만 서버 정보를 저장하지 못했습니다. 저장 권한을 확인하세요.'
            uri = (self.browser.display_location(self.current)
                   if hasattr(self.browser, 'display_location') else self.current.get_uri())
            self.location.set_text(f'{server_label(Server(self.name.get_text(), uri))} · {location_label(uri)}')
            self.connection_form.set_expanded(False)
            if hasattr(self.browser, 'read_only') and self.browser.read_only(self.current):
                self.storage_notice.set_text('읽기 전용 NFS 연결 · 메모와 핀 이미지는 이 컴퓨터에 저장합니다.\n서버 등록 정보는 종료 후에도 유지됩니다.')
            else:
                self.storage_notice.set_text(self.storage_default)
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
            self.status.set_text(redact(message) or ('폴더가 비어 있습니다.' if not entries else '폴더를 열거나 재생할 영상을 선택하세요.'))
            if target is not None:
                if self.session is not None:
                    self.session.last_server = Server(f'{file.get_uri_scheme().upper()} 서버', file.get_uri())
                self.status.set_text('연결됨 · 최근 영상을 열고 있습니다…')
                target_file = self.current.resolve_relative_path(target)
                self._activate(target_file, False)
                if self.closed and self.session is not None:
                    self.session.last_location = target_file.get_parent()
                if not self.closed:
                    self.status.set_text('최근 영상을 열지 못했습니다. 파일·메모 저장 상태를 확인하거나 다른 영상을 선택하세요.')
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
        self.spinner.set_spinning(False)
        return False
