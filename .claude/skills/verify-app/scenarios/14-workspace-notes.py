#!/usr/bin/env python3
"""외부 Codex 작업의 메모 저장·충돌·파일 전환을 격리된 GTK에서 검증한다.

터미널 실행을 모의 처리하므로 Codex 실행·로그인·모델 호출은 하지 않는다.
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
TEMP = tempfile.TemporaryDirectory(prefix="bora-workspace-notes-")
folder = Path(TEMP.name)
for key, suffix in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                    ("XDG_DATA_HOME", "data")):
    os.environ[key] = str(folder / suffix)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk
from bora.app import BoraApplication
from bora.ai.history import Conversation
from bora.ai import workspace

results = []


def check(name, condition):
    results.append(bool(condition))
    print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
    assert condition, name


def pump(seconds=.15):
    end = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < end:
        while context.pending() and time.monotonic() < end:
            context.iteration(False)
        time.sleep(.01)


def wait_for(condition, timeout=3):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        pump(.05)
    return condition()


class Probe(BoraApplication):
    def do_activate(self):
        super().do_activate()
        self.win = self.props.active_window
        self.win.player.volume = 0
        GLib.timeout_add(1200, self.run_checks)

    def run_checks(self):
        w = self.win
        try:
            a, b = folder / "강의 a.mp4", folder / "강의 b.mp4"
            w.toggle_notes(True)
            notes, chat = w._notes, w._chat
            path = notes.doc.path
            check("처음 연 메모는 아직 파일 없음", not path.exists())
            check("Codex 준비가 첫 메모 파일 생성", notes.prepare_codex() and path.is_file())
            check("제목 포함 UTF-8 메모 저장", path.read_text(encoding="utf-8") == notes._text())
            notes._buffer.set_text("사용자 미저장 편집\n이 장면을 설명해 주세요")
            check("실행 전 미저장 편집 존재", path.read_text() != notes._text())
            with patch.object(workspace, "launch") as launch:
                check("현재 줄 Codex 작업 요청", notes.ask_current_line())
                check("비동기 터미널 실행 전달", wait_for(lambda: launch.call_count == 1))
                video_arg, note_arg, sub_arg, question_arg = launch.call_args.args
                check("현재 영상과 메모 폴더 연동", video_arg == a and note_arg == path
                      and note_arg.parent == a.parent and sub_arg is None)
                check("현재 줄을 질문으로 전달", question_arg == "이 장면을 설명해 주세요")
                check("미저장 메모를 저장한 후 전달", "사용자 미저장 편집" in path.read_text()
                      and not notes.doc.dirty)
            original_mtime = path.stat().st_mtime
            external = "Codex가 추가한 설명\n"
            path.write_text(external, encoding="utf-8")
            os.utime(path, (original_mtime - 60, original_mtime - 60))
            notes.refresh_external()
            check("수정 시각이 과거여도 외부 내용 반영", notes._text() == external
                  and not notes.doc.dirty)
            local = external + "사용자가 동시에 쓴 내용\n"
            notes._buffer.set_text(local)
            newer = "Codex가 다시 쓴 원본\n"
            path.write_text(newer, encoding="utf-8")
            notes.refresh_external()
            check("충돌 때 사용자 편집 보존", notes._text() == local)
            check("충돌 때 예약 자동 저장 중지", notes._save_id == 0)
            check("일반 저장이 외부 편집을 덮지 않음", not notes.save() and path.read_text() == newer)
            check("Ctrl+S 처리", notes._on_key(None, Gdk.KEY_s, 0, Gdk.ModifierType.CONTROL_MASK))
            pump()
            check("강제 저장도 확인 대기하고 원본 보존", notes._conflict_dialog is not None
                  and path.read_text() == newer and notes._text() == local)
            notes._conflict_dialog.response(Gtk.ResponseType.CANCEL)
            check("충돌 취소가 양쪽 내용 보존", notes._text() == local and path.read_text() == newer)
            before = set(folder.glob("*.내편집-*.md"))
            notes.save(force=True)
            notes._conflict_dialog.response(Gtk.ResponseType.ACCEPT)
            backups = set(folder.glob("*.내편집-*.md")) - before
            check("내 편집을 별도 파일로 보관", len(backups) == 1
                  and next(iter(backups)).read_text() == local)
            check("원본 외부 편집 보존 후 새로고침", path.read_text() == newer
                  and notes._text() == newer and not notes.doc.dirty)

            chat.doc.messages.append({"role": "user", "content": "저장 실패 시험"})
            chat._dirty = True
            with patch.object(chat.doc, "save", side_effect=OSError("test write failure")):
                w.open_path(b)
                check("대화 저장 실패가 영상 전환 차단", w.current_path == a and chat._path == a)
                check("전환 실패에도 영상과 메모 일치", notes.doc.path == a.with_suffix(".md")
                      and notes._text() == newer)
            check("대화 저장 복구", chat.prepare_leave())
            broken = Conversation(b)
            broken.path.parent.mkdir(parents=True, exist_ok=True)
            broken.path.write_text("{broken json", encoding="utf-8")
            w.open_path(b)
            pump()
            check("손상된 대화와 무관하게 영상 열기", w.current_path == b and w.player.alive)
            check("영상 메모 일치와 대화만 비활성", notes.doc.path == b.with_suffix(".md")
                  and chat._path == b and chat.doc is None and not chat.send_button.get_sensitive())
            check("손상된 대화 원본 보존", broken.path.read_text() == "{broken json")
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
    video = folder / "강의 a.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=30:duration=15", "-c:v", "libx264",
                    "-preset", "ultrafast", str(video)], check=True)
    (folder / "강의 b.mp4").write_bytes(video.read_bytes())
    Probe(non_unique=True).run([sys.argv[0], str(video)])
    print(f"{sum(results)}/{len(results)} 통과")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
