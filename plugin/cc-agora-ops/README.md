# cc-agora-ops

AgentAgora 운영자 도구 Claude Code 플러그인. 워커 spawn, 팀 일괄 셋업, 통신 매트릭스 관리, 로컬 서버 기동을 담당한다. 통신 코어(`invoke`·`broadcast` 등)는 `cc-agora` 플러그인에 있으며, 이 플러그인과는 의존성이 없다.

## 슬래시 명령

| 슬래시 | 시그니처 | 동작 |
| ------ | -------- | ---- |
| `/cc-agora-ops:agora-spawn` | `<id> <role> "<description>" [--dir --force --server-url]` | 워커 1명 채널 모드 셋업 — thin CLAUDE.md + .mcp.json + run.bat + .claude/settings.local.json 생성. |
| `/cc-agora-ops:agora-design-worker` | `[<id>] [--dir --force --server-url]` | 운영자와 대화해 커스텀 페르소나를 작성하고 워커를 스캐폴딩 — 7개 사전 정의에 없는 역할용. 페르소나는 `.claude/CLAUDE.md`에. |
| `/cc-agora-ops:agora-spawn-team` | `<manifest.json> [--dir --launch=off/manual/auto --force --server-url]` | manifest JSON으로 팀 전체 일괄 spawn. 부분 실패 시 sequential abort. |
| `/cc-agora-ops:agora-comm-matrix` | `[<csv-path>] [--server-url]` | 서버의 통신 매트릭스를 GET(조회) 또는 POST(교체). 토큰 게이트 `/admin/comm-matrix` 엔드포인트 사용. |
| `/cc-agora-ops:agora-make-comm-matrix` | `[<out-path>]` | 라이브 등록 인스턴스로 통신 매트릭스 CSV를 작성. 토폴로지 선택 후 N×N(+`*` fallback) CSV 생성. |
| `/cc-agora-ops:agora-dashboard` | `[--server-url]` | 팀 현황 대시보드를 브라우저로 연다. |
| `/cc-agora-ops:agora-setup` | `[--dir]` | AgentAgora 배치 전체를 한 번에 부트스트랩 — 서버 기동 스크립트·스키마·권한·워커 로스터. 각 에이전트는 `agora-design-worker`로 생성. |

## 로컬 서버 기동 (`run-server.bat`)

`templates/run-server.bat`을 사용하면 AgentAgora MCP 서버를 로컬에서 간단히 띄울 수 있다.

1. `templates/run-server.bat`을 워크스페이스 루트에 복사한다.
2. 더블클릭하거나 터미널에서 `run-server.bat`을 실행한다.
3. 서버는 `http://127.0.0.1:8420/mcp`에서 기동된다.
4. 중단은 해당 창에서 `Ctrl+C`.

`agent-agora` 콘솔 스크립트가 PATH에 있으면 그것을 쓰고, 없으면 `py -3.13 -m agent_agora`로 폴백한다.

## 워커 spawn 산출물

`/cc-agora-ops:agora-spawn <id> <role> "<description>"` 실행 시 `<id>/` 하위에 다음 파일이 생성된다:

| 파일 | 설명 |
| ---- | ---- |
| `CLAUDE.md` | thin 인스턴스 설명 — 역할·책임·페르소나 플러그인 적용 지시. 페르소나 본문은 포함하지 않는다. |
| `.mcp.json` | 2-서버 구성 — AgentAgora HTTP 서버 + agora-channel stdio 어댑터. `X-Agora-*` 헤더로 자동 등록. |
| `run.bat` | 채널 모드 기동 스크립트. `--dangerously-load-development-channels server:agora-channel`로 claude를 기동. |
| `.claude/settings.local.json` | 워커별 페르소나 플러그인 활성화. `extraKnownMarketplaces`에 로컬 AgentAgora 저장소를 등록하고, `enabledPlugins`에 `cc-agora-<role>@agentagora: true`를 설정. |

페르소나 플러그인(`cc-agora-coder`, `cc-agora-orchestrator` 등)은 Plan 3에서 생성된다. 플러그인이 없어도 spawn 자체는 동작하며, 워커를 실제 기동하면 Plan 3 머지 후 정상 작동한다.

## 요구 사항

- Python 3.13+ (`agent_agora`가 `pip install -e .` 또는 `uv tool install .`로 설치돼 있어야 함).
- AgentAgora MCP 서버가 실행 중이어야 한다 (기본 `http://127.0.0.1:8420/mcp`).
- `--launch=auto` 사용 시 Windows Terminal(`wt.exe`)이 PATH에 있어야 한다. 부재 시 `--launch=manual`로 자동 강등.
- `agora-comm-matrix`의 POST 동작은 서버가 `AGORA_ADMIN_TOKEN` 환경 변수로 기동돼 있어야 한다.
