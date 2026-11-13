"""mpv가 첫 프레임을 읽기 전에 이전 파일 속도를 초기화해야 한다."""
from types import SimpleNamespace
import pytest
from bora.player import Player


@pytest.mark.parametrize('previous',[.25,1.75,4])
def test_each_loadfile_sees_normal_speed_before_play(previous):
    player=Player.__new__(Player)
    engine=SimpleNamespace(speed=previous)
    observed=[]
    engine.play=lambda path:observed.append((path,engine.speed))
    player._mpv=engine
    player.open('first.mp4')
    player.speed=2
    player.open('second.mp4')
    player.speed=.5
    player.open('second.mp4')
    assert observed==[('first.mp4',1),('second.mp4',1),('second.mp4',1)]
