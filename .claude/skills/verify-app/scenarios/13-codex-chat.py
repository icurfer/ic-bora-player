#!/usr/bin/env python3
"""격리된 GTK 창에서 Codex 대화 흐름·입력·저장·전환을 모의 응답으로 검증한다.

실제 계정/API/사용자 파일은 쓰지 않는다. BORA_REVIEW_SHOTS=/tmp/... 로 캡처 위치 지정.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
TEMP = tempfile.TemporaryDirectory(prefix="bora-codex-gui-")
folder = Path(TEMP.name)
for key, suffix in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                    ("XDG_DATA_HOME", "data")):
    os.environ[key] = str(folder / suffix)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk
from bora.app import BoraApplication
import bora.ai.panel as panel_module

results = []


def check(name, condition):
    results.append(bool(condition))
    print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
    assert condition, name


def pump(seconds=.15):
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending() and time.monotonic() < end:
            ctx.iteration(False)
        time.sleep(.01)


def wait_for(condition, timeout=3):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        pump(.05)
    return condition()


def shot(name, window):
    target = os.environ.get("BORA_REVIEW_SHOTS")
    if target:
        paused = window.player.paused
        window.player.paused = True
        paintable = Gtk.WidgetPaintable.new(window)
        try:
            window.queue_draw()
            node = None
            for _attempt in range(10):
                pump(.1)
                snapshot = Gtk.Snapshot.new()
                paintable.snapshot(snapshot, window.get_width(), window.get_height())
                node = snapshot.to_node()
                if node is not None:
                    break
            if node is None:
                raise RuntimeError("GTK 캡처를 만들지 못했습니다")
            path = Path(target)
            path.mkdir(parents=True, exist_ok=True)
            texture = window.get_renderer().render_texture(node, None)
            texture.save_to_png(str(path / f"{name}.png"))
        finally:
            paintable.set_widget(None)
            window.player.paused = paused


class FakeAsk:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.running = False
        self.cancelled = False

    def ask(self, question):
        self.question = question
        self.running = True
        return True

    def cancel(self):
        self.running = False
        self.cancelled = True


class Probe(BoraApplication):
    def do_activate(self):
        super().do_activate()
        self.win = self.props.active_window
        self.win.player.volume = 0
        GLib.timeout_add(1400, self.run_checks)

    def run_checks(self):
        w = self.win
        try:
            a, b = folder / "a.mp4", folder / "b.mp4"
            w.toggle_notes(True)
            notes = w._notes
            notes._buffer.set_text("사용자가 작성한 메모")
            notes.save()
            chat = w._chat
            check("영상별 대화 열기", chat.load_for(a))
            w.show_chat()
            pump()
            shot("01-empty", w)
            check("메모 위·Codex 아래 동시 표시", w._study.get_orientation() == Gtk.Orientation.VERTICAL
                  and w._study.get_start_child() is notes and w._study.get_end_child() is chat
                  and notes.get_mapped() and chat.get_mapped())
            old_position = w._study.get_position()
            w._study.set_position(old_position + 35)
            pump()
            check("세로 구분선 높이 조절", w._study.get_position() != old_position)
            w._study.set_position(old_position)
            check("메모와 대화 입력 분리", chat._input.get_buffer() is not notes._buffer)
            chat.set_question("긴 한국어 질문입니다. 이 장면을 간단히 설명해 주세요.")
            pump()
            check("입력 포커스 재생 단축키 보호", w._typing() and not w._on_key(
                None, Gdk.KEY_space, 0, Gdk.ModifierType(0)))
            with patch.object(panel_module, "ensure_ready", return_value=(True, "ready")), \
                    patch.object(panel_module, "AskRunner", FakeAsk):
                check("Ctrl+Enter 전송", chat._on_key(None, Gdk.KEY_Return, 0,
                                                      Gdk.ModifierType.CONTROL_MASK))
                request = chat._runner
                check("질문에 메모 맥락 포함", "사용자가 작성한 메모" in request.question.note_text)
                check("답변 중 보내기 비활성·중지 활성", not chat.send_button.get_sensitive()
                      and chat.stop_button.get_sensitive())
                request.callbacks["on_delta"]("첫 답변입니다.\n\n긴 경로 " + "/example" * 30)
                pump()
                check("대화 응답이 메모를 바꾸지 않음", notes._text() == "사용자가 작성한 메모")
                adjustment = chat._scroll.get_vadjustment()
                adjustment.set_value(0)
                request.callbacks["on_delta"]("\n추가 설명입니다.\n" * 15)
                pump()
                check("지난 대화 읽는 동안 자동 스크롤하지 않음", adjustment.get_value() < 5)
                notes._buffer.insert(notes._buffer.get_end_iter(), "\n응답 중에도 메모 편집")
                notes.save()
                shot("02-streaming", w)
                request.callbacks["on_done"](None, {})
                pump()
                check("답변 완료 버튼 상태", chat._runner is None and
                      chat._answer_button.get_sensitive() and not chat.stop_button.get_sensitive())
                chat._answer_button.emit("clicked")
                check("명시적 메모 삽입", "첫 답변입니다." in notes._text() and
                      "응답 중에도 메모 편집" in notes._text())
                check("중복 삽입 방지", not chat._answer_button.get_sensitive())
                w.show_chat()
                chat.context_check.set_active(False)
                chat.set_question("다음 질문")
                chat.send()
                request = chat._runner
                check("맥락 제외 옵션", request.question.note_text == "" and
                      request.question.subtitle_path is None)
                check("이전 대화 전달", len(request.question.history) == 2)
                request.callbacks["on_delta"]("부분 답변")
                pump()
                chat.cancel()
                check("중지 및 상태 보존", request.cancelled and
                      chat.doc.messages[-1].get("status") == "interrupted")
                pump()
                shot("03-stopped", w)
                chat.set_question("남겨 둔 초안")
                check("다른 영상 대화 열기", chat.load_for(b))
                request.callbacks["on_delta"]("이전 영상 늦은 응답")
                pump()
                check("파일 사이 응답 섞이지 않음", not chat.doc.messages)
                chat.load_for(a)
                check("영상별 초안 복원", chat._text(chat._input.get_buffer()) == "남겨 둔 초안")
                check("영상별 기록 복원", len(chat.doc.messages) == 4)
                chat.set_question("오류 재현")
                chat.send()
                chat._runner.callbacks["on_error"]("Codex 로그인 시간이 만료되었습니다. 연결 설정에서 다시 로그인해 주세요.")
                pump(.4)
                print("오류 상태:", chat._status.get_text())
                check("오류 안내 유지", "다시 로그인" in chat._status.get_text())
                shot("04-error", w)
                chat._dirty = True
                with patch.object(chat.doc, "save", side_effect=OSError("test write failure")):
                    check("저장 실패 시 전환 차단", not chat.load_for(b) and chat._path == a)
                check("오류 해결 뒤 저장", chat.prepare_leave())
            from bora.ai import api
            import io
            payload = (b'data: {"type":"response.output_text.delta","delta":"API reply"}\n\n'
                       b'data: {"type":"response.completed","response":{"usage":{}}}\n\n')
            api.save_config('openai', api.DEFAULT_MODEL)
            chat.refresh_provider()
            chat.set_question("API 방식으로 질문")
            with patch.object(api, 'get_key', return_value='test-placeholder'), \
                    patch.object(api, '_open', return_value=io.BytesIO(payload)) as network, \
                    patch.object(panel_module, 'AskRunner', side_effect=AssertionError('Codex fallback')):
                check("API 선택 후 실제 API runner 전송", chat.send())
                check("API 모의 스트림 완료", wait_for(lambda: chat._runner is None))
                check("API 응답 제공자 보존", chat.doc.messages[-1].get('provider') == 'openai'
                      and chat.doc.messages[-1]['content'] == 'API reply')
                check("API Responses 경로 사용", network.call_args.args[1] == 'responses')
                chat._answer_button.emit('clicked')
                check("메모에 API 작성자 구분", 'OpenAI API 답변' in notes._text())
            api.save_config('codex', api.DEFAULT_MODEL)
            chat.refresh_provider()
            w.set_default_size(960, 560)
            pump(.4)
            check("기존 960x560에서 두 입력 표시", notes._view.get_mapped() and chat._input.get_mapped()
                  and w.get_height() == 560)
            shot("05-compact", w)
            w.set_default_size(720, 560)
            pump(.4)
            w._paned.set_position(w.get_width() - 340)
            pump(.2)
            print(f"좁은 창 요청 720x560 / 실제 {w.get_width()}x{w.get_height()}, 대화폭 {chat.get_width()}")
            check("좁은 창 전송·질문 접근", chat.send_button.get_mapped() and chat._input.get_height() >= 24)
            shot("05-narrow", w)
            with patch.object(panel_module, "check_connection", return_value="ChatGPT 로그인 준비됨"):
                chat._check_connection()
                wait_for(lambda: not chat._checking)
                check("연결 확인 비동기 완료", not chat._checking and "준비됨" in chat._status.get_text())
            style = Adw.StyleManager.get_default()
            original_scheme = style.get_color_scheme()
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
            pump(.2)
            shot("06-light", w)
            style.set_color_scheme(original_scheme)
            before = len(chat.doc.messages)
            chat._confirm_new()
            pump()
            dialog = next(d for d in Gtk.Window.list_toplevels() if isinstance(d, Gtk.MessageDialog))
            dialog.response(Gtk.ResponseType.CANCEL)
            check("새 대화 취소 시 기록 유지", len(chat.doc.messages) == before)
            chat._confirm_new()
            pump()
            dialog = next(d for d in Gtk.Window.list_toplevels() if isinstance(d, Gtk.MessageDialog))
            dialog.response(Gtk.ResponseType.ACCEPT)
            check("명시 확인 후 대화 초기화", not chat.doc.messages and "첫 답변입니다." in notes._text())
            broken = panel_module.Conversation(b)
            broken.path.parent.mkdir(parents=True, exist_ok=True)
            broken.path.write_text("{broken json", encoding="utf-8")
            w.open_path(b)
            pump()
            check("손상된 대화가 영상 재생을 막지 않음", w.current_path == b and chat.doc is None
                  and chat._path == b and not chat.send_button.get_sensitive())
            check("손상된 기록을 그대로 보존", broken.path.read_text() == "{broken json")
            check("정상 종료", w._on_close() is False)
        except Exception:
            import traceback
            traceback.print_exc()
            results.append(False)
        finally:
            if w.player.alive:
                w.player.close()
            self.quit()
        return False


def main():
    video = folder / "a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30:duration=30", "-c:v", "libx264",
                    "-preset", "ultrafast", str(video)], check=True)
    (folder / "b.mp4").write_bytes(video.read_bytes())
    Probe(non_unique=True).run([sys.argv[0], str(video)])
    print(f"{sum(results)}/{len(results)} 통과")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
