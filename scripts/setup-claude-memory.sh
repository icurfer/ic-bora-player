#!/usr/bin/env bash
# Symlink this repo's .claude/memory into Claude Code's global memory path, so
# your project's rules/memory are versioned in git AND loaded every session —
# and shared with the team via commit/PR.
#
# Run once per clone, from the repo root:  bash scripts/setup-claude-memory.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/.claude/memory"

[ -d "$SRC" ] || { echo "ERROR: $SRC not found. Run from the repo root." >&2; exit 1; }

# Claude Code encodes a project path by replacing every '/' with '-'.
ENCODED="$(echo "$REPO_ROOT" | sed 's|/|-|g')"
TARGET_DIR="$HOME/.claude/projects/$ENCODED"
TARGET="$TARGET_DIR/memory"

mkdir -p "$TARGET_DIR"

# If a real directory (not a symlink) already lives there, back it up first.
if [ -d "$TARGET" ] && [ ! -L "$TARGET" ]; then
  BACKUP="$TARGET.bak.$(date +%Y%m%d%H%M%S)"
  echo "existing memory dir found → backing up to: $BACKUP"
  mv "$TARGET" "$BACKUP"
fi

# Windows (Git Bash/MSYS/Cygwin): plain `ln -s` silently COPIES instead of
# linking, which defeats git-versioning (the copy diverges). Force a native
# symlink (needs Developer Mode), else fall back to an NTFS junction (no admin
# needed). `winsymlinks:nativestrict` makes ln FAIL instead of copying — Git
# Bash/MSYS2 read it from MSYS=, Cygwin from CYGWIN=, so set both.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    # Remove only a LINK at $TARGET (a real dir was backed up above). NEVER
    # `rm -rf` here: an rm that doesn't treat an NTFS junction as a link would
    # recurse THROUGH it and delete the repo's memory source files.
    if [ -L "$TARGET" ]; then
      rm -f "$TARGET"
    elif [ -d "$TARGET" ]; then
      cmd //c rmdir "$(cygpath -w "$TARGET")" >/dev/null 2>&1 || true  # junction/empty dir only — rmdir never recurses
    fi
    if MSYS=winsymlinks:nativestrict CYGWIN=winsymlinks:nativestrict \
         ln -sfn "$SRC" "$TARGET" 2>/dev/null && [ -L "$TARGET" ]; then
      :  # native symlink
    elif cmd //c mklink /J "$(cygpath -w "$TARGET")" "$(cygpath -w "$SRC")" >/dev/null 2>&1; then
      :  # NTFS junction — native Windows apps (Claude Code) can traverse it
    else
      echo "ERROR: could not create a symlink or junction." >&2
      echo "  Enable Windows Developer Mode (Settings > For developers) and re-run." >&2
      exit 1
    fi ;;
  *) ln -sfn "$SRC" "$TARGET" ;;
esac
echo "✓ linked: $TARGET -> $SRC"
echo "  Your .claude/memory is now git-versioned and loaded by Claude Code each session."
