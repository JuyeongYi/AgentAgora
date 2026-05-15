# Backlog — 미뤄둔 작업

2026-05-15 기준. 다음 세션에서 이어갈 항목.

## spec 완료 — 구현 대기

- **cc-agora bots** — [spec](superpowers/specs/2026-05-15-cc-agora-bots-design.md). pub/sub broker 모델, 봇 fire-and-forget + `agora.bot_emit`(결정 25, B2).
  - **Plan 1 (스키마 강제) 구현 완료** — [plan](superpowers/plans/2026-05-16-cc-agora-bots-1-schema.md). SchemaRegistry, `dispatch`/`broadcast` msgtype 강제, schema 카탈로그(`.agentagora/schemas.jsonl`), `agora.register_schema`/`schemas`/`schemas_list` 도구. 전체 테스트 171개 통과.
  - **Plan 2 (봇 라우팅) 구현 완료** — [plan](superpowers/plans/2026-05-16-cc-agora-bots-2-routing.md). BotRegistry, broker fan-out(`subscribed`/`cc`), `agora.register_bot`/`bot_emit`/`bots`/`find` 도구, observer 모드, target 생략 schema-routed dispatch, `no_route` 에러. 전체 테스트 219개 통과.
  - **다음 작업 (미구현):** plugin v2.2 — `agora-spawn-bot` 슬래시 커맨드, `agora_bot_sdk`, `bot.py.template`(spec §3.11 / §8 item 9). 기존 cc-agora 워커 payload에 `msgtype` 주입 + `examples/echo_bot` 업데이트(broker 실 배포 전 필수).
- **통신 매트릭스** — [spec](superpowers/specs/2026-05-15-comm-matrix-design.md). **구현 완료** — `CommMatrix`(CSV worker↔worker ACL), `dispatch` comm_denied / `broadcast` denied 필터, `agora.register_comm_matrix` 도구, 시작 시 `.agentagora/comm-matrix.csv` 로드. 전체 테스트 244개 통과.
  - **후속 미구현 (spec §7):** 런타임 등록분 영속, 동적 워커 자동 행·열, role 기반 ACL, 매트릭스 조회 도구.

## 개선 항목

- **서버 로그 payload pretty-print** — `src/agent_agora/dispatcher.py`의 `_fmt_payload`가 현재 `json.dumps(payload, ensure_ascii=False, separators=(",", ":"))`로 payload를 한 줄 압축 출력한다. 로그(`[agora] <from> -> <to> : <payload>`)에서 JSON/jsonl payload가 읽기 나쁘다. 들여쓰기 포맷팅(`indent=2`)으로 출력해 가독성 개선. trade-off — 멀티라인 로그는 grep이 약간 불편하나 사용자 요청대로 가독성 우선.
- **기존 AgoraTest 워커 stop-hook** — `C:/Users/jylee/Documents/카카오톡 받은 파일/AgoraTest/`의 Inst2~Inst8 `settings.local.json` prompt가 "wait 즉시 호출"만 있어 "대화만 하고 작업 안 함" 문제가 남아있다. plugin template(`plugin/cc-agora/templates/settings.local.json.template`)은 "작업 우선" prompt로 재정비됐으나 기존 워커는 미적용 — 교체 필요.
