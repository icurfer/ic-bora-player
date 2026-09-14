#!/usr/bin/env bash
#
# 음성 텍스트 추출 환경(.venv-stt)을 만든다. **선택 기능**이다 — 설치하지 않아도
# 플레이어는 그대로 동작하고, 추출 메뉴만 '설치 필요'로 바뀐다.
#
# 왜 별도 venv 인가: 시스템 파이썬에는 PEP 668 로 넣을 수 없고, 넣어서도 안 된다.
# faster-whisper 는 ctranslate2 를 끌고 오고 모델 파일이 수백 MB 다.
#
#   bash scripts/install-stt.sh            설치
#   bash scripts/install-stt.sh --remove   제거
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
VENV=".venv-stt"

if [ "${1:-}" = "--remove" ]; then
  rm -rf "$VENV"
  echo "제거했다. 모델 캐시는 ~/.cache/huggingface 에 남아 있다(지우려면 그 폴더를 지운다)."
  exit 0
fi

command -v ffmpeg >/dev/null || { echo "✗ ffmpeg 가 필요하다: sudo apt install ffmpeg" >&2; exit 1; }

python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
echo "→ faster-whisper 설치 중 (몇 분 걸린다)..."
"$VENV/bin/pip" install --quiet faster-whisper

"$VENV/bin/python" -c "import faster_whisper, ctranslate2; print('  faster-whisper', faster_whisper.__version__, '/ ctranslate2', ctranslate2.__version__)"
echo
echo "✓ 준비됐다. 모델은 처음 쓸 때 내려받는다(small 기준 약 480 MB)."
echo "  Bora 에서 자막 없는 영상을 열면 추출을 제안한다."
