"""mpv가 첫 프레임을 읽기 전에 이전 파일 속도를 초기화해야 한다."""
from types import SimpleNamespace
import pytest
from bora.player import Player


@pytest.mark.parametrize('previous',[.25,1.75,4])
def test_each_loadfile_sees_normal_speed_before_play(previous):
    player=Player.__new__(Player)
    engine=SimpleNamespace(speed=previous, pause=True, playlist=[{'id': 1}])
    observed=[]
    engine.play=lambda path:observed.append((path,engine.speed,engine.pause))
    player._mpv=engine
    player.open('first.mp4')
    player.speed=2
    player.open('second.mp4')
    player.speed=.5
    player.open('second.mp4')
    assert observed==[('first.mp4',1,False),('second.mp4',1,False),('second.mp4',1,False)]


def test_previous_entry_events_cannot_finish_new_load():
    player = Player.__new__(Player)
    player._load_pending = True
    player._requested_entry = 2
    player._active_entry = player._ready_entry = player._failed_entry = None
    def event(**data):
        player._on_load_event(SimpleNamespace(as_dict=lambda: data))
    event(event=b'start-file', playlist_entry_id=1)
    event(event=b'playback-restart')
    assert player.loading
    event(event=b'end-file', playlist_entry_id=1, reason=b'error')
    assert player.loading and not player.load_error
    event(event=b'start-file', playlist_entry_id=2)
    event(event=b'playback-restart')
    assert not player.loading
    event(event=b'end-file', playlist_entry_id=2, reason=b'error')
    assert player.load_error and not player.loading
