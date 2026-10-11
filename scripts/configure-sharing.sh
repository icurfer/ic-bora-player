#!/usr/bin/env bash
# Configure publication scope without staging, untracking, or publishing files.
set -euo pipefail
MODE="${1:-auto}"
TARGET="${2:-.}"
case "$MODE" in auto|personal|shared) ;; *) echo 'Usage: configure-sharing.sh [auto|personal|shared] [target]' >&2; exit 2;; esac
ROOT="$(cd "$TARGET" && pwd -P)"
for component in "$ROOT/harness" "$ROOT/harness/config" "$ROOT/harness/config/sharing" "$ROOT/.gitignore"; do
  [ ! -L "$component" ] || { echo 'Refusing symlinked publication configuration.' >&2; exit 1; }
done
SETTING="$ROOT/harness/config/sharing"
if [ "$MODE" = auto ]; then
  if [ -f "$SETTING" ]; then MODE="$(cat "$SETTING")"; else MODE=personal; fi
fi
case "$MODE" in personal|shared) ;; *) echo 'Invalid sharing setting; expected personal or shared.' >&2; exit 1;; esac
# A linked worktree may keep its Git metadata outside ROOT. Never write there:
# use an explicit, managed .gitignore block as the portable fallback.
EXCLUDE=""
if [ "$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)" = "$ROOT" ]; then
  GITDIR="$(git -C "$ROOT" rev-parse --absolute-git-dir)"
  GITDIR="$(cd "$GITDIR" && pwd -P)"
  case "$GITDIR" in
    "$ROOT"/*)
      if [ ! -L "$ROOT/.git" ] && [ ! -L "$GITDIR/info" ] && [ ! -L "$GITDIR/info/exclude" ]; then
        EXCLUDE="$GITDIR/info/exclude"
      fi ;;
  esac
fi
BEGIN='# praxis:personal:begin'
END='# praxis:personal:end'
TEMP=""
trap '[ -z "$TEMP" ] || rm -f "$TEMP"' EXIT
rewrite() {
  local file="$1" add="$2"
  mkdir -p "$(dirname "$file")"
  TEMP="$(mktemp "${file}.praxis.XXXXXX")"
  if [ -f "$file" ]; then
    awk -v b="$BEGIN" -v e="$END" '
      $0==b {if (inside || seen) exit 2; inside=1;seen=1;next}
      $0==e {if (!inside) exit 2;inside=0;next}
      !inside {print}
      END {if (inside) exit 2}
    ' "$file" > "$TEMP" || { echo "Malformed managed block: $file" >&2; exit 1; }
  fi
  if [ "$add" = yes ]; then
    printf '%s\n' "$BEGIN" >> "$TEMP"
    printf '%s\n' '/harness/' '/docs/requirements/' '/docs/spec/' '/docs/scope/' '/docs/deferred/' '/docs/done/' >> "$TEMP"
    printf '%s\n' "$END" >> "$TEMP"
  fi
  if [ -f "$file" ] && cmp -s "$file" "$TEMP"; then rm -f "$TEMP"; else mv "$TEMP" "$file"; fi
  TEMP=""
}
IGNORE="$ROOT/.gitignore"
if [ -n "$EXCLUDE" ]; then
  if [ -f "$IGNORE" ] && grep -qxF "$BEGIN" "$IGNORE"; then rewrite "$IGNORE" no; fi
  if [ "$MODE" = personal ]; then rewrite "$EXCLUDE" yes
  elif [ -f "$EXCLUDE" ] && grep -qxF "$BEGIN" "$EXCLUDE"; then rewrite "$EXCLUDE" no; fi
else
  if [ "$MODE" = personal ]; then rewrite "$IGNORE" yes
  elif [ -f "$IGNORE" ] && grep -qxF "$BEGIN" "$IGNORE"; then rewrite "$IGNORE" no; fi
fi
mkdir -p "$ROOT/harness/config"
TEMP="$(mktemp "${SETTING}.XXXXXX")"
printf '%s\n' "$MODE" > "$TEMP"
mv "$TEMP" "$SETTING"; TEMP=""
echo "Publication scope: $MODE (harness and development records). No files staged or published."
if [ "$MODE" = personal ]; then
  echo 'User guides and public changelogs remain eligible for commit.'
  if [ -z "$EXCLUDE" ]; then echo 'Using .gitignore fallback: Git metadata is absent or outside this target.'; fi
  if [ "$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)" = "$ROOT" ]; then
    TRACKED="$(git -C "$ROOT" ls-files -- harness docs/requirements docs/spec docs/scope docs/deferred docs/done)"
    if [ -n "$TRACKED" ]; then
      echo 'Already tracked: ignore rules cannot hide these. Review before untracking; history is unchanged.'
      printf '%s\n' "$TRACKED"
    fi
  fi
fi
