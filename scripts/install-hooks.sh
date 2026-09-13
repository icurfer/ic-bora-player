#!/usr/bin/env bash
# Point this repo's git hooks at .githooks/ (run once per clone).
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
chmod +x "$ROOT/.githooks/pre-commit" "$ROOT/scripts/check-conventions.sh" 2>/dev/null || true
git -C "$ROOT" config core.hooksPath .githooks
echo "✓ core.hooksPath = .githooks — the praxis gate is now active."
echo "  Test it: stage a code change without bumping the version file and try to commit."
