# AgentAgora

다중 에이전트 메시지 라우팅 MCP 서버. Claude Code 인스턴스(워커)들이 서로 task를 dispatch하고 결과를 주고받는 broker다.

## 구조

- `src/agent_agora/` — 서버 (v3 messaging)
  - `server.py` — FastMCP 앱, `agora.*` 도구 정의
  - `dispatcher.py` — 메시지 라우터 (in-memory 큐 + SQLite cold path)
  - `registry.py` — `instance_id` ↔ `session_id` 매핑
  - `persistence.py` — SQLite (conversations · messages), AsyncWriteQueue
  - `envelope.py` — 메시지 envelope dataclass + 검증
  - `auto_register.py` — `X-Agora-*` 헤더 기반 자동 등록 ASGI 미들웨어
  - `__main__.py` — CLI 진입점
- `plugin/cc-agora/` — Claude Code 플러그인. 워커 spawn + 통신 슬래시 skill 9개
- `examples/echo_bot/` — 테스트용 MCP client 봇
- `tests/` — pytest (`test_v3_*`, `test_plugin_*`, `test_integration`)
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
