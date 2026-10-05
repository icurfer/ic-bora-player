# 인수 검토 재현 기록

기준: 0.26.1, Ubuntu 26.04, python-mpv 1.0.8, libmpv 0.41.0.

- 실행 중 파일은 WAV이며 ffprobe의 codec_type은 audio 하나뿐이었다. 영상 출력 오류로 단정하지 않는다.
- `python3 -m pytest -q`: 205개 통과. 기존 기능 시나리오 01~11도 통과했다.
- 외부 자막 재현: 임시 H.264 영상과 이름이 다른 UTF-8 SRT를 만들고
  `prepare_for_video(video, cache, explicit=srt)` → `Player(vo="null").open(video, plan)` 후
  `wait_until_playing(timeout=5)`와 트랙 조회. plan.source는 SRT이나 sub_tracks는 빈 목록.
  원인: Player.open이 plan.tracks가 있는 SAMI 분리 결과만 추가하고 plan.source는 전달하지 않는다.
- 임시 3초 영상을 source=output인 ExportJob으로 1초 내보내면 원본 길이가 1초로 바뀐다.
- 작은따옴표를 포함한 임시 폴더에서 두 조각을 합치면 ffmpeg concat이 경로를 잘못 해석한다.
- A 영상의 구간 삭제 후 B를 열면 타임라인 객체와 blackout=True가 유지된다.
- 메모를 밖에서 수정한 뒤 저장하면 False이나 load_for(B)는 미저장 버퍼를 교체한다.
- AI delta는 질문 아래가 아닌 buffer.get_end_iter()에 들어간다.

검증 자료는 임시 폴더에 생성했다. 영구 회귀 절차는 tests와 verify-app 시나리오에 둔다.
