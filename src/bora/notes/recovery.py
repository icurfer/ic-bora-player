"""저장 오류가 닫기 동작을 영구히 막지 않도록 명시적인 복구 선택을 제공한다."""
import os
from pathlib import Path
import tempfile
from gi.repository import GLib, Gtk
from ..platform import paths


def copy_text(text, destination=None, *, suffix='.md'):
    """원본 메모를 건드리지 않고 본문 사본을 원자적으로 보관한다."""
    directory = Path(destination).parent if destination else paths.data_dir() / 'recovered-notes'
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='recovered-note-', suffix=suffix, dir=directory)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if destination:
            temporary.replace(destination)
        return Path(destination) if destination else temporary
    except (OSError, UnicodeError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def prepare_close(panel):
    snapshot = (panel.doc, panel._text())
    if getattr(panel, '_close_approved', None) == snapshot:
        return True
    if panel.prepare_leave():
        return True
    if getattr(panel, '_save_failure_dialog', None) is not None:
        panel._save_failure_dialog.show()
        return False
    title = getattr(panel, 'recovery_title', '메모를 저장하지 못했습니다')
    dialog = Gtk.Dialog(title=title, transient_for=panel.window, modal=True,
                        default_width=420, resizable=False)
    content = dialog.get_content_area()
    for name in ('top', 'bottom', 'start', 'end'):
        getattr(content, 'set_margin_' + name)(18)
    content.set_spacing(10)
    content.append(Gtk.Label(label=title, xalign=0, wrap=True, css_classes=['title-3']))
    content.append(Gtk.Label(label='본문을 이 컴퓨터에 복구 저장하거나 다른 위치에 저장한 뒤 종료할 수 있습니다. '
        '첨부 이미지는 원래 위치에 유지됩니다. 저장하지 않고 종료하면 미저장 변경이 사라집니다.',
        xalign=0, wrap=True, max_width_chars=42))
    dialog._response_buttons = {}
    for label, code in (('복구 저장 후 종료', Gtk.ResponseType.APPLY),
                        ('다른 위치에 저장', Gtk.ResponseType.ACCEPT),
                        ('저장하지 않고 종료', Gtk.ResponseType.REJECT),
                        ('계속 편집', Gtk.ResponseType.CANCEL)):
        button = Gtk.Button(label=label)
        button.connect('clicked', lambda _b, value=code: dialog.response(value))
        if code == Gtk.ResponseType.REJECT:
            button.add_css_class('destructive-action')
        if code == Gtk.ResponseType.APPLY:
            button.add_css_class('suggested-action')
            dialog.set_default_widget(button)
        dialog._response_buttons[code] = button
        content.append(button)
    panel._save_failure_dialog = dialog

    def close_with_approval():
        panel._cancel_autosave()
        panel._close_approved = (panel.doc, panel._text())
        def close():
            panel.window.close()
            return False
        GLib.timeout_add(1, close)

    def store(destination=None):
        try:
            saved = copy_text(panel._text(), destination, suffix=panel.doc.path.suffix or '.md')
        except (OSError, UnicodeError):
            panel.window.toast('복구 본문도 저장하지 못했습니다. 다른 위치에 저장하거나 계속 편집을 선택하세요.')
            prepare_close(panel)
            return
        panel.window.toast(f'메모 본문 사본 저장: {saved}')
        close_with_approval()

    def response(widget, result):
        panel._save_failure_dialog = None
        widget.destroy()
        if result == Gtk.ResponseType.REJECT:
            close_with_approval()
        elif result == Gtk.ResponseType.APPLY:
            store()
        elif result == Gtk.ResponseType.ACCEPT:
            chooser = Gtk.FileChooserNative(title='메모 본문 사본 저장', transient_for=panel.window,
                modal=True, action=Gtk.FileChooserAction.SAVE, accept_label='저장 후 종료', cancel_label='취소')
            chooser.set_current_name(panel.doc.path.name if panel.doc else '메모.md')
            panel._save_failure_dialog = chooser
            def chosen(source, answer):
                file = source.get_file() if answer == Gtk.ResponseType.ACCEPT else None
                panel._save_failure_dialog = None
                source.destroy()
                if file and file.get_path():
                    store(Path(file.get_path()))
            chooser.connect('response', chosen)
            chooser.show()
    dialog.connect('response', response)
    dialog.present()
    return False
