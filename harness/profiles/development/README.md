# Development harness / 개발용

Selected as `development` in `harness/config/profile.json`.
Implementation: `harness/src/development.mjs`; shared bounded runner: `src/run.mjs`.
Checks remain in `harness/config/project.json` so existing development configuration
and task records need not move. Follow `.claude/commands/praxis-task.md` for
`task init/check/validate/status`. See `harness/README.md` for command details.

This profile verifies code changes and configured local checks. A successful
check is not evidence of current production infrastructure health.
