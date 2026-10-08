"""영상별 Codex 대화. 메모는 사용자가 답변을 넣을 때만 바꾼다."""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk, Pango

from .client import AskRunner, check_connection, ensure_ready
from .context import Question
from .images import ImageError, find_images
from .api import AIError, APIAskRunner, load_config, check_api, get_key
from .history import Conversation
from ..notes.model import format_stamp


class ChatPanel(Gtk.Box):
    """메모 아래에 함께 표시하는 대화 영역. 모든 worker 콜백은 UI 스레드로 전달한다."""

    def __init__(self, owner):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         width_request=320, margin_start=10, margin_end=10,
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

        header = Gtk.Box(spacing=6)
        title = Gtk.Label(label="AI 대화", xalign=0, hexpand=True)
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
        self.append(header)
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
        self.append(self.context_check)
        self.image_check = Gtk.CheckButton(label="메모 이미지 첨부", active=True)
        self.image_check.set_tooltip_text("현재 메모의 로컬 PNG·JPEG·WEBP 이미지 · 최대 4장/20MB · 전송 시 사용량에 포함")
        self.image_check.connect("toggled", lambda *_: self.refresh_images())
        self.append(self.image_check)
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

    def load_for(self, path):
        path = Path(path)
        if self._path == path and self.doc is not None:
            return True
        if not self.prepare_leave():
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
            self._image_status.set_text("이미지는 보내지 않습니다")
            return
        try:
            images = self._note_images()
            label = f"메모 이미지 {len(images)}장 · 전송 시 포함" if images else "메모 이미지 없음"
            self._image_status.set_text(label)
            self._image_status.set_tooltip_text("\n".join(p.name for p in images))
        except ImageError as exc:
            self._image_status.set_text(str(exc))
            self._image_status.set_tooltip_text(None)

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
        return self._save()

    def _sync_buttons(self):
        running = self._runner is not None
        self.send_button.set_sensitive(self.doc is not None and not running and
                                       bool(self._text(self._input.get_buffer()).strip()))
        self.stop_button.set_sensitive(running)
        self._action_stack.set_visible_child_name("stop" if running else "send")
        self.new_button.set_sensitive(self.doc is not None and not running)
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
                    "영상에서 궁금한 내용을 물어보세요.\n답변은 ‘메모에 넣기’로 옮길 수 있습니다.")
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
        view = Gtk.TextView(buffer=buffer, editable=False, cursor_visible=False,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, can_focus=True)
        box.append(view)
        button = None
        if assistant:
            button = Gtk.Button(label="메모에 넣기", halign=Gtk.Align.START,
                                sensitive=complete and bool(message.get("content")))
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
            image_paths = self._note_images()
        except ImageError as exc:
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
        user_message = {"role": "user", "content": text, "timestamp": self._position,
                        "attachments": [p.name for p in image_paths]}
        self.doc.messages.append(user_message)
        self._add_message(user_message)
        self._answer = ""
        self._answer_message = {"role": "assistant", "content": "", "timestamp": self._position,
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
        self._status.set_text("답변 완료 · 필요한 답변을 메모에 넣어 보세요.")
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
        stamp = format_stamp(message["timestamp"]) + " " if "timestamp" in message else ""
        partial = " (미완료)" if message.get("status") in ("error", "interrupted") else ""
        author = "OpenAI API" if message.get("provider") == "openai" else "Codex"
        text = "\n\n### " + stamp + author + " 답변" + partial + "\n\n" + message.get("content", "") + "\n"
        notes._buffer.insert(notes._buffer.get_end_iter(), text)
        notes.save()
        button.set_label("메모에 넣음")
        button.set_sensitive(False)
        self.window.toast("답변을 메모에 넣었지만 저장하지 못했습니다. 메모의 저장 상태를 확인해 주세요."
                          if notes.doc.dirty else "AI 답변을 메모 끝에 넣었습니다")

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
