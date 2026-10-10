# Bora 적용 정보

개발용 프로필을 선택했다. 기존 GitHub CI를 유지하고 패키지는 GitHub에서만 빌드한다.
업스트림: icurfer/ic-praxis 96aa5b13afbdbce3e6aaf580d6163195f9813aed.
아래 기본 템플릿의 CI 비활성 설명은 신규 프로젝트 기본값이며 Bora에는 적용하지 않는다.
Bora 버전 정책은 docs/RELEASING.md가 우선한다.
검사 전 변경 파일을 검토해 명시적으로 stage한다. 작업 기록은 커밋하지 않는다.

포탈 작업·인계는 [task 관리 정책](../docs/TASK_MANAGEMENT.md)을 따른다.
ic-bora 스페이스 26의 task ID를 기획/완료 문서에 적고, 포탈 댓글에는 로컬 하네스 ID와
OS·커밋·검증 결과를 남긴다. 포탈 상태와 이 하네스의 검사 상태는 자동 동기화되지 않는다.

# Praxis task harness / 작업 하네스

This folder is installed by default. CI stays off. Requires Node.js 18+ and Git;
local commit hooks remain usable without Node. No npm install is required.

에이전트에게 **“이 작업 시작해줘”**, **“검증해줘”**, **“현재 상태 알려줘”**라고
요청하세요. Codex는 `$praxis-task`, Claude Code는 `/praxis-task`로도 호출할 수
있습니다. 처음에는 에이전트가 프로젝트에 맞는 검사 명령을 설정합니다.
검사가 미설정된 상태는 통과로 처리하지 않습니다. CI는 켜지지 않습니다.

## Choose the type first / 종류 선택

Fresh installs have `profile: null` in `config/profile.json`. When you ask the
agent to apply this harness, `praxis-init` asks you to choose:

- **개발용 / development**: existing code tasks and test/build validation.
- **인프라용 / infrastructure**: separate integration placeholder; operational
  execution will be designed from a reference project supplied later.

```bash
node harness/bin/praxis.mjs profile select development
# Or: node harness/bin/praxis.mjs profile select infrastructure
node harness/bin/praxis.mjs profile status
```

No task runs until a type is selected. The agent honors a choice you already
made. Ordinary reinstalls preserve it. Switching an existing type is deliberately
not a selection operation: review configuration and local task migration first.
`--force` remains destructive template replacement and must not be used to switch.
An upgrade from pre-profile releases asks for the type once; existing development
checks and records stay in place. Both types keep CI off by default.

```text
harness/
├── config/
│   ├── profile.json          # selected type (null initially)
│   ├── project.json          # development checks, existing format preserved
│   └── infrastructure.json   # reference project and notes, no operations yet
├── profiles/
│   ├── development/README.md
│   └── infrastructure/README.md
└── src/
    ├── main.mjs              # shared selection and routing
    ├── development.mjs       # development task implementation
    └── run.mjs               # shared bounded command runner
```

Infrastructure selection succeeds, but `profile status` returns 1 (pending) and
all task commands remain blocked. Recording a reference does not enable execution.
Read only the selected guide under `profiles/`. The remaining command/check/record
sections describe **development**; they do not define an infrastructure workflow.

## Commands

Run from the installed repository (subdirectories also work):

```bash
node harness/bin/praxis.mjs --help
node harness/bin/praxis.mjs profile select development
node harness/bin/praxis.mjs task init login-fix --title "Fix login" --size small
node harness/bin/praxis.mjs task check login-fix
node harness/bin/praxis.mjs task validate login-fix
node harness/bin/praxis.mjs task status login-fix
```

`--size` defaults to `big`. Big changes need at least one nonempty plan file;
use `--plan docs/spec/plan.md --plan docs/scope/scope.md`. Existing records cannot
be overwritten. Plan existence is checked; content still requires review.

## Project checks

Edit `config/project.json` to use your project's actual commands. For a project
that provides an npm test script, an example is:

```json
{
  "schemaVersion": 1,
  "checks": [
    { "name": "tests", "command": ["npm", "test"], "timeoutSeconds": 300 }
  ]
}
```

Every check needs a unique name, nonempty executable/argument array and a timeout
of 1–3600 seconds. Commands run sequentially from the repo root with no shell
expansion; if a shell is genuinely needed, configure `bash` and a reviewed script.
Use foreground checks. On POSIX, timeout/interruption stops the started process
group; Windows stops the direct process. This is not a sandbox. Review commands as executable repository code. On Windows use Git Bash
and an executable accessible to Node (e.g. a Bash script wrapping npm).

Validation first runs the existing `scripts/check-conventions.sh` staged gate,
then the configured checks, stopping on failure. Nothing is staged, committed,
pushed or deployed by the harness itself. Commands print output to the terminal;
records store command/exit metadata, not output logs. Do not put credentials in
command arguments. Empty configuration, invalid JSON and missing plans fail closed.

## Records and freshness

`harness/.state/<id>.json` is a local, ignored record (format version 1): task ID,
title, size, plan paths, creation time and latest validation metadata. Validation
contains results, timestamp, fingerprint and pass/fail. `project.json` also uses
format version 1; fields are validated at runtime. There is no external service.

A passed record becomes stale when HEAD, the index, or tracked/nonignored files
change. Config, gate and referenced plans are included even if ignored. Ignored
build outputs and external state/dependencies are not fingerprinted: rerun checks
when those change. Submodules are currently unsupported and cause validation to
fail. Validation that changes fingerprinted files requires a rerun. A lock prevents
concurrent harness writers; after a crash, remove `.state/lock` only after checking
that no harness process remains. Local records are not tamper-proof evidence.

The staged gate only examines staged changes; the real pre-commit hook remains
necessary. This harness does not enforce every possible development path.

## Test the harness

```bash
node --test harness/test/*.test.mjs
```

Tests create disposable Git repositories and do not change the current index.

`task status` exits 0 only for current passing evidence, otherwise 1. The
`src/run.mjs` executor manages check completion, timeout and interruption.
Bora는 일반 코드 변경에 버전 증가를 요구하지 않는다. 버전 형식·릴리스 검증은 기존
scripts/version_policy.py와 docs/RELEASING.md를 따른다.
