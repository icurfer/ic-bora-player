#!/usr/bin/env bash
# praxis-review — hygiene check so the system's growth stays signal, not noise.
#
# The discipline system is meant to GROW (each incident adds a rule/gate/memory).
# This surfaces the sprawl that growth creates, so you can prune it:
#   - orphan memory files   (exist on disk but not linked in MEMORY.md)
#   - dangling index lines  (MEMORY.md points to a file that's gone)
#   - dangling Codex adapters (.agents/skills/<name>/ whose canonical
#     procedure under .claude/ was deleted — the adapter routes to nothing)
#   - growth stats + the list of active gates
#
# Read-only. It reports and proposes; it never deletes. Run:
#   bash scripts/praxis-review.sh
set -euo pipefail

MEM=".claude/memory"
IDX="$MEM/MEMORY.md"
GATE="scripts/check-conventions.sh"
SKILLS=".claude/skills"
AGENTS=".claude/agents"
ADAPTERS=".agents/skills"   # Codex-native thin adapters (route to .claude/ canon)

CYA=$'\033[36m'; YEL=$'\033[33m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
hdr() { printf '\n%s== %s ==%s\n' "$CYA" "$1" "$RST"; }

[ -d "$MEM" ] || { echo "no $MEM/ here — run from a scaffolded project root." >&2; exit 1; }

# all memory files except the index (no mapfile — bash 3.2/macOS compatible)
FILES=()
while IFS= read -r _f; do FILES+=("$_f"); done \
  < <(find "$MEM" -maxdepth 1 -name '*.md' ! -name 'MEMORY.md' | sort)

hdr "Growth"
printf '  memory files: %s\n' "${#FILES[@]}"
if [ -f "$GATE" ]; then
  # 게이트 절 헤더를 센다: `# ── ` 배너 중 gate/rule/규칙을 언급한 것.
  # (원본은 한자·프랑스어·스페인어도 찾았으나 Gate F 가 한자를 막아 빼다. 이 저장소는 영어·한글만 쓴다.)
  # 못 찾으면 `# ── ` 배너 전체로 폴백한다.
  gates="$(grep -cE '^#[[:space:]]*──.*([Gg]ate|[Rr]ule|규칙)' "$GATE" 2>/dev/null || true)"
  [ "${gates:-0}" -eq 0 ] && gates="$(grep -cE '^#[[:space:]]*──' "$GATE" 2>/dev/null || true)"
  printf '  active gates in %s: %s\n' "$GATE" "${gates:-?}"
fi
if [ -d "$SKILLS" ]; then
  n="$(find "$SKILLS" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  printf '  skills in %s: %s\n' "$SKILLS" "$n"
fi
if [ -d "$AGENTS" ]; then
  n="$(find "$AGENTS" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
  printf '  sub-agents in %s: %s\n' "$AGENTS" "$n"
fi
if [ -d "$ADAPTERS" ]; then
  n="$(find "$ADAPTERS" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  printf '  codex adapters in %s: %s\n' "$ADAPTERS" "$n"
fi

hdr "Orphan memory files (on disk, not linked in MEMORY.md)"
orphans=0
for f in ${FILES[@]+"${FILES[@]}"}; do   # guarded: empty array + set -u crashes bash <4.4
  base="$(basename "$f")"
  if ! grep -qF "$base" "$IDX" 2>/dev/null; then
    printf '  %s! %s%s  — add a line to MEMORY.md, or delete the file\n' "$YEL" "$base" "$RST"
    orphans=$((orphans+1))
  fi
done
[ "$orphans" -eq 0 ] && printf '  %s✓ none%s\n' "$GRN" "$RST"

hdr "Dangling index lines (MEMORY.md links a missing file)"
dangling=0
while IFS= read -r link; do
  [ -n "$link" ] || continue
  if [ ! -f "$MEM/$link" ]; then
    printf '  %s! %s%s  — file missing; fix or remove the MEMORY.md line\n' "$YEL" "$link" "$RST"
    dangling=$((dangling+1))
  fi
done < <(grep -E '^[[:space:]]*-[[:space:]]*\[' "$IDX" 2>/dev/null | grep -oE '\(([A-Za-z0-9_./-]+\.md)\)' | tr -d '()' | grep -v '^MEMORY.md$' || true)
[ "$dangling" -eq 0 ] && printf '  %s✓ none%s\n' "$GRN" "$RST"

# Adapters are thin by design — they route to a canonical procedure named after
# the adapter (.claude/commands/<name>.md or .claude/skills/<name>/SKILL.md).
# If the canon was deleted or renamed, the adapter still LOOKS installed but
# routes to nothing; surface that instead of letting Codex discover a dead skill.
if [ -d "$ADAPTERS" ]; then
  hdr "Dangling Codex adapters ($ADAPTERS/ routes to a missing .claude/ canon)"
  dangling_a=0
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    name="$(basename "$d")"
    if [ ! -f ".claude/commands/$name.md" ] && [ ! -f ".claude/skills/$name/SKILL.md" ]; then
      printf '  %s! %s%s  — no .claude/commands/%s.md or .claude/skills/%s/SKILL.md; restore the canon or delete the adapter\n' \
        "$YEL" "$name" "$RST" "$name" "$name"
      dangling_a=$((dangling_a+1))
    fi
  done < <(find "$ADAPTERS" -maxdepth 1 -mindepth 1 -type d | sort)
  [ "$dangling_a" -eq 0 ] && printf '  %s✓ none%s\n' "$GRN" "$RST"
fi

hdr "Next"
printf '  %sReview the rules themselves for staleness with:  /praxis-review%s\n' "$DIM" "$RST"
printf '  %s(this script finds structural sprawl; judgment about "still true?" is the slash command)%s\n' "$DIM" "$RST"
