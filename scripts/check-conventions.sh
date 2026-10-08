#!/usr/bin/env bash
#
# check-conventions.sh — the praxis gate.
#
# Turns human discipline into a machine-enforced pre-commit gate. Each rule
# below was (or should be) born from a real incident: something broke, you wrote
# down why, and if it was mechanically checkable you moved it here so it can
# never slip back. Add a new gate every time a retro produces a checkable rule.
#
# Every gate judges the STAGED BLOB (`git show ":$f"`) — what actually gets
# committed — never the working tree. `--all` mode sweeps the working tree instead.
#
# Portability: runs on stock bash 3.2 (macOS) and Git Bash (Windows) — keep it
# free of bash-4-isms (declare -A, mapfile) and guard empty-array expansions.
#
# Usage:
#   scripts/check-conventions.sh          # check staged changes (called by the hook)
#   scripts/check-conventions.sh --all    # also sweep the whole working tree for secrets
#
# Emergency bypass:  git commit --no-verify
#
set -euo pipefail

# Staged paths are repo-root relative — run from the root so `git show :path`,
# pathspecs, and AREA regexes agree no matter where the script was invoked from.
cd "$(git rev-parse --show-toplevel)"

# ── Config (tune these for your project) ────────────────────────────────────
# 버전은 릴리스 단위로 변경한다. 코드/문서 커밋마다 bump를 요구하지 않는다.
# 제품 버전과 배포 규칙: docs/RELEASING.md

# Secret / taboo detection ---------------------------------------------------
# Literal secrets — any match blocks outright (no placeholder exception).
FORBIDDEN_PATTERNS=(
  'AKIA[0-9A-Z]{16}'                       # AWS access key id
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'     # private key literal
)
# key/value secret assignment. Three forms:
#   quoted        — `foo = "..."` / YAML `foo: '...'`  → checked in EVERY file
#   unterminated  — `foo: "...` (pasted secret, no closing quote) → every file
#   bare          — `foo: hunter2...` / `FOO=...`      → checked only in
#     config-style files (BARE_VALUE_FILES_RE). In code, a bare RHS is a variable
#     reference, not a literal — flagging `token = access_token` would drown the
#     gate in false positives; quoted literals cover code.
SECRET_KEY_RE='(password|passwd|secret_?key|secretkey|token|api_?key)'
BARE_VALUE_FILES_RE='(^|/)(\.env[^/]*|[^/]+\.(ya?ml|properties|ini|conf|cfg|toml|env))$|(^|/)dockerfile[^/]*$'
# A value that looks like a placeholder/scaffold is skipped. The check runs on
# EVERY assignment on the line, value by value — a line is exempt only if ALL its
# values are placeholders, so a placeholder in a trailing comment can't exempt a
# real secret earlier on the line. Wordy patterns are boundary-anchored:
# `EXAMPLE_KEY` is a placeholder, `myexample-ProdToken99` is not.
PLACEHOLDER_RE='(CHANGE_?ME|REDACTED|xxxx+|\$\{|\{\{|<[^>]*>|(^|[^[:alnum:]])(example|placeholder|dummy|change[-_]?me)([^[:alnum:]]|$))'
# Minimum value length for the key/value gate ({3,} over-flags `token: "abc"`).
SECRET_MIN_LEN=8
# Pathspecs the `--all` sweep scans. Staged mode ALWAYS scans every staged file —
# a narrowed glob must never exempt a staged secret from the commit gate.
FORBIDDEN_GLOBS=('.')

# 금칙 표현(Gate F) -----------------------------------------------------------
# 사용자 전역 규칙: 문서·코드에 한자를 쓰지 않는다(읽는 사람이 못 알아본다).
# 검사 본체와 패턴은 scripts/check_taboo.py 에 있다. 여기서는 예외 경로만 정한다.
# 예외: 자막 처리 프로젝트라 테스트 자막·조사 샘플에는 일본어·중국어가 정당하게 들어간다.
TABOO_EXCLUDE_RE='^(tests?/fixtures/|docs/research/samples/|third_party/)'
# ────────────────────────────────────────────────────────────────────────────

RED=$'\033[31m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
fail=0
err()  { printf '%s✗%s %s\n' "$RED" "$RST" "$1" >&2; fail=1; }
ok()   { printf '%s✓%s %s\n' "$GRN" "$RST" "$1" >&2; }

MODE="${1:-}"

# quotepath=false: without it git shell-quotes non-ASCII paths ("\354\204\244…"),
# which breaks the AREA regexes and makes `git show ":$f"` fail — silently
# skipping exactly the files the gate must judge.
gitq() { git -c core.quotepath=false "$@"; }

# Secret/content 검사는 커밋에 포함되는 staged blob을 읽는다.
CHANGED_LIST="$(gitq diff --cached --name-only --diff-filter=ACMRD || true)"
PRESENT_LIST="$(gitq diff --cached --name-only --diff-filter=ACMR || true)"
DELETED_LIST="$(gitq diff --cached --name-only --diff-filter=D || true)"

# Read a file's to-be-committed content: the staged blob (index), NOT the
# working tree — a pre-commit gate must judge what actually gets committed.
# `--all` mode sweeps the working tree instead. Every gate reads through this.
content() {
  if [ "$MODE" = "--all" ]; then cat -- "$1" 2>/dev/null
  else git show ":$1" 2>/dev/null; fi
}

# ── Gate A: 필수 지침/버전과 바이너리 소스 추적 방지 ──────────────────
for required in version AGENTS.md CLAUDE.md docs/RELEASING.md; do
  content "$required" >/dev/null 2>&1 || err "필수 파일 누락: $required"
done
if printf '%s\n' "$PRESENT_LIST" | grep -Eiq '\.(deb|rpm|AppImage|exe|msi)$'; then
  err "설치 바이너리는 Git에 추가하지 말고 GitHub Releases에 첨부하세요."
fi

# ── Gate B: staging에 있는 버전 형식을 검사한다 ──────────────────────────
if content version >/dev/null 2>&1; then
  version_value="$(content version)"
  version_lines="$(content version | awk 'END{print NR}')"
  if [ "$version_lines" -ne 1 ] || ! python3 scripts/version_policy.py --value "$version_value" >/dev/null; then
    err "version 형식이 올바르지 않습니다."
  else
    ok "버전 형식 확인 (일반 커밋의 버전 증가는 요구하지 않음)"
  fi
fi

# ── Gate C: forbidden patterns (secrets / taboos) ───────────────────────────
# Reads the STAGED blob (or the working tree under --all) — never a mix, so a
# secret staged then deleted from the working tree is still caught.
scan_targets() {
  if [ "$MODE" = "--all" ]; then
    gitq ls-files -- ${FORBIDDEN_GLOBS[@]+"${FORBIDDEN_GLOBS[@]}"}
  else
    printf '%s\n' "$PRESENT_LIST"
  fi
}
QUOTED_ASSIGN_RE="${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*(\"[^\"]{${SECRET_MIN_LEN},}\"|'[^']{${SECRET_MIN_LEN},}'|[\"'][^\"' ]{${SECRET_MIN_LEN},})"
BARE_ASSIGN_RE="${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*[A-Za-z0-9_+/=.-]{${SECRET_MIN_LEN},}[[:space:]]*(#.*)?\$"
# Extract the assigned value from ONE matched assignment (input is lowercased —
# the value is only ever compared against PLACEHOLDER_RE, case-insensitively).
assign_val() {
  printf '%s\n' "$1" | sed -En \
    -e "s@.*${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*\"([^\"]{${SECRET_MIN_LEN},})\".*@\2@p" \
    -e "s@.*${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*'([^']{${SECRET_MIN_LEN},})'.*@\2@p" \
    -e "s@.*${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*[\"']([^\"' ]{${SECRET_MIN_LEN},}).*@\2@p" \
    -e "s@.*${SECRET_KEY_RE}[[:space:]]*[:=][[:space:]]*([a-z0-9_+/=.-]{${SECRET_MIN_LEN},})[[:space:]]*(#.*)?\$@\2@p" \
    | head -n1
}
# A line is exempt ONLY if every assignment on it extracts to a placeholder
# value. Unparseable → treated as real (block is the safe direction).
line_all_placeholders() {  # $1 = line, $2 = assign regex
  lline="$(printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]')"
  found=0
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    found=1
    v="$(assign_val "$m")"
    [ -n "$v" ] || return 1
    printf '%s\n' "$v" | grep -Eiq -e "$PLACEHOLDER_RE" || return 1
  done < <(printf '%s\n' "$lline" | grep -oE -e "$2" || true)
  [ "$found" -eq 1 ]
}
report_hit() { if [ "$1" -eq 0 ]; then err "forbidden pattern detected:"; fi; }
hit=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  body="$(content "$f")" || continue
  [ -n "$body" ] || continue
  # 1) literal secrets — always block
  for pat in ${FORBIDDEN_PATTERNS[@]+"${FORBIDDEN_PATTERNS[@]}"}; do
    while IFS= read -r line; do
      report_hit "$hit"; hit=1
      printf '        %s: %s\n' "$f" "$line" >&2
    done < <(printf '%s\n' "$body" | grep -nIE -e "$pat" || true)
  done
  # 2) key/value secret assignment — block unless EVERY value is a placeholder
  assign_re="$QUOTED_ASSIGN_RE"
  if printf '%s\n' "$f" | grep -Eiq -e "$BARE_VALUE_FILES_RE"; then
    assign_re="${QUOTED_ASSIGN_RE}|${BARE_ASSIGN_RE}"
  fi
  while IFS= read -r line; do
    if line_all_placeholders "$line" "$assign_re"; then continue; fi
    report_hit "$hit"; hit=1
    printf '        %s: %s\n' "$f" "$line" >&2
  done < <(printf '%s\n' "$body" | grep -nIiE -e "$assign_re" || true)
done < <(scan_targets)

# Gate D (릴리스 태그/변경내역/검증기록)는 version_policy.py --release-tag에서 검사한다.
# 일반 개발 커밋에는 릴리스 조건을 요구하지 않는다.

# ── Gate E: dual-agent constitution sync (CLAUDE.md ↔ AGENTS.md) ────────────
# One rule set, two native entrypoints: Claude Code reads CLAUDE.md, Codex
# reads AGENTS.md. Both carry a marker-delimited shared block that must stay
# byte-identical — otherwise the two agents follow different rules and drift
# silently. Judged on the staged blob, like every other gate.
#   - both files carry the block          → blocks must match
#   - one carries it, the other file exists WITHOUT it → that agent can't see
#     the shared rules → block (finish the merge, or delete the odd file out)
#   - only one entrypoint exists at all   → single-agent setup, nothing to judge
SHARED_BEGIN='<!-- praxis:shared:begin -->'
SHARED_END='<!-- praxis:shared:end -->'
shared_block() {  # prints the block body; empty if the file or markers are absent
  content "$1" | awk -v b="$SHARED_BEGIN" -v e="$SHARED_END" \
    '$0==b{on=1;next} $0==e{on=0} on{print}'
}
if content CLAUDE.md >/dev/null 2>&1 && content AGENTS.md >/dev/null 2>&1; then
  c_block="$(shared_block CLAUDE.md)"
  a_block="$(shared_block AGENTS.md)"
  if [ -z "$c_block" ] && [ -z "$a_block" ]; then
    :  # neither carries the praxis block — the sync mechanism isn't in use here
  elif [ "$c_block" = "$a_block" ]; then
    ok "constitution in sync (CLAUDE.md ↔ AGENTS.md shared block)"
  elif [ -z "$c_block" ] || [ -z "$a_block" ]; then
    err "one constitution entrypoint has no praxis:shared block — that agent can't see the shared rules."
    printf '%s    → copy the <!-- praxis:shared:begin/end --> block into the file that lacks it, or delete that file if unused.%s\n' "$DIM" "$RST" >&2
  else
    err "CLAUDE.md and AGENTS.md shared blocks have DRIFTED — the two agents would follow different rules."
    printf '%s    → edit one, copy the marker block VERBATIM into the other, then stage both.%s\n' "$DIM" "$RST" >&2
  fi
fi

# ── Gate F: 금칙 표현(한자·금칙어) ────────────────────────
# 문서 규칙이지만 기계로 검사되므로 CLAUDE.md 문장이 아니라 여기 있다.
# 검사 본체는 scripts/check_taboo.py 에 있다 — grep 으로는 로케일에 따라
# 미탐·오탐이 갈려 게이트로 쓸 수 없었다(그 파일의 주석에 실측 기록).
# 게이트가 살아 있는지는 `bash scripts/selftest_taboo.sh` 로 확인한다.
TABOO_CHECKER="$(git rev-parse --show-toplevel)/scripts/check_taboo.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$TABOO_CHECKER" ]; then
  taboo_report="$(scan_targets | python3 "$TABOO_CHECKER" "$MODE" "$TABOO_EXCLUDE_RE" || true)"
  if [ -n "$taboo_report" ]; then
    while IFS="$(printf '\t')" read -r reason path lineno line; do
      [ -n "$reason" ] || continue
      err "$reason"
      printf '        %s: %s: %s\n' "$path" "$lineno" "$line" >&2
    done <<< "$taboo_report"
  else
    ok "금칙 표현 없음(한자·금칙어)"
  fi
else
  printf '%s! python3 또는 check_taboo.py 가 없어 Gate F 를 건너뛴다.%s\n' "$DIM" "$RST" >&2
fi

# ── Result ──────────────────────────────────────────────────────────────────
if [ "$fail" -ne 0 ]; then
  printf '\n%sCommit blocked.%s Fix the above, or bypass intentionally with %sgit commit --no-verify%s\n' \
    "$RED" "$RST" "$DIM" "$RST" >&2
  exit 1
fi
printf '%spraxis gate passed.%s\n' "$GRN" "$RST" >&2
exit 0
