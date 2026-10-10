#!/usr/bin/env bash
# Run before checks that read working files. Arguments are Git pathspecs.
# Never stage, stash or overwrite the user's files.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
[ "$#" -gt 0 ] || set -- .
if ! git diff --quiet -- "$@"; then
  echo 'FAIL: check inputs differ from the Git index. Review and stage the intended inputs first.' >&2
  exit 1
fi
if [ -n "$(git ls-files --others --exclude-standard -- "$@")" ]; then
  echo 'FAIL: untracked check inputs exist. Review and stage or explicitly ignore them first.' >&2
  exit 1
fi
if [ -n "$(git ls-files --unmerged -- "$@")" ]; then
  echo 'FAIL: unresolved index entries.' >&2
  exit 1
fi
