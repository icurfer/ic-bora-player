#!/usr/bin/env bash
# 검증용 샘플 만들기 — 영상과 국내 관례 자막(CP949 SAMI).
# 저장소에 커밋하지 않는다. 필요할 때 만들어 쓴다.
#   bash .claude/skills/verify-app/helpers/make_sample.sh [출력디렉터리]
set -euo pipefail
OUT="${1:-/tmp/bora-sample}"
mkdir -p "$OUT"
ffmpeg -hide_banner -loglevel error -y -f lavfi \
  -i "testsrc2=size=1920x1080:rate=30:duration=10" \
  -c:v libx264 -pix_fmt yuv420p -preset ultrafast "$OUT/movie.mp4"
# 자막은 조사 때 쓴 생성기를 그대로 쓴다(같은 표본을 유지하려고).
( cd "$OUT" && python3 "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/docs/research/scripts/gen.py" >/dev/null )
cp "$OUT/sample_cp949.smi" "$OUT/movie.smi"
echo "만들었다: $OUT/movie.mp4 + $OUT/movie.smi (CP949 한·영 통합 SAMI)"
