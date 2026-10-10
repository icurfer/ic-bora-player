---
description: Route task requests by the selected harness type; run development tasks or explain pending infrastructure setup
---

Use this procedure when the user asks to start a task, check progress or verify
work. Explain the result in the user's language; users need not learn commands.
The executable lives in `harness/`, shared by Claude Code and Codex.

First read `harness/config/profile.json`. Bora uses development. If the type is unset, select development with
`node harness/bin/praxis.mjs profile select development` before creating a task.
If it is `infrastructure`, read `harness/profiles/infrastructure/README.md`,
explain pending reference-project integration and stop; do not run development
commands as a substitute. Only `development` uses the procedure below.

1. Read `harness/README.md` and `harness/config/project.json`. Check Node.js 18+
   is available. If missing, explain the prerequisite; local Git gates still work.
2. For a new task, select a short unique ID, infer a concrete title and classify
   the change using the constitution. Default to `big` when uncertain. Reuse
   existing plans; for a big change, write the required spec/scope documents and
   reference them with repeated `--plan` options. Do not fabricate user approval.
3. Run `node harness/bin/praxis.mjs task init <id> --title <title> --size <size>`
   with any plan references. Existing IDs are never overwritten. Records live in
   ignored `harness/.state/`; preserve them and do not commit personal records.
4. If checks are not configured, inspect the project's actual documented test and
   build commands, then configure `harness/config/project.json`. Use executable
   argument arrays, not shell strings. Never substitute a no-op merely to pass.
   Commands are trusted repository code: inspect changes before running them.
   Use foreground, bounded checks; no servers, deployment, publishing or messages.
5. Run `task check <id>` before implementation. A pass checks required files and
   configuration, not the semantic quality of the plan. Review that separately.
6. Review and stage only intended inputs; `scripts/check-index-clean.sh` rejects
   unstaged/untracked inputs so checked code matches the index. Run `task validate <id>` after implementation. It calls the existing staged
   Git gate plus configured project checks. It does not stage or commit files.
   Unstaged changes are included in the freshness fingerprint, but the gate's
   commit rules still inspect the index; the real commit hook remains necessary.
7. Run `task status <id>` to report progress. Explain blockers and the next step.
   After file/index/HEAD changes, rerun validation. Do not call unit checks E2E.

Do not create extra CI workflows or deploy just to run this procedure.
Bora already uses GitHub CI by user request; retain its package build and upload.
Read `docs/TASK_MANAGEMENT.md` before task intake. Use the installed task-register
skill to read space 26 and the target task/comments, reuse existing work, and
record the portal task ID alongside this local harness ID in the task documents.
Portal status and handoff updates follow that policy; harness validation does not
update the portal automatically. Missing portal access must be reported explicitly.
Commit/push follow AGENTS.md and docs/RELEASING.md. The harness is a local
workflow aid, not a security boundary or a replacement for code review.
