# -*- coding: utf-8 -*-
"""설정·이어보기 회귀 테스트.

특히 고정하는 것:
- 깨진 설정 파일이 앱을 막지 않는다
- 끝까지 본 파일은 이어보기를 묻지 않는다
- 저장이 원자적이다(반쪽 파일이 남지 않는다)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bora.state import MAX_RECENT, MIN_RESUME_SECONDS, State  # noqa: E402


def _video(tmp_path: Path, name: str = "movie.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x00" * 8)
    return path


def test_roundtrip(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    video = _video(tmp_path)
    state.settings.sub_font_size = 44
    state.note_playback(video, position=600, duration=7200)
    state.save()

    again = State(tmp_path / "cfg")
    assert again.settings.sub_font_size == 44
    assert again.resume_for(video) == 600


def test_finished_file_is_not_resumed(tmp_path: Path) -> None:
    """끝까지 본 파일을 다시 열 때 '이어 볼까요'를 묻지 않는다(기획서 R2)."""
    state = State(tmp_path / "cfg")
    video = _video(tmp_path)
    state.note_playback(video, position=7100, duration=7200)   # 98%
    assert state.resume_for(video) is None
    assert state.recent[list(state.recent)[0]].finished is True


def test_too_early_is_not_resumed(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    video = _video(tmp_path)
    state.note_playback(video, position=MIN_RESUME_SECONDS - 1, duration=7200)
    assert state.resume_for(video) is None


def test_remember_position_can_be_turned_off(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    video = _video(tmp_path)
    state.note_playback(video, position=600, duration=7200)
    state.settings.remember_position = False
    assert state.resume_for(video) is None


def test_broken_config_does_not_break_startup(tmp_path: Path) -> None:
    """깨진 설정 때문에 앱이 안 뜨면 안 된다. 치워 두고 기본값으로 시작한다."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "state.json").write_text("{ 이건 JSON 이 아니다 ", encoding="utf-8")
    state = State(cfg)
    assert state.settings.speed == 1.0
    assert state.recent == {}
    assert (cfg / "state.json.broken").exists()


def test_unknown_fields_are_ignored(tmp_path: Path) -> None:
    """옛 버전이 남긴 모르는 설정이 있어도 죽지 않는다."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "state.json").write_text(json.dumps({
        "schema": 99,
        "settings": {"speed": 1.5, "그런설정없음": True},
        "recent": {"x": {"path": "/없음", "말도안되는키": 1}},
    }), encoding="utf-8")
    state = State(cfg)
    assert state.settings.speed == 1.5
    assert state.recent == {}


def test_recent_is_trimmed_and_sorted(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    for i in range(MAX_RECENT + 5):
        video = _video(tmp_path, f"m{i}.mkv")
        state.note_playback(video, position=100, duration=7200)
    assert len(state.recent) == MAX_RECENT
    items = state.recent_items()
    assert items == sorted(items, key=lambda i: i.updated, reverse=True)


def test_recent_skips_missing_files(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    video = _video(tmp_path)
    state.note_playback(video, position=100, duration=7200)
    video.unlink()
    assert state.recent_items() == []


def test_forget_all(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    state.note_playback(_video(tmp_path), position=100, duration=7200)
    state.forget_all()
    assert state.recent == {}
    assert State(tmp_path / "cfg").recent == {}


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    state = State(tmp_path / "cfg")
    state.note_playback(_video(tmp_path), position=100, duration=7200)
    state.save()
    assert not list((tmp_path / "cfg").glob("*.tmp"))
    assert json.loads((tmp_path / "cfg" / "state.json").read_text(encoding="utf-8"))["schema"] == 1


def test_valid_json_with_wrong_structure_is_recovered(tmp_path):
    for raw in ([], None, {'settings': []}, {'recent': 'wrong'}):
        (tmp_path / 'state.json').write_text(json.dumps(raw))
        state = State(tmp_path)
        assert state.settings.speed == 1
        assert state.recent == {}
        assert (tmp_path / 'state.json.broken').exists()


def test_settings_values_are_validated(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'settings': {
        'speed': 'fast', 'volume': float('nan'), 'sub_font_size': -1,
        'sub_pos': 999, 'sub_color': 'bad color', 'log_level': 'trace',
        'remember_position': 'false', 'previous_defaults': [],
    }}))
    state = State(tmp_path)
    assert state.settings.speed == 1
    assert state.settings.volume == 100
    assert state.settings.sub_font_size == 0
    assert state.settings.sub_pos == 100
    assert state.settings.sub_color == ''
    assert state.settings.log_level == ''
    assert state.settings.remember_position is True
    assert state.settings.previous_defaults == {}


def test_corrupt_recent_records_and_pins_are_skipped(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'recent': {
        'bad': {'path': 2}, 'bad2': {'path': 'x', 'position': 'soon'},
        'good': {'path': 'x', 'pins': [None, {'start': 'bad'}, {'start': 2}]},
    }}))
    state = State(tmp_path)
    assert list(state.recent) == ['good']
    assert state.recent['good'].pins[0]['start'] == 2
    assert len(state.recent['good'].pins) == 1


def test_terminal_provider_persists_and_invalid_value_defaults(tmp_path):
    state = State(tmp_path)
    state.settings.terminal_provider = 'claude'
    state.save()
    assert State(tmp_path).settings.terminal_provider == 'claude'
    raw = json.loads(state.path.read_text())
    raw['settings']['terminal_provider'] = 'unknown'
    state.path.write_text(json.dumps(raw))
    assert State(tmp_path).settings.terminal_provider == 'codex'
