# AgentAgora

다중 에이전트 메시지 라우팅 MCP 서버. Claude Code 인스턴스(워커)들이 서로 task를 dispatch하고 결과를 주고받는 broker다.

## 구조

- `src/agent_agora/` — 서버 (v4 messaging)
  - 라우팅 코어: `server.py`(FastMCP `agora.*` 도구), `dispatcher.py`(메시지 라우터 — in-memory 큐 + SQLite cold path), `conversation_store.py`·`dispatch_console.py`, `envelope.py`(메시지 envelope + 검증), `errors.py`
  - 레지스트리: `registry/` 서브패키지 — `core.py`(`_BidirectionalRegistry` 베이스 + `InstanceRegistry` + operator 헬퍼), `bot.py`(`BotRegistry` 봇 네임스페이스). `__init__`가 공개 표면 re-export.
  - 영속: `persistence.py`(SQLite WAL — conversations·messages, AsyncWriteQueue), `dispatch_persistence.py`, `schemas.py`(런타임 가변 JSON Schema 카탈로그), `sweeper.py`(주기 sweep — TTL·dead-session·GC)
  - HTTP 라우트·미들웨어: `auto_register.py`(`X-Agora-*` 자동 등록), `admin_routes.py`(`AGORA_ADMIN_TOKEN` 게이팅), `channel_routes.py`(`GET /channel/wait`)
  - 대시보드: `dashboard/` 서브패키지 — `routes.py`(HTTP 라우트 + `dashboard.html`·`dashboard_static/` 동거), `events.py`(SSE 브로커), `auth.py`(`DashboardAuthMiddleware`), `health.py`. `__init__`가 공개 표면 re-export.
  - 채널 모드: `channel_adapter.py`(워커별 stdio MCP 채널 서버 — 인박스 감지 → `claude/channel` 알림)
  - 봇 SDK: `bot.py`(`AgoraBot` 베이스 클래스), `_broker_http.py`(채널/봇 공유 `/channel/wait` HTTP 클라이언트)
  - 파일 공유: `files/` 서브패키지 — `store.py`(`FileStore`)·`policy.py`(`FilePolicy`)·`routes.py`(업로드/다운로드 HTTP)
  - 통신 매트릭스: `comm_matrix.py`(워커↔워커 dispatch ACL)
  - TLS: `certs.py`(self-signed 인증서)
  - `__main__.py` — CLI 진입점
- `plugin/` — Claude Code 플러그인 마켓플레이스 (`.claude-plugin/marketplace.json` — 9개 플러그인)
  - `cc-agora/` — 통신 코어 (메시지 dispatch·broadcast·종결 슬래시 + `agora-protocol` 운용 규칙)
  - `cc-agora-ops/` — 운영자 도구 (워커·팀 spawn, 통신 매트릭스, 대시보드, 배치 셋업)
  - `personas/` — 역할 페르소나 7종 (coder·reviewer·tester·writer·planner·orchestrator·general)
- `examples/` — 테스트·데모용 MCP client (`echo_bot`, `comm_demo`)
- `tests/` — pytest (`test_v3_*`·`test_v4_*`·`test_channel_*`·`test_file_*`·`test_plugin_*`·`test_integration` 등)
- `docs/` — 사용자·운영 문서 (`plugins.md`·`channel-mode.md`·`bot-sdk.md`·`usage-guide.md`·`file-sharing.md` 등)
  - `docs/superpowers/specs/` — 설계 문서 (spec 우선 — 구현 전 확인)
  - `docs/backlog.md` — 진행 중·미뤄둔 작업

## 개발

- Python 3.13 타겟. (3.11 환경엔 `agent_agora`가 설치돼 있지 않을 수 있음 — plugin 테스트는 3.11에서도 동작.)
- 서버 실행: `python -m agent_agora --port 8420 --no-tls --no-timeout`
- 테스트: `python -m pytest tests/ -v`
- 설계는 spec 우선. 새 기능은 `docs/superpowers/specs/`에 spec을 먼저 두고, 결정 트레일을 보존한다.

## 규약

- Windows 대상 JSON(`.mcp.json`, `settings.local.json` 등) 안의 path·shell 문자열은 forward slash로 쓴다. backslash는 hook/spawn 레이어에서 escape 충돌을 일으킨다.
- 산출물(plugin preset, README, spec)은 한국어 우선. 코드 식별자·JSON 키·MCP 도구명, 그리고 스킬(SKILL.md 본문·frontmatter)·서브에이전트 정의는 영어로 작성한다.
- 로그 페이로드에 원본 바이너리 에셋을 넣지 않는다 — 작은 파생물(요약·해시)만.
