#!/usr/bin/env bash
#
# AI 질의 환경(.venv)을 만든다. **선택 기능**이다 — 없어도 플레이어·메모는 그대로 동작한다.
#
# --system-site-packages 를 쓰는 이유: PyGObject 는 시스템 GI 와 묶여 있어 순수 venv 에서 깨진다.
# 시스템 패키지를 그대로 보면서 anthropic 만 여기에 넣는다(기획서 v0.3 §8-1 실측).
#
#   bash scripts/install-ai.sh            설치
#   bash scripts/install-ai.sh --remove   제거
set -euo pipefail
# 기본은 deb와 개발 실행이 함께 찾을 수 있는 사용자 데이터 폴더다.
BORA_INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/bora"
BORA_REMOVE=0
BORA_PRINT_PATH=0
for arg in "$@"; do
  case "$arg" in
    --dev) BORA_INSTALL_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)" ;;
    --remove) BORA_REMOVE=1 ;;
    --print-path) BORA_PRINT_PATH=1 ;;
    *) echo "사용법: $0 [--dev] [--remove] [--print-path]" >&2; exit 2 ;;
  esac
done
VENV="$BORA_INSTALL_ROOT/.venv"
if [ "$BORA_PRINT_PATH" -eq 1 ]; then
  printf '%s\n' "$VENV"; exit 0
fi

if [ "$BORA_REMOVE" -eq 1 ]; then
  rm -rf "$VENV"; echo "제거했다."; exit 0
fi

mkdir -p "$BORA_INSTALL_ROOT"
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
echo "→ anthropic SDK 설치 중..."
"$VENV/bin/pip" install --quiet anthropic
"$VENV/bin/python" -c "import anthropic; print('  anthropic', anthropic.__version__)"

echo
echo "✓ 준비됐다. 이제 **API 키**가 필요하다 — 앱은 키를 저장하지 않는다."
echo "  둘 중 하나를 쓴다:"
echo "    export ANTHROPIC_API_KEY=sk-ant-...      (셸 설정에 넣어 두면 된다)"
echo "    ant auth login                            (프로필이 ~/.config/anthropic 에 저장된다)"
echo
echo "  키가 없어도 재생·메모·자막은 그대로 동작한다. AI 질의만 비활성이다."
