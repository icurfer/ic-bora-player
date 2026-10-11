#!/usr/bin/env bash
# Local commit safeguard, not proof of human approval or a server security boundary.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
MODE=personal
if [ -f harness/config/sharing ]; then MODE="$(cat harness/config/sharing)"; fi
case "$MODE" in personal|shared) ;; *) echo 'Invalid publication scope.' >&2; exit 1;; esac
fail=0
while IFS= read -r -d '' file; do
  case "$file" in
    harness/.state/*|harness/config/profile.json.lock)
      echo "Local runtime record must not be committed: $file" >&2; fail=1 ;;
    harness/*|docs/requirements/*|docs/spec/*|docs/scope/*|docs/deferred/*|docs/done/*)
      if [ "$MODE" = personal ]; then
        echo "Personal scaffold file staged: $file. Review publication scope with the user; do not force-add or auto-untrack." >&2
        fail=1
      elif [ "$(git show :harness/config/sharing 2>/dev/null || true)" != shared ]; then
        echo "Stage the reviewed shared scope declaration with the published files: harness/config/sharing" >&2
        fail=1
      fi ;;
  esac
done < <(if [ "${1:-}" = --all ]; then git ls-files -z; else git diff --cached --name-only --diff-filter=ACMRT -z; fi)
exit "$fail"
