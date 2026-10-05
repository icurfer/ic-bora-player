#!/usr/bin/env python3
"""인수 검토 회귀: 파일 전환·메모 충돌·AI 응답·외부 SRT·음성 안내.

실제 API나 사용자 자료를 쓰지 않는다. 설정·캐시·영상·문서는 임시 폴더로 격리한다.
"""
import os
import sys
import tempfile
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
TEMP = tempfile.TemporaryDirectory(prefix='bora-handover-')
folder = Path(TEMP.name)
os.environ['XDG_CONFIG_HOME'] = str(folder / 'config')
os.environ['XDG_CACHE_HOME'] = str(folder / 'cache')
os.environ['XDG_DATA_HOME'] = str(folder / 'data')

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib
from bora.app import BoraApplication
from bora.glarea import MpvGLArea
from bora.notes.model import NoteDocument
import bora.notes.panel as panel_module

results = []


def check(name, condition):
    results.append(bool(condition))
    print(f"[{'통과' if condition else '실패'}] {name}", flush=True)
    assert condition, name


def pump_until(condition, timeout=5):
    end = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if condition():
            return True
        time.sleep(.02)
    return False


class FakeAsk:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.running = False
        self.cancelled = False

    def ask(self, _job):
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
        GLib.timeout_add(1200, self.run_checks)

    def run_checks(self):
        w = self.win
        try:
            a, b, audio = folder / 'a.mp4', folder / 'b.mp4', folder / 'audio.wav'
            check('초기 영상 재생', pump_until(lambda: (w.player.duration or 0) > 0))
            w.toggle_edit()
            w._timeline.model.toggle(0)
            w._on_timeline_position(1)
            check('삭제 구간 검은 덮개', w._blackout.get_visible())
            old_generation = w._media_generation
            w.open_path(b)
            check('편집 폐기 전 파일 전환 보류', w.current_path == a)
            w.open_path(b)
            check('새 파일에서 편집 상태 제거', w.current_path == b and w._timeline.model is None
                  and not w._blackout.get_visible() and not w.editing and w._clips.empty)
            called = []
            w._for_media(old_generation, lambda: called.append(True))
            check('이전 파일 콜백 무시', not called)

            notes = w._notes
            notes.load_for(b)
            notes._buffer.set_text('saved memo')
            notes.save()
            notes._buffer.set_text('unsaved memo')
            notes.doc.path.write_text('external edit')
            stamp = time.time() + 5
            os.utime(notes.doc.path, (stamp, stamp))
            w.open_path(a)
            check('메모 충돌 시 영상·버퍼 보존', w.current_path == b and notes._text() == 'unsaved memo')
            check('메모 충돌 시 종료 중단', w._on_close() is True and w.player.alive)
            check('충돌 편집 보관 후 외부 내용 복원', notes._preserve_and_reload())
            notes._buffer.set_text('write failure memo')
            with patch.object(notes.doc, 'save', side_effect=OSError('test write failure')):
                w.open_path(a)
                check('저장 오류 시 전환 중단', w.current_path == b and notes._text() == 'write failure memo')
            notes.save()
            w.toggle_notes(False)
            w.open_path(a)
            check('숨긴 메모도 새 파일에 연결', notes.doc.path == NoteDocument.path_for(a))

            notes._buffer.set_text('question\nfollowing paragraph')
            notes._buffer.place_cursor(notes._buffer.get_start_iter())
            with patch.object(w, 'open_codex_terminal', return_value=True) as launch:
                check('메모 질문을 기본 터미널에 전달', notes.ask_current_line())
                check('터미널 질문 내용', launch.call_args.args == ('question',))
                check('질문 전달이 메모를 바꾸지 않음', notes._text() == 'question\nfollowing paragraph')
            w.open_path(b)

            external = folder / 'unrelated.srt'
            external.write_text('1\n00:00:00,000 --> 00:00:08,000\nexternal subtitle\n')
            w.open_path(a, external)
            check('다른 이름의 외부 SRT 로드', pump_until(lambda: any(
                t.get('external-filename') == str(external) for t in w.player.sub_tracks)))
            check('일반 자막 중복 없음', len(w.player.sub_tracks) == 1)
            w.open_path(b)
            check('다음 파일에 자막이 남지 않음', pump_until(lambda: not w.player.sub_tracks))
            for lang in ('ko', 'en'):
                (folder / f'b.{lang}.srt').write_text(external.read_text())
            w.open_path(b)
            check('일반 다국어 자막 자동 탐색 유지', pump_until(lambda: len(w.player.sub_tracks) == 2))

            w.open_path(audio)
            check('음성 트랙 판정', pump_until(lambda: w.player.audio_only))
            w._tick()
            check('음성 전용 안내 표시', w._media_hint.get_visible()
                  and '음성 전용' in w._media_hint.get_label())
            check('안내 문구 대비', w._media_hint.get_style_context().get_color().red > .9)
            w.open_path(a)
            check('영상 복귀', pump_until(lambda: not w.player.audio_only))
            w._tick()
            check('영상에서 음성 안내 제거', not w._media_hint.get_visible())
            with patch.object(w.player._mpv, 'set_loglevel', wraps=w.player._mpv.set_loglevel) as level:
                w._on_log_level(SimpleNamespace(get_active=lambda: True), 'debug')
                check('메뉴 로그 등급이 mpv에도 적용', level.call_args.args == ('v',))
            failed_area = MpvGLArea(w.player)
            failed_area._on_realize(SimpleNamespace(make_current=lambda: None,
                                                     get_error=lambda: 'test GL error'))
            w._video.error = failed_area.error
            w._tick()
            check('GL 초기화 실패 안내', w._media_hint.get_visible()
                  and 'test GL error' in w._media_hint.get_label())
            w._video.error = ''
            check('정상 종료', w._on_close() is False)
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
    video = folder / 'a.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x240:rate=30:duration=12', '-c:v', 'libx264',
                    '-preset', 'ultrafast', str(video)], check=True)
    (folder / 'b.mp4').write_bytes(video.read_bytes())
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'anullsrc=r=16000:cl=mono', '-t', '12', str(folder / 'audio.wav')], check=True)
    Probe(non_unique=True).run([sys.argv[0], str(video)])
    print(f"{sum(results)}/{len(results)} 통과")
    return 0 if results and all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
