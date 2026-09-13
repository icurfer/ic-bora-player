---
description: Review the discipline system for sprawl and prune what no longer earns its place
---

The discipline system grows with every incident — which is the point, but growth
without pruning becomes noise. Review it and propose a cleanup.

Do this:
1. Run `bash scripts/praxis-review.sh` and read its output (orphan memory
   files, dangling index lines, growth stats, active gates).
2. **Judge staleness** — read `.claude/memory/*.md` and `scripts/check-conventions.sh`.
   Flag anything that:
   - no longer matches the codebase (names a file/flag/path that's gone),
   - duplicates another rule,
   - is a `(STARTER RULE …)` that this project never adopted,
   - is a gate that can no longer fire (its `CODE_RE`/pattern matches nothing here).
3. **Propose, don't delete.** Present a short table: item → why prune → keep/remove
   recommendation. Wait for the user to confirm.
4. On confirmation: delete the agreed files/lines, update `.claude/memory/MEMORY.md`
   to match, and remove dead gates from `check-conventions.sh`.
5. Fix any orphan/dangling issues the script found (add the missing index line, or
   remove the stale one).

Principle: keep every surviving rule EARNED — tied to a real incident and still
true. A lean, high-signal system beats a large stale one. Prune generously.
