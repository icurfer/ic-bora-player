"""GIO가 Windows에서 원래 명령줄을 다시 읽는 차이를 보정한다."""
import sys
import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gio


class WindowsApplication(Adw.Application):
    def run(self, argv=None):
        self._windows_argv = list(sys.argv if argv is None else argv)
        try:
            return super().run(argv)
        finally:
            self._windows_argv = None

    def do_local_command_line(self, arguments):
        normalized = getattr(self, "_windows_argv", None)
        if normalized is None:
            normalized = sys.argv
        try:
            self.register(None)
            files = [Gio.File.new_for_commandline_arg(arg) for arg in normalized[1:]]
            if files:
                self.open(files, "")
            else:
                self.activate()
            return True, arguments, 0
        except Exception as exc:
            print(f"Bora 실행 실패: {exc}", file=sys.stderr)
            return True, arguments, 1
