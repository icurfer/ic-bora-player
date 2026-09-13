#!/usr/bin/env bash
#
# Gate F 자체 검사 — 금칙 표현 게이트가 '실제로' 막는지, 그리고 멀쩡한 것을 막지 않는지 본다.
#
# 왜 필요한가: 이 게이트는 한 번 조용히 죽은 적이 있다(2026-09-13).
# grep 의 바이트 범위 패턴이 아무것도 매칭하지 않았는데, 통과만 하니 아무도 몰랐다.
# 게이트는 '막는 것'을 확인해야 살아 있는 것이다.
#
#   bash scripts/selftest_taboo.sh
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail=0

mk() { printf '%b' "$2" > "$TMP/$1"; }

# 막아야 하는 것 — 리터럴 대신 코드포인트로 만든다(이 파일이 게이트에 걸리지 않게).
mk hanja.txt   "$(python3 -c 'print(chr(0x4E2D)+" "+chr(0x6587)+" test")')\n"
mk extA.txt    "$(python3 -c 'print(chr(0x3400)+" test")')\n"
mk taboo.txt   "$(python3 -c 'print(chr(0xC804)+chr(0xC0AC)+" 적용 범위")')\n"
# 통과해야 하는 것 — 한글, em dash, 박스 문자, 일본어 가나(한자 없음), 이모지
mk ok_ko.txt   "한글만 있는 줄\n"
mk ok_dash.txt "제목 — 설명 · 구분 ─────\n"
mk ok_kana.txt "$(python3 -c 'print("".join(map(chr,(0x3042,0x3044,0x3046,0x20,0x30AB,0x30CA))))')\n"
mk ok_emoji.txt "통과 여부 ✅ 🔴\n"

check() {  # $1=파일 $2=기대(block|pass)
  out="$(printf '%s\n' "$TMP/$1" | python3 scripts/check_taboo.py --all '' 2>/dev/null)"
  rc=$?
  if [ "$2" = "block" ] && [ "$rc" -ne 1 ]; then
    echo "  ✗ $1 : 막아야 하는데 통과했다 (미탐)"; fail=1; return
  fi
  if [ "$2" = "pass" ] && [ "$rc" -ne 0 ]; then
    echo "  ✗ $1 : 통과해야 하는데 막혔다 (오탐)"; echo "     $out"; fail=1; return
  fi
  echo "  ✓ $1 ($2)"
}

echo "Gate F 자체 검사"
check hanja.txt block
check extA.txt block
check taboo.txt block
check ok_ko.txt pass
check ok_dash.txt pass
check ok_kana.txt pass
check ok_emoji.txt pass

# 게이트 스크립트 자신과 이 검사 파일이 자기 규칙에 걸리면 커밋이 영영 막힌다
for f in scripts/check_taboo.py scripts/selftest_taboo.sh scripts/check-conventions.sh; do
  [ -f "$f" ] || continue
  if printf '%s\n' "$f" | python3 scripts/check_taboo.py --all '' >/dev/null 2>&1; then
    echo "  ✓ $f (자기 규칙에 걸리지 않음)"
  else
    echo "  ✗ $f : 게이트 자신이 자기 규칙에 걸린다"; fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "Gate F 자체 검사 실패"; exit 1
fi
echo "Gate F 자체 검사 통과"
