# 공통 UI Linux 1차 적용

기획: [shared-ui](../spec/shared-ui.md). Windows 후속: [deferred](../deferred/shared-ui.md).

## 변경

`src/bora/ui.py`에서 기본 창·학습 패널 크기, 영상 안내 CSS, 메모 역할 색상을 관리한다.
메모는 시스템 밝게/어둡게 전환에 따라 기존 태그 색상만 갱신하며 텍스트·선택을 다시
만들지 않는다. root/unroot 시 테마 신호를 연결/해제한다. 인용문은 흐린 고정 회색 대신
본문 색상으로 읽고, 링크는 밑줄을 유지한다. 삭제 구간 안내는 GTK Pango 글꼴로 그린다.

새 테마 설정·저장 형식·OS별 화면은 추가하지 않았다. 전체 타임라인과 액션 목록 통합은
후속 범위다. 공통 소스 변경이므로 Windows에도 같은 구현이 전달되지만 실측 완료는 아니다.

## 검증

Ubuntu 26.04, GTK 4.22.4, libadwaita 1.9.0. 사용자 설정·메모와 검증 데이터를 분리했다.

- `bash scripts/check-python-tests.sh`: 287 통과, 3 제외.
- 격리 Xvfb `18-shared-ui.py`: 49/49 통과. 밝게/어둡게 메모·커서·선택·초안 보존,
  실제 위젯 경계와 아이콘 27개, 두 차례 재부착 신호 정리, 모의 고대비 정책 포함.
- 링크 대비 밝게 4.72:1 / 어둡게 5.84:1, 인용문 10.86:1 / 15.70:1.
- 요청 960×700의 실제 GTK 콘텐츠 950×690, 요청 640×560의 콘텐츠 630×550.
  메모 위·대화 아래와 주요 도구·전송 버튼 접근을 확인했다. 모든 폰트·배율의 최소 크기 보장은 아니다.
- 독립 UI 에이전트가 밝게/어둡게/좁은 창/한국어 안내 실제 캡처를 검토했다.
  `/tmp/bora-shared-ui-review/shared-{light-960,dark-960,dark-korean-overlay,dark-minimum}.png`.
- 격리 XTest `17-terminal-choice.py`: 10/10 통과. 외부 CLI 실행은 모의.
- 격리 XTest `16-shortcuts-images.py`: 25/25 통과. 실제 Ctrl+Enter 전송·Ctrl+W 종료,
  메모 단축키와 이미지 전달 확인. API/CLI 응답은 모의이며 영상은 일시정지 상태다.
- Wayland `01-playback-renders.py /tmp/bora-shared-ui-video/movie.mp4`: 렌더 콜백 123,
  재생 위치 4.23초, `vulkan-copy`, 통과. 검증 창 종료.

실행 예:
`GDK_BACKEND=x11 GSK_RENDERER=cairo BORA_REVIEW_SHOTS=/tmp/bora-shared-ui-review xvfb-run -a python3 .claude/skills/verify-app/scenarios/18-shared-ui.py`.

## 검증 중 발견과 한계

기존 시나리오16이 파일 끝 개행 보장을 편집 버퍼와 직접 비교하고, 요청 창 크기와
콘텐츠 높이를 동일시해 실패했다. 실제 저장 계약과 위젯 경계 검사로 고쳤다.
Xvfb 재생 중 모의 worker는 종료했으나 UI idle 응답 처리가 대기하는 것을 스레드 덤프로
확인했다. 10초 대기로 늘려도 재현되어 입력·첨부 검사는 영상을 일시정지해 실행했다.
제한 대기 10초를 유지하며, 이 결과를 재생 중 응답성 전체 검증으로 쓰지 않는다.
실제 종료 키입력도 시나리오에 포함했다.

Xvfb 화면의 GL 영상에는 표시 이상이 있어 해당 캡처를 재생 성공 증거로 쓰지 않는다.
재생은 별도의 실제 Wayland 검사로 확인했다. 테마 전환 시 선택은 보존되지만 GtkTextView를
완전히 분리·재부착하면 GTK가 선택을 해제하는 현상이 있다. 텍스트·커서는 유지된다.
실제 고대비 세션·한글 IME·글꼴/소수 배율·Windows·오래된 런타임은 미검증이다.
실제 계정 AI 호출·설치 완료를 뜻하지 않는다. 로컬 배포 패키지는 만들지 않았다.
