# cc-agora-structure

AgentAgora 운영자 플러그인 — 타깃 레포의 폴더 구조를 분석해 워커별 파티션을 산출하고, 파티션마다 범위 한정 워커를 다중 스폰한다.

## 요구사항

이 플러그인은 [code-review-graph](https://pypi.org/project/code-review-graph/)를 의존한다. `.mcp.json`에 MCP 서버를 선언하지만, **CLI 패키지는 별도 설치해야 한다**:

```bash
pip install code-review-graph
```

설치 후 `code-review-graph serve`가 PATH에서 실행 가능해야 한다.

## 사용

1. `/agora-structure-analyze` — 현재 레포를 분석해 구조 매니페스트를 `<repo>/.agora-structure/manifest.json`에 작성한다. 운영자가 검토·편집.
2. `/agora-structure-spawn --manifest <path>` — 매니페스트로 파티션마다 워커별 스테이징 디렉터리 생성 + 채널 모드 다중 기동.

워커는 첫 구현 task 수신 시 superpowers `using-git-worktrees` 스킬로 자기 파티션의 worktree+sparse-checkout(콘 모드)을 생성해 작업한다. 자세한 설계는 `docs/superpowers/specs/2026-05-20-spawn-by-structure-design.md` 참조.

## 범위 강제 4계층

1. **sparse-checkout** — 워커가 첫 task에 콘 모드로 파티션 폴더만 머티리얼라이즈, 그 외 파일이 worktree 디스크에 없음.
2. **CWD** — 세션 CWD = 스테이징 디렉터리, 작업은 Bash `cd`로 worktree.
3. **scoped CLAUDE.md** — 파티션 + worktree 절차 + 크로스파티션 규칙.
4. **settings.local.json permission** — Edit/Write 허용 = 스테이징 + 예약 worktree만.

크로스파티션 읽기는 code-review-graph MCP, 쓰기는 agora 디스패치.
