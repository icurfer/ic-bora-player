"""GTK 응답용 마크다운 표시. 원본은 버퍼에 보존하고 HTML은 실행하지 않는다."""
import re
from html import escape

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk, Pango


def inline(text):
    """지원하는 인라인 표시만 Pango로 바꾼다. 입력 마크업은 항상 이스케이프한다."""
    pattern = r'(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|~~[^~\n]+~~)'
    parts = re.split(pattern, text)
    for index in range(1, len(parts), 2):
        part = parts[index]
        if part.startswith('`'):
            parts[index] = '<tt>' + escape(part[1:-1]) + '</tt>'
        elif part.startswith(('**', '__')):
            parts[index] = '<b>' + escape(part[2:-2]) + '</b>'
        elif part.startswith('~~'):
            parts[index] = '<s>' + escape(part[2:-2]) + '</s>'
        else:
            parts[index] = '<i>' + escape(part[1:-1]) + '</i>'
    for index in range(0, len(parts), 2):
        parts[index] = escape(parts[index])
    return ''.join(parts)


class MarkdownView(Gtk.Box):
    """스트리밍 버퍼를 읽어 제목, 목록, 표, 코드와 강조를 표시한다."""
    def __init__(self, buffer):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        self.buffer = buffer
        self._pending = 0
        buffer.connect('changed', self._changed)
        self.render()

    def _changed(self, *_):
        if not self._pending:
            self._pending = GLib.timeout_add(60, self.render)

    @staticmethod
    def label(text, *, markup=True):
        label = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, hexpand=True,
                          width_chars=1, max_width_chars=60)
        if markup:
            label.set_markup(inline(text))
        else:
            label.set_text(text)
        return label

    def render(self):
        self._pending = 0
        child = self.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.remove(child)
            child = following
        lines = self.buffer.get_text(*self.buffer.get_bounds(), True).splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.lstrip().startswith('```'):
                code = []
                index += 1
                while index < len(lines) and not lines[index].lstrip().startswith('```'):
                    code.append(lines[index])
                    index += 1
                label = self.label('\n'.join(code), markup=False)
                label.add_css_class('monospace')
                self.append(label)
            elif (index + 1 < len(lines) and '|' in line
                  and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', lines[index + 1])):
                rows = [line]
                index += 2
                while index < len(lines) and '|' in lines[index] and lines[index].strip():
                    rows.append(lines[index])
                    index += 1
                grid = Gtk.Grid(column_spacing=12, row_spacing=6, column_homogeneous=True)
                for row, content in enumerate(rows):
                    for column, cell in enumerate(content.strip().strip('|').split('|')):
                        label = self.label(cell.strip())
                        if row == 0:
                            label.add_css_class('heading')
                        grid.attach(label, column, row, 1, 1)
                self.append(grid)
                continue
            elif line.strip():
                heading = re.match(r'^\s{0,3}(#{1,6})\s+(.*)', line)
                if heading:
                    label = self.label(heading[2])
                    label.add_css_class('heading')
                    label.set_margin_top(6)
                else:
                    line = re.sub(r'^(\s*)[-*+]\s+', r'\1• ', line)
                    label = self.label(line.removeprefix('> '))
                self.append(label)
            else:
                self.append(Gtk.Box(height_request=4))
            index += 1
        return False
