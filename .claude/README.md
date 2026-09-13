# .claude

이 저장소가 git 으로 공유하는 Claude Code 자산 — 메모리(지속적 규칙·사실), 스킬, 슬래시 커맨드.
커밋해 두면 새로 클론하는 사람도, 다음 세션도 같은 규칙과 같은 교훈을 받는다.

## 구성

- `memory/` — 세션을 넘는 메모리. 파일 하나에 사실 하나
  - `MEMORY.md` — 색인. 매 세션 로드된다(한 메모리당 한 줄)
  - `feedback_*.md` — 작업 규칙(각각 *왜* + *어떻게 적용* 포함)
  - `project_*.md` — 지속적인 프로젝트 사실
  - `reference_*.md` — 외부·내부 자료 포인터
- `commands/` — 슬래시 커맨드 (`/praxis-review`)
- `skills/` — 스킬 (`verify-app`)

## 메모리를 세션 너머로 유지하기

Claude Code 는 `~/.claude/projects/<인코딩된-저장소-경로>/memory/` 에서 메모리를 읽는다.
아래 스크립트가 이 저장소의 `.claude/memory/` 를 그 위치에 심볼릭 링크로 걸어 준다:

```bash
bash scripts/setup-claude-memory.sh
```

클론마다 한 번 실행한다. 그 뒤로는 메모리 수정이 곧 git 변경이 되어 커밋으로 함께 이동한다.

> 이 머신 주의: 저장소가 `/data/...` 와 `/home/ubuntu/data/...` 두 경로로 모두 열린다
> (`/home/ubuntu/data` 는 `/data` 심볼릭 링크). Claude Code 는 **연 경로 문자열 그대로**
> 메모리 디렉터리 이름을 만들기 때문에 두 경로가 서로 다른 메모리를 본다.
> 스크립트는 실행 당시의 경로 하나만 연결하므로, 다른 경로로도 연다면 그쪽에도 같은 링크를 건다.

## 무엇을 커밋하나

- 커밋한다: `.claude/memory/**`, `.claude/README.md`, `.claude/commands/**`, `.claude/skills/**`
- 커밋하지 않는다: `.claude/settings.local.json` 등 로컬 캐시 (`.gitignore` 에 넣는다)
