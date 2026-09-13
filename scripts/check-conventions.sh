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
# AREAS — one entry per deployable unit, expressed as two PARALLEL arrays:
# AREA_CODE_RE[i] is the code paths that "must be deployed"; AREA_VFILE[i] is the
# deploy-trigger file CI watches. Touching those paths without bumping that file
# in the SAME commit means CI never fires. (Two arrays, not a delimited string,
# because a CODE_RE like '(src/|lib/)' already contains '|'.)
#
# AREA_CODE_RE[i] is an extended regex matched against staged paths (repo-root
# relative). A single-deploy-unit repo has ONE area (the default below). A
# monorepo adds one per unit and ANCHORS each with '^' so units don't bleed:
#   AREA_CODE_RE=( '^backend/'               '^frontend/(src/|public/)' )
#   AREA_VFILE=(   'backend/version'         'frontend/version'         )
# (module: monorepo — /praxis-init enables this shape when it detects >1 unit.)
# 이 저장소: 배포 단위 하나(데스크톱 앱), 트리거는 루트 'version'.
# 아직 코드가 없어 경로는 기획서 §5 의 예정 배치다 — 실제 트리를 만들 때 맞춘다.
# scripts/ 와 docs/ 는 배포물이 아니므로 일부러 뺐다(개발 도구를 고칠 때 bump 를 강요하지 않는다).
AREA_CODE_RE=(
  '^(src/|bora/|data/|po/|packaging/|pyproject\.toml$|setup\.cfg$|meson\.build$|requirements[^/]*\.txt$|[^/]*\.(desktop|metainfo\.xml)$|[^/]*\.flatpak\.(ya?ml|json)$)'
)
AREA_VFILE=(
  'version'
)

# DEPLOY_MANIFESTS — optional. Keep a deploy manifest's image tag in sync with a
# version file, so a version bump can't ship without updating what actually
# deploys. Empty = disabled. One entry per pair:
#   'VERSION_FILE|MANIFEST_FILE|TAG_REGEX'
# TAG_REGEX is an extended regex with ONE capture group for the tag, and it MUST
# match your manifest's ACTUAL layout — a nested-YAML `tag: "x"` and a flattened
# `image.tag: x` need different regexes. Verify it once:
#   sed -nE 's/.*<TAG_REGEX>.*/\1/p' <manifest>   # should print just the tag
# (module: deploy-manifest — enable on k8s/Helm/compose repos.)
DEPLOY_MANIFESTS=(
  # nested Helm values.yaml (image:\n  tag: "1.2.3"):
  # 'backend/version|helm/backend/values.yaml|tag:[[:space:]]*"?([^"[:space:]]+)"?'
)

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
# 사용자 전역 규칙: 문서·코드에 CJK 통합 한자를 쓰지 않는다(읽는 사람이 못 알아본다).
# 로케일에 따라 한글까지 오탐하지 않도록 UTF-8 '바이트열'로 매칭한다(LC_ALL=C).
# 패턴을 유니코드 이스케이프로 쓰는 이유: 이 스크립트 자신이 자기 패턴에 걸리지 않게 하려고.
TABOO_PATTERNS=(
  $'[\xe4-\xe9][\x80-\xbf][\x80-\xbf]'   # U+4000~U+9FFF = CJK 통합 한자(+확장 A)
  $'\xec\xa0\x84\xec\x82\xac'            # 회사 전체를 뜻할 때만 맞는 표기. 전체/모두로 쓴다
)
TABOO_REASONS=(
  '한자(CJK 통합 한자)가 들어 있다 — 한글이나 기호로 바꾼다.'
  '금칙어가 들어 있다 — 회사 전체를 뜻할 때만 맞는 표기이므로 전체/모두로 바꾼다.'
)
# 예외 경로: 자막 처리 프로젝트라 테스트 자막·조사 샘플에는 일본어·중국어가 정당하게 들어간다.
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

# Three staged views: Gate A judges every change INCLUDING deletions (removing
# deploy code is a deploy too); the "bump" must be a file that still EXISTS after
# the commit; content scans read only files that will exist.
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

# ── Gate A: deploy-trigger bump missing (per area) ──────────────────────────
# Deploy-affecting code is staged but that area's version file is not → CI never
# fires and the change silently never ships. Pure docs/config changes are exempt.
# A staged DELETION of the version file is never a bump — it removes the trigger.
for i in "${!AREA_CODE_RE[@]}"; do
  code_re="${AREA_CODE_RE[$i]}"; vfile="${AREA_VFILE[$i]}"
  [ -n "$code_re" ] && [ -n "$vfile" ] || continue
  if printf '%s\n' "$DELETED_LIST" | grep -Fxq -e "$vfile"; then
    err "'$vfile' is staged for DELETION — the deploy trigger would vanish and CI could never fire again."
    printf '%s    → unstage it (git restore --staged %s), or bypass with --no-verify if this is an intentional restructure.%s\n' "$DIM" "$vfile" "$RST" >&2
    continue
  fi
  if printf '%s\n' "$CHANGED_LIST" | grep -Eq -e "$code_re"; then
    if printf '%s\n' "$PRESENT_LIST" | grep -Fxq -e "$vfile"; then
      ok "deploy trigger bumped ('$vfile' staged with code change)"
    else
      err "deploy code changed but '$vfile' is not staged — CI won't fire."
      printf '%s    → patch-bump %s and git add it. Changed code paths:%s\n' "$DIM" "$vfile" "$RST" >&2
      printf '%s\n' "$CHANGED_LIST" | grep -E -e "$code_re" | sed 's/^/        /' >&2
    fi
  fi
done

# ── Gate B: version file format (one non-empty line, no blank second line) ──
# Judged on the staged blob: a malformed blob with a fixed working tree must
# still block (and vice versa must pass). A single trailing newline is fine —
# blocking `1.2.3\n` would hard-block every editor-touched adopter repo.
seen_vfiles=' '
for vfile in "${AREA_VFILE[@]}"; do
  [ -n "$vfile" ] || continue
  case "$seen_vfiles" in *" $vfile "*) continue ;; esac
  seen_vfiles="$seen_vfiles$vfile "
  content "$vfile" >/dev/null 2>&1 || continue   # not tracked here → nothing to judge
  nlines="$(content "$vfile" | awk 'END{print NR}')"
  first="$(content "$vfile" | head -n1)"
  if [ "${nlines:-0}" -ne 1 ] || [ -z "$first" ]; then
    err "'$vfile' must be exactly one non-empty line (staged: ${nlines:-0} line(s))."
    printf '%s    → printf %%s "<version>" > %s   (then git add it)%s\n' "$DIM" "$vfile" "$RST" >&2
  else
    ok "'$vfile' format ok ($first)"
  fi
done

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

# ── Gate D: deploy-manifest sync (optional) ─────────────────────────────────
# A version bump that doesn't update the manifest tag ships the OLD image.
# Judged on staged blobs, like every other gate.
for m in ${DEPLOY_MANIFESTS[@]+"${DEPLOY_MANIFESTS[@]}"}; do
  [ -n "$m" ] || continue
  vfile="${m%%|*}"; rest="${m#*|}"; mfile="${rest%%|*}"; tag_re="${rest#*|}"
  content "$vfile" >/dev/null 2>&1 && content "$mfile" >/dev/null 2>&1 || continue
  want="$(content "$vfile" | head -n1)"
  have="$(content "$mfile" | sed -nE "s/.*${tag_re}.*/\1/p" | head -n1)"
  if [ -n "$have" ] && [ "$want" != "$have" ]; then
    err "version($want) != manifest tag($have) in $mfile — bump the manifest too."
  fi
done

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

# ── Gate F: 금칙 표현(한자·금칙어) ──────────────────────────────────────────
# 문서 규칙이지만 기계로 검사되므로 CLAUDE.md 문장이 아니라 여기 있다.
# 스테이징된 블롭을 바이트로 훑는다 — 로케일에 상관없이 같은 판정이 나와야 한다.
taboo_hit=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  printf '%s\n' "$f" | grep -Eq -e "$TABOO_EXCLUDE_RE" && continue
  body="$(content "$f")" || continue
  [ -n "$body" ] || continue
  for i in "${!TABOO_PATTERNS[@]}"; do
    while IFS= read -r line; do
      err "${TABOO_REASONS[$i]}"
      printf '        %s: %s\n' "$f" "$line" >&2
      taboo_hit=1
    done < <(printf '%s\n' "$body" | LC_ALL=C grep -nIE -e "${TABOO_PATTERNS[$i]}" || true)
  done
done < <(scan_targets)
[ "$taboo_hit" -eq 0 ] && ok "금칙 표현 없음(한자·금칙어)"

# ── Result ──────────────────────────────────────────────────────────────────
if [ "$fail" -ne 0 ]; then
  printf '\n%sCommit blocked.%s Fix the above, or bypass intentionally with %sgit commit --no-verify%s\n' \
    "$RED" "$RST" "$DIM" "$RST" >&2
  exit 1
fi
printf '%spraxis gate passed.%s\n' "$GRN" "$RST" >&2
exit 0
