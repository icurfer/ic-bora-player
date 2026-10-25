"""영상별 Codex 대화. 닫기와 영상 전환에서 새 대화를 시각과 함께 메모에 보존한다."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from .client import AskRunner, check_connection, ensure_ready
from .context import Question
from .images import ImageError, find_images, load_images, MAX_IMAGES
from .api import AIError, APIAskRunner, load_config, check_api, get_key
from .history import Conversation
from ..notes.model import format_stamp
from ..ui import PANEL_WIDTH
from ..notes.model import NoteDocument
from .study import qa_text, StudyPreview, pending_transcript, message_marker, question_for
from .markdown import MarkdownView


class ChatPanel(Gtk.Box):
    """메모 아래에 함께 표시하는 대화 영역. 모든 worker 콜백은 UI 스레드로 전달한다."""

    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         width_request=PANEL_WIDTH, margin_start=10, margin_end=10,
                         margin_top=4, margin_bottom=4)
        self.window = owner
        self.doc = None
        self._path = None
        self._runner = None
        self._generation = 0
        self._answer = ""
        self._answer_buffer = None
        self._answer_button = None
        self._answer_message = None
        self._position = 0.0
        self._drafts = {}
        self._dirty = False
        self._save_failed = False
        self._checking = False
        self._captures = {}
        self._study_preview = None

        header = Gtk.Box(spacing=6)
        title = Gtk.Label(label="학습 에이전트", xalign=0, hexpand=True)
        title.add_css_class("heading")
        header.append(title)
        self._help = Gtk.Button(label="연결 설정", tooltip_text="AI 연결 방식·로그인·API 키 설정")
        self._help.connect("clicked", lambda *_: self.window.show_ai_settings())
        header.append(self._help)
        self.connection_button = Gtk.Button(icon_name="network-transmit-receive-symbolic",
                                           tooltip_text="선택한 AI 연결 확인")
        self.connection_button.connect("clicked", self._check_connection)
        header.append(self.connection_button)
        self.new_button = Gtk.Button(icon_name="document-new-symbolic", tooltip_text="새 대화")
        self.new_button.connect("clicked", self._confirm_new)
        header.append(self.new_button)
        self.close_button = Gtk.Button(icon_name="window-close-symbolic",
                                       tooltip_text="대화를 메모에 기록하고 학습 에이전트 닫기")
        self.close_button.connect("clicked", lambda *_: self.window.toggle_agent())
        header.append(self.close_button)
        self.append(header)
        tools = Gtk.Box(spacing=6)
        self.capture_button = Gtk.Button(label="화면 첨부", tooltip_text="현재 영상 프레임 캡처 · 자막 포함")
        self.capture_button.connect("clicked", lambda *_: self.capture_frame())
        tools.append(self.capture_button)
        self.study_button = Gtk.Button(label="학습메모 AI 요약", tooltip_text="전체 메모를 AI로 요약 · 현재 연결의 사용량 적용")
        self.study_button.connect("clicked", lambda *_: self.make_study())
        tools.append(self.study_button)
        self.append(tools)
        self._capture_box = Gtk.Box(spacing=4)
        self.append(self._capture_box)
        self._status = Gtk.Label(label="로컬 Codex · ChatGPT 사용 한도 적용", xalign=0,
                                wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        self._status.add_css_class("dim-label")
        self.append(self._status)

        self._messages = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._scroll = Gtk.ScrolledWindow(child=self._messages, vexpand=True,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER,
                                         min_content_height=32)
        self.append(self._scroll)
        self.context_check = Gtk.CheckButton(label="주변 자막·메모 일부 함께 보내기", active=True)
        self.context_check.set_tooltip_text("현재 시각·질문·기존 대화는 항상 전달합니다. 모델 응답은 온라인으로 처리됩니다.")
        context_options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        context_options.append(self.context_check)
        self.image_check = Gtk.CheckButton(label="메모 이미지 첨부", active=True)
        self.image_check.set_tooltip_text("현재 메모의 로컬 PNG·JPEG·WEBP 이미지 · 최대 4장/20MB · 전송 시 사용량에 포함")
        self.image_check.connect("toggled", lambda *_: self.refresh_images())
        context_options.append(self.image_check)
        self._context_options = Gtk.Expander(label="전송 맥락: 자막·메모·이미지", child=context_options)
        self.append(self._context_options)
        for option in (self.context_check, self.image_check):
            option.connect("toggled", lambda *_: self._sync_context_options())
        self._image_status = Gtk.Label(label="메모 이미지 없음", xalign=0, wrap=True,
                                       wrap_mode=Pango.WrapMode.WORD_CHAR)
        self._image_status.add_css_class("dim-label")
        self.append(self._image_status)
        self._context_label = Gtk.Label(label="영상을 열면 이 영상의 대화가 표시됩니다.",
                                       xalign=0, wrap=True)
        self._context_label.add_css_class("dim-label")
        self._input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                   top_margin=6, bottom_margin=6, left_margin=6, right_margin=6)
        self._input.set_tooltip_text("질문 입력 · Enter 줄바꿈 · Ctrl+Enter 보내기")
        self._input.update_property([Gtk.AccessibleProperty.LABEL], ["AI에게 질문"])
        input_scroll = Gtk.ScrolledWindow(child=self._input, min_content_height=36,
                                         max_content_height=72, propagate_natural_height=True,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        input_scroll.add_css_class("frame")
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self._input.add_controller(keys)
        self._input.get_buffer().connect("changed", lambda *_: self._sync_buttons())
        footer = Gtk.Box(spacing=6)
        input_scroll.set_hexpand(True)
        footer.append(input_scroll)
        self.stop_button = Gtk.Button(label="중지", sensitive=False)
        self.stop_button.connect("clicked", lambda *_: self.cancel())
        self.send_button = Gtk.Button(label="보내기", sensitive=False, tooltip_text="보내기 (Ctrl+Enter)")
        self.send_button.add_css_class("suggested-action")
        self.send_button.connect("clicked", lambda *_: self.send())
        self._action_stack = Gtk.Stack(valign=Gtk.Align.END)
        self._action_stack.add_named(self.send_button, "send")
        self._action_stack.add_named(self.stop_button, "stop")
        footer.append(self._action_stack)
        self.append(footer)
        self._key_hint = Gtk.Label(label="Ctrl+Enter 보내기 · Enter 줄바꿈", xalign=0)
        self._key_hint.add_css_class("dim-label")
        self.append(self._key_hint)
        self.window._notes._buffer.connect("changed", lambda *_: self.refresh_images())
        self.refresh_provider()
        self._render()

    def refresh_provider(self):
        if self._runner is not None:
            return
        try:
            config = load_config()
            text = ("OpenAI API · " + config["model"] + " · 별도 사용 요금"
                    if config["provider"] == "openai" else "로컬 Codex · ChatGPT 사용 한도 적용")
        except AIError as exc:
            text = str(exc)
        self._status.set_text(text)

    @staticmethod
    def _text(buffer):
        return buffer.get_text(*buffer.get_bounds(), True)

    def focus_editor(self):
        self._input.grab_focus()

    def set_question(self, text):
        self._input.get_buffer().set_text(text)
        self.focus_editor()

    def load_for(self, path, *, prepared=False):
        path = Path(path)
        if self._path == path and self.doc is not None:
            return True
        if not prepared and not self.prepare_leave():
            return False
        if self._path is not None:
            self._drafts[str(self._path)] = self._text(self._input.get_buffer())
        try:
            document = Conversation(path)
        except (OSError, ValueError, UnicodeError):
            self.cancel()
            self.doc, self._path = None, path
            self._dirty = False
            self._save_failed = False
            self._input.get_buffer().set_text("")
            self._render()
            self._status.set_text("대화 기록을 열지 못했습니다. 기록 파일과 접근 권한을 확인해 주세요.")
            self._sync_buttons()
            return True
        self.cancel()
        self.doc, self._path = document, path
        self._dirty = False
        self._save_failed = False
        self._input.get_buffer().set_text(self._drafts.get(str(path), ""))
        self._render_captures()
        self.refresh_provider()
        self.refresh_context()
        self._render()
        self._sync_buttons()
        return True

    def _note_images(self):
        notes = self.window._notes
        if not self.image_check.get_active() or not notes.doc:
            return []
        if self._path != getattr(self.window, "_current", None):
            return []
        return find_images(notes._text(), notes.doc.path)

    def refresh_images(self):
        if not self.image_check.get_active():
            self._image_status.set_text(f"메모 이미지 제외 · 화면 첨부 {len(self._captures.get(str(self._path), []))}장")
            return
        try:
            images = self._note_images()
            label = f"메모 이미지 {len(images)}장 · 전송 시 포함" if images else "메모 이미지 없음"
            self._image_status.set_text(label + f" · 화면 {len(self._captures.get(str(self._path), []))}장")
            self._image_status.set_tooltip_text("\n".join(p.name for p in images))
        except ImageError as exc:
            self._image_status.set_text(str(exc))
            self._image_status.set_tooltip_text(None)
            self._context_options.set_expanded(True)

    def _sync_context_options(self):
        parts = []
        if self.context_check.get_active():
            parts.append("자막·메모")
        if self.image_check.get_active():
            parts.append("메모 이미지")
        self._context_options.set_label("전송 맥락: " + ("·".join(parts) if parts else "대화·시각만"))

    def refresh_context(self):
        self.refresh_images()
        has_subtitle = bool(getattr(self.window, "_plan", None))
        if self._path is not None:
            self._context_label.set_text("현재 시각을 함께 보냅니다 · " +
                                         ("주변 자막 포함 가능" if has_subtitle else "자막 없음"))

    def _save(self):
        if self.doc is None or not self._dirty:
            return True
        try:
            self.doc.save()
        except (OSError, ValueError):
            self._save_failed = True
            self._status.set_text("대화 저장 실패 — 내용을 보존했습니다. 저장 위치를 확인해 주세요.")
            return False
        self._dirty = False
        if self._save_failed:
            self._status.set_text("대화를 저장했습니다.")
            self._save_failed = False
        return True

    def prepare_leave(self):
        self.cancel()
        if not self._save():
            return False
        if not self.record_notes():
            return False
        if self._study_preview is not None:
            self._study_preview.close()
        return True

    def record_notes(self):
        if self.doc is None or not self.doc.messages:
            return True
        if not self.window._ensure_notes():
            return False
        text = pending_transcript(self.doc.messages, self.window._notes._text())
        return not text or self.append_note(text, self._path, reveal=False)

    def _sync_buttons(self):
        running = self._runner is not None
        self.send_button.set_sensitive(self.doc is not None and not running and
                                       bool(self._text(self._input.get_buffer()).strip()))
        self.stop_button.set_sensitive(running)
        self._action_stack.set_visible_child_name("stop" if running else "send")
        self.new_button.set_sensitive(self.doc is not None and not running)
        self.study_button.set_sensitive(self.doc is not None and not running)
        self.capture_button.set_sensitive(self.doc is not None and not running)
        self.connection_button.set_sensitive(not self._checking and not running)

    def _on_key(self, _controller, key, _code, modifiers):
        if (key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and modifiers & Gdk.ModifierType.CONTROL_MASK
                and not modifiers & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)):
            self.send()
            return True
        return False

    def _render(self):
        child = self._messages.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._messages.remove(child)
            child = following
        if not self.doc or not self.doc.messages:
            text = ("이 영상의 대화 기록을 열 수 없습니다.\n기존 기록은 보존했습니다."
                    if self._path is not None and self.doc is None else
                    "영상에서 궁금한 내용을 물어보세요.\n닫을 때 새 대화를 영상 시각과 함께 메모에 기록합니다.")
            label = Gtk.Label(label=text,
                              wrap=True, xalign=0)
            label.add_css_class("dim-label")
            self._messages.append(label)
        else:
            for message in self.doc.messages:
                self._add_message(message, complete=True)

    def _add_message(self, message, complete=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        assistant = message.get("role") == "assistant"
        label = ("OpenAI API" if message.get("provider") == "openai" else "Codex") if assistant else "나"
        if "timestamp" in message:
            label += " · " + format_stamp(message["timestamp"])
        if message.get("status") == "interrupted":
            label += " · 중지됨"
        elif message.get("status") == "error":
            label += " · 미완료"
        if not assistant and message.get("attachments"):
            label += f" · 이미지 {len(message['attachments'])}장"
        title = Gtk.Label(label=label, xalign=0)
        title.add_css_class("heading")
        box.append(title)
        buffer = Gtk.TextBuffer()
        buffer.set_text(message.get("content", ""))
        view = (MarkdownView(buffer) if assistant else
                Gtk.TextView(buffer=buffer, editable=False, cursor_visible=False,
                             wrap_mode=Gtk.WrapMode.WORD_CHAR, can_focus=True))
        box.append(view)
        button = None
        if assistant:
            index = next((i for i, item in enumerate(self.doc.messages) if item is message), None)
            notes = self.window._notes
            recorded = (index is not None and notes.doc is not None
                        and notes.doc.path == NoteDocument.path_for(self._path)
                        and message_marker(message, index) in notes._text())
            button = Gtk.Button(label="메모에 넣음" if recorded else "메모에 넣기", halign=Gtk.Align.START,
                                sensitive=complete and bool(message.get("content")) and not recorded)
            path = self._path
            button.connect("clicked", lambda b: self._insert_note(b, path, message))
            box.append(button)
        self._messages.append(box)
        return buffer, button

    def _at_bottom(self):
        adjustment = self._scroll.get_vadjustment()
        return adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 40

    def _to_bottom(self):
        adjustment = self._scroll.get_vadjustment()
        adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()))
        return False

    def send(self):
        text = self._text(self._input.get_buffer()).strip()
        if self.doc is None or self._runner is not None or not text:
            return False
        try:
            config = load_config()
        except AIError as exc:
            self._status.set_text(str(exc))
            return False
        if config['provider'] == 'codex':
            ready, hint = ensure_ready()
            if not ready:
                self._status.set_text(hint)
                return False
        try:
            image_paths = self._request_images()
            image_refs = [p.resolve().relative_to(self._path.parent.resolve()).as_posix()
                          for p in image_paths]
        except (ImageError, OSError, ValueError) as exc:
            self._status.set_text(str(exc))
            self.refresh_images()
            return False
        history = [dict(m) for m in self.doc.messages]
        include = self.context_check.get_active()
        notes = self.window._notes
        self._position = self.window.player.time_pos or 0.0
        plan = getattr(self.window, "_plan", None)
        question = Question(text=text, position=self._position, video_title=self._path.stem,
                            subtitle_path=plan.source if include and plan else None,
                            note_text=notes._text() if include and notes.doc else "",
                            note_line=notes._cursor_line() if include and notes.doc else -1,
                            history=history, image_paths=image_paths,
                            note_path=notes.doc.path if notes.doc else None)
        if not self.doc.messages:
            child = self._messages.get_first_child()
            if child:
                self._messages.remove(child)
        user_message = {"id": uuid.uuid4().hex, "role": "user", "content": text, "timestamp": self._position,
                        "attachments": [p.name for p in image_paths],
                        "image_refs": image_refs}
        self.doc.messages.append(user_message)
        self._add_message(user_message)
        self._answer = ""
        self._answer_message = {"reply_to": user_message["id"], "role": "assistant", "content": "", "timestamp": self._position,
                                "status": "completed", "provider": config["provider"]}
        self._answer_buffer, self._answer_button = self._add_message(self._answer_message)
        self._dirty = True
        self._input.get_buffer().set_text("")
        self._generation += 1
        generation = self._generation
        runner_class = APIAskRunner if config["provider"] == "openai" else AskRunner
        options = {"config": config} if config["provider"] == "openai" else {}
        self._runner = runner_class(
            **options,
            on_delta=lambda t: GLib.idle_add(self._dispatch, generation, self._delta, t),
            on_done=lambda c, u: GLib.idle_add(self._dispatch, generation, self._done, c, u),
            on_error=lambda m: GLib.idle_add(self._dispatch, generation, self._error, m))
        self._status.set_text("OpenAI API에 연결하는 중…" if config["provider"] == "openai" else "Codex에 연결하는 중…")
        self._sync_buttons()
        if not self._runner.ask(question):
            self._error("질문을 보내지 못했습니다. AI 연결 설정을 확인해 주세요.")
            return False
        self._save()
        GLib.idle_add(self._to_bottom)
        return True

    def _dispatch(self, generation, handler, *args):
        if generation == self._generation:
            handler(*args)
        return False

    def _delta(self, text):
        follow = self._at_bottom()
        self._answer += text
        self._answer_buffer.insert(self._answer_buffer.get_end_iter(), text)
        self._status.set_text("답변 작성 중… 위에서 메모를 계속 편집할 수 있습니다.")
        if follow:
            GLib.idle_add(self._to_bottom)

    def _finish_answer(self, status="completed"):
        if self._answer_message is not None and self._answer:
            self._answer_message["content"] = self._answer
            self._answer_message["status"] = status
            self.doc.messages.append(self._answer_message)
            self._dirty = True
            self._answer_button.set_sensitive(True)
            if status != "completed":
                title = self._answer_button.get_parent().get_first_child()
                title.set_label(title.get_label() + (" · 중지됨" if status == "interrupted" else " · 미완료"))
        self._answer_message = None
        self._runner = None
        self._sync_buttons()

    def _done(self, _cost, _usage):
        self._finish_answer()
        self._captures.pop(str(self._path), None)
        self._render_captures()
        self.refresh_images()
        self._status.set_text("답변 완료 · 닫을 때 새 대화를 메모에 자동 기록합니다.")
        self._save()

    def _error(self, message):
        if not self._text(self._input.get_buffer()).strip() and self.doc is not None:
            for previous in reversed(self.doc.messages):
                if previous.get("role") == "user":
                    self._input.get_buffer().set_text(previous["content"])
                    break
        if not self._answer and self._answer_buffer is not None:
            self._answer_buffer.set_text("답변을 받지 못했습니다. 연결을 확인한 뒤 다시 보내 주세요.")
        self._finish_answer("error")
        self._status.set_text(message)
        self._save()

    def cancel(self):
        self._generation += 1
        if self._runner is not None:
            self._runner.cancel()
            self._finish_answer("interrupted")
            self._status.set_text("답변을 중지했습니다. 받은 내용은 대화에 남습니다.")
            self._save()

    def _insert_note(self, button, path, message):
        if path != self._path or path != getattr(self.window, "_current", None):
            self._status.set_text("이 답변의 영상을 다시 열어 주세요.")
            return
        notes = self.window._notes
        self.window.toggle_notes(True)
        if notes.doc is None or notes.doc.path != notes.doc.path_for(path):
            self._status.set_text("메모를 먼저 열어 주세요.")
            return
        if message_marker(message, self.doc.messages.index(message)) in notes._text():
            button.set_label("메모에 넣음")
            button.set_sensitive(False)
            return
        question = question_for(self.doc.messages, message)
        markers = '\n'.join(message_marker(m, self.doc.messages.index(m))
                            for m in (question, message) if m is not None)
        if self.append_note(qa_text(self.doc.messages, message) + '\n' + markers + '\n', path):
            button.set_label("메모에 넣음")
            button.set_sensitive(False)

    def append_note(self, text, path, *, reveal=True):
        if path != self._path or path != getattr(self.window, "_current", None):
            self._status.set_text("이 대화의 영상을 다시 열어 주세요.")
            return False
        if reveal:
            self.window.toggle_notes(True)
        notes = self.window._notes
        if notes.doc is None or notes.doc.path != NoteDocument.path_for(path):
            return False
        # 이미 편집/외부 충돌이 있으면 먼저 해결한다. 삽입 후 저장 실패는 버퍼에서 보호한다.
        if not notes.prepare_leave():
            self._status.set_text("메모의 저장 문제를 먼저 해결하세요.")
            return False
        start = notes._buffer.get_char_count()
        notes._buffer.insert(notes._buffer.get_end_iter(), text)
        if not notes.save():
            # 삽입분만 되돌려 재시도 중복을 막고 기존 메모/미리보기는 보존한다.
            notes._buffer.delete(notes._buffer.get_iter_at_offset(start), notes._buffer.get_end_iter())
            notes._cancel_autosave()
            notes.doc.text = notes._text()
            self._status.set_text("메모 저장 실패 — 원문을 보존했습니다. 저장 위치를 확인한 뒤 다시 시도하세요.")
            return False
        self.window.toast("학습메모에 내용을 추가했습니다")
        self._status.set_text("메모에 기록했습니다. 닫을 때 새 대화만 추가합니다.")
        return True

    def make_study(self, *, summarize=True):
        if self.doc is None or self._runner is not None:
            return
        if not self.record_notes():
            return
        if self._study_preview is None:
            self._study_preview = StudyPreview(self)
            if summarize:
                self._study_preview.summarize()
        self._study_preview.present()

    def _request_images(self):
        paths = list(dict.fromkeys(self._note_images() + self._captures.get(str(self._path), [])))
        if len(paths) > MAX_IMAGES:
            raise ImageError("메모 이미지와 화면 첨부는 합계 최대 4장입니다. 첨부를 줄여 주세요.")
        return paths

    def capture_frame(self):
        if self._runner is not None or self._path is None or self._path != getattr(self.window, "_current", None):
            return False
        captures = self._captures.setdefault(str(self._path), [])
        try:
            if len(self._request_images()) >= MAX_IMAGES:
                raise ImageError("최대 4장까지 첨부할 수 있습니다. 기존 첨부를 제거하세요.")
            assets = NoteDocument.assets_dir_for(self._path)
            if not assets.resolve().is_relative_to(self._path.parent.resolve()):
                raise ImageError("영상 폴더 밖으로 연결된 첨부 폴더는 사용할 수 없습니다.")
            path = assets / ("agent-" + uuid.uuid4().hex + ".png")
            self.window.player.screenshot(path, include_subs=True)
            load_images([path], NoteDocument.path_for(self._path))
        except ImageError as exc:
            self._status.set_text(str(exc))
            return False
        except Exception:
            self._status.set_text("영상 화면을 첨부하지 못했습니다. 영상 재생 상태와 첨부 개수·저장 권한을 확인하세요.")
            return False
        captures.append(path)
        self._render_captures()
        self.refresh_images()
        self._status.set_text("현재 영상 화면을 첨부했습니다. 질문을 입력하고 보내세요.")
        return True

    def _render_captures(self):
        child = self._capture_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._capture_box.remove(child)
            child = following
        for path in self._captures.get(str(self._path), []):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            try:
                thumbnail = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 56, 36, True)
                picture = Gtk.Image.new_from_pixbuf(thumbnail)
                picture.set_pixel_size(56)
            except GLib.Error:
                picture = Gtk.Image.new_from_icon_name("image-missing-symbolic")
            picture.set_tooltip_text("현재 영상 캡처 · " + path.name)
            box.append(picture)
            remove = Gtk.Button(label="제거", tooltip_text="전송 첨부에서 제거 · 저장된 이미지 파일은 유지")
            remove.connect("clicked", lambda _button, p=path: self._remove_capture(p))
            box.append(remove)
            self._capture_box.append(box)
        self._capture_box.set_visible(bool(self._captures.get(str(self._path))))

    def _remove_capture(self, path):
        captures = self._captures.get(str(self._path), [])
        if path in captures:
            captures.remove(path)
        self._render_captures()
        self.refresh_images()

    def _check_connection(self, *_args):
        if self._checking:
            return
        self._checking = True
        self.connection_button.set_sensitive(False)
        try:
            config = load_config()
        except AIError as exc:
            self._checking = False
            self._sync_buttons()
            self._status.set_text(str(exc))
            return
        self._status.set_text("AI 연결 확인 중…")

        def work():
            try:
                result = (check_api(get_key(), config["model"]) if config["provider"] == "openai"
                          else check_connection())
            except AIError as exc:
                result = str(exc)
            except Exception:
                result = "AI 연결을 확인하지 못했습니다. 연결 설정을 확인해 주세요."
            GLib.idle_add(done, result)

        def done(result):
            self._checking = False
            self._sync_buttons()
            if self._runner is None:
                try:
                    unchanged = load_config() == config
                except AIError:
                    unchanged = False
                if unchanged:
                    self._status.set_text(str(result))
            return False

        threading.Thread(target=work, daemon=True).start()

    def _confirm_new(self, *_args):
        if self.doc is None or self._runner is not None:
            return
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   text="이 영상의 대화를 지울까요?",
                                   secondary_text="대화 기록을 지우고 새로 시작합니다. 메모에 넣은 답변은 유지됩니다.")
        dialog.add_button("취소", Gtk.ResponseType.CANCEL)
        destructive = dialog.add_button("대화 지우기", Gtk.ResponseType.ACCEPT)
        destructive.add_css_class("destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        path = self._path

        def response(_dialog, answer):
            _dialog.destroy()
            if answer != Gtk.ResponseType.ACCEPT or self._path != path:
                return
            previous = self.doc.messages
            self.doc.messages = []
            self._dirty = True
            if not self._save():
                self.doc.messages = previous
                return
            self._render()
            self._status.set_text("새 대화를 시작합니다.")
        dialog.connect("response", response)
        dialog.present()
