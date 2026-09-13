#!/usr/bin/env python3
"""Gate F — 금칙 표현 검사 (한자·금칙어).

check-conventions.sh 가 호출한다. 검사 대상 경로를 표준입력으로 줄 단위로 받는다.

이 검사만 grep 이 아니라 파이썬으로 하는 이유 (2026-09-13 실측):
  - 바이트 범위 패턴은 GNU grep 이 브래킷 안에서 처리하지 못해 **아무것도 매칭하지 않는다**.
    게이트가 통과만 시키며 조용히 무력화된다(미탐).
  - 문자 범위 패턴에 LC_ALL=C 를 걸면 멀티바이트가 바이트로 쪼개져 em dash 까지 잡는다(오탐).
로케일에 따라 결과가 달라지는 검사는 게이트로 쓸 수 없다. 파이썬은 유니코드를 정확히 다룬다.

⚠ 패턴을 코드포인트(chr)로 조립하는 이유: 이 파일 자체가 자기 패턴에 걸리지 않게 하려고.
   리터럴로 쓰면 게이트가 이 파일을 영원히 막는다.
⚠ 이 파일을 고치면 '한자가 든 파일'과 '한글만 든 파일' 둘 다로 재검증할 것.
   scripts/selftest_taboo.sh 가 그 둘을 자동으로 확인한다.

사용법:
    <경로 목록> | check_taboo.py <mode> <exclude_regex>
      mode: '--all' 이면 작업 트리를 읽고, 그 밖에는 스테이징된 블롭을 읽는다.
    일치가 있으면 종료 코드 1 과 '사유<탭>경로<탭>줄번호<탭>내용' 을 줄마다 출력한다.
"""

import re
import subprocess
import sys

# CJK 확장 A(U+3400~U+4DBF) + 통합 한자(U+4E00~U+9FFF).
# 일본어 가나(U+3040~U+30FF)와 기호·박스 문자(U+2000~U+2E7F)는 범위 밖이다.
_HANJA_FIRST, _HANJA_LAST = 0x3400, 0x9FFF
# 회사 전체를 뜻할 때만 맞는 표기. 다른 뜻으로 읽혀 의미가 흐려진다.
_TABOO_WORD = chr(0xC804) + chr(0xC0AC)

RULES = [
    (re.compile("[" + chr(_HANJA_FIRST) + "-" + chr(_HANJA_LAST) + "]"),
     "한자가 들어 있다 — 한글이나 기호로 바꾼다."),
    (re.compile(re.escape(_TABOO_WORD)),
     "금칙어가 들어 있다 — 회사 전체를 뜻할 때만 맞는 표기다. 전체/모두로 바꾼다."),
]

MAX_SHOWN = 160


def read_target(path: str, mode: str) -> bytes:
    if mode == "--all":
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return b""
    result = subprocess.run(["git", "show", ":" + path], capture_output=True)
    return result.stdout if result.returncode == 0 else b""


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    exclude = re.compile(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None

    hits = 0
    for path in sys.stdin.read().splitlines():
        path = path.strip()
        if not path or (exclude and exclude.search(path)):
            continue
        raw = read_target(path, mode)
        if not raw or b"\x00" in raw[:8192]:
            continue                      # 비어 있거나 바이너리면 대상이 아니다
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue                      # UTF-8 이 아닌 파일은 이 규칙의 대상이 아니다
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, reason in RULES:
                if pattern.search(line):
                    print("\t".join([reason, path, str(lineno), line[:MAX_SHOWN]]))
                    hits += 1
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
