---
description: 구조 매니페스트로 파티션마다 워커별 스테이징 디렉터리를 만들고 다중 기동한다.
---

# /agora-structure-spawn

구조 매니페스트를 읽어 파티션마다 워커 스테이징 디렉터리를 만들고, 채널 모드로 다중 기동한다.

## 인자

`$ARGUMENTS`를 `structure_spawn.py`에 그대로 전달한다:

- `--manifest <path>` — **필수**. 매니페스트 JSON 경로.
- `--out <path>` — 스테이징 디렉터리 부모 (기본: `<repo>/.agora-structure/workers/`).
- `--worktree-base <path>` — 워커가 만들 worktree의 예약 베이스 (기본: `<repo-parent>/<repo>.structure-worktrees/`).
- `--server-url <url>` — MCP HTTP 서버 (기본: `http://127.0.0.1:8420/mcp`).
- `--launch off|manual|auto` — 기동 모드 (기본: `manual`).
- `--force` — 기존 스테이징 디렉터리 덮어쓰기.

## 실행

Bash 도구로 실행한다:

```bash
python <plugin-root>/scripts/structure_spawn.py $ARGUMENTS
```

여기서 `<plugin-root>`은 `<repo>/plugin/cc-agora-structure/`(마켓플레이스 등록 경로 기준)이며, 절대경로로 해석한다.

## 결과

- 각 파티션마다 `<out>/<partition-id>/` 안에 `CLAUDE.md`·`.mcp.json`·`.claude/settings.local.json`·`run.bat`이 생성된다.
- `--launch=manual`(기본)이면 기동 커맨드가 출력된다 — 운영자가 복사해 실행.
- `--launch=auto`면 `wt.exe` 탭으로 즉시 기동.
- 타깃 레포가 git 레포가 아니면 종료 코드 2로 거부.

워커는 기동 직후 idle 상태이며, agora로 첫 구현 task를 받으면 superpowers `using-git-worktrees` 스킬로 자기 파티션의 worktree+sparse-checkout(콘 모드)을 만들어 작업한다.
