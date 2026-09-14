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
cd "$(git rev-parse --show-toplevel)"
VENV=".venv"

if [ "${1:-}" = "--remove" ]; then
  rm -rf "$VENV"; echo "제거했다."; exit 0
fi

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
