# 공통 UI Linux MVP 범위

- `src/bora/ui.py`: 기본 창·패널 크기, 영상 안내 CSS, 메모 색상 적용 함수.
- `notes/panel.py`: 공통 크기 사용, root/unroot 시 테마 신호 연결/해제, 태그 색상 갱신.
- `ai/panel.py`: 공통 패널 크기 참조.
- `window.py`: 공통 창/패널/힌트 스타일 참조, `_draw_blackout` PangoCairo 변경.
- `scenarios/18-shared-ui.py`: 격리 실행, 테마/배치/아이콘/메모 보존 및 캡처 검사.
- `scenarios/16-shortcuts-images.py`: 끝 개행 계약, 창 장식과 콘텐츠 크기 구분, 가상 화면 재생과 입력 검사 분리·대기 한도, 실제 Ctrl+W 검사.
- 기획·완료·백로그에 Linux 실측 결과와 Windows 후속 검증을 구분한다.

새 테마 설정 화면, 기존 단축키 구조 전면 변경, Windows 구현 수정은 포함하지 않는다.
