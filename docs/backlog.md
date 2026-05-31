# Backlog — 미뤄둔 작업

## 진행 중

- **wait-tool-gating** — `agora.wait_notify`(블로킹 long-poll)를 채널 모드 워커
  (Claude Code)의 MCP 도구 표면에서 들어내는 작업. spec 완료 —
  `docs/superpowers/specs/2026-05-18-wait-tool-gating-design.md`, 브랜치
  `wait-tool-gating`. 다음 단계는 구현 플랜 작성 → 구현 → 브랜치 마무리. 설계
  요지: `GET /channel/wait` HTTP 엔드포인트 신설(always-on), `agora-channel`
  어댑터·`AgoraBot` SDK를 HTTP로 전환, MCP `agora.wait_notify`는 기본 비등록 +
  `--add-wait` 플래그로만 등록.

## MCP 표준 추적 — 2026-07-28 RC

MCP가 2026-07-28 릴리스 후보를 발표했다(RC 잠금 2026-05-21, 최종 2026-07-28).
프로토콜 버전 `2026-07-28`(이전 `2025-11-25`). **아직 최종 릴리스 전이므로 지금은
영향 파악·추적만 한다.** 출처: blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate

**설계 입장 — stateless transport는 채택하지 않는다 (의도).** RC의 핵심은 무상태
전환(handshake `initialize` 제거 SEP-2575, 세션 `Mcp-Session-Id` 제거 SEP-2567,
round-robin LB 지원)이지만, AgentAgora는 본질적으로 **장기 유지되는 워커 프로세스
간 통신을 중개하는 stateful broker**다. instance↔session 매핑, `agora.instances`/
`agora.bots` 같은 엔트리 리스트 기능은 stateful 상태를 전제로 하며 무상태성과
상충한다. 따라서 RC가 세션을 프로토콜에서 들어내더라도 AgentAgora는 stateful
transport를 계속 쓰는 것이 옳다. 관건은 **mcp 라이브러리가 stateful(streamable-HTTP
+ 세션) 모드를 계속 지원하는지** 추적하는 것이며, 우리 정체성 모델 자체를 바꿀
필요는 없다. (`auto_register.py`의 `mcp-session-id` 헤더 의존은 라이브러리가
세션 헤더를 계속 제공하는 한 유지 가능.)

호환성 관점에서 최종 릴리스 전 점검할 항목(우선순위순):

- **mcp 라이브러리 버전 핀** — `pyproject.toml`의 `mcp>=1.0`. RC 지원 버전이
  나오면 stateful 모드가 계속 동작하는지 확인 후 핀 갱신. (가장 먼저 영향)
- **JSON Schema 2020-12 지원 (SEP-2106)** — `oneOf`/`anyOf`/`$ref`/`$defs` 허용.
  `schemas.py` 카탈로그의 표현력을 넓힐 기회. 단 외부 `$ref` URI 자동 역참조 금지·
  스키마 깊이/검증시간 제한 필요.
- **에러코드 `-32002`→`-32602` (SEP-2164)** — 우리 코드엔 리터럴 JSON-RPC 코드
  매칭이 없어(확인됨) 직접 영향 적음. 라이브러리 레벨에서 흡수.
- **Tasks extension (SEP-2663)** — `tools/call→task handle`, `tasks/get/update/cancel`.
  우리 `dispatch(expect_result)→reply→close_thread`와 개념적 동형. 표준 MCP
  클라이언트 호환 표면을 한 겹 입히는 기회(선택). 단 RC가 `tasks/list`를
  무상태성 때문에 제거한 점은 우리와 무관(우리는 stateful 유지).
- **신규 헤더 `Mcp-Method`/`Mcp-Name` (SEP-2243)** — 라이브러리가 처리. 우리
  ASGI 미들웨어 체인이 통과시키는지만 확인.
- **플러그인 워커 `.mcp.json`은 이미 RC-friendly** — `cc-agora-ops`·
  `cc-agora-structure`의 워커 템플릿(`mcp.json.template`, `worker-mcp.json.template`)은
  워커 정체성을 표준 MCP 세션이 아니라 **매 HTTP 요청에 실리는 커스텀 헤더
  `X-Agora-Instance-Id`(+Role/Description/Cwd)**로 전달한다. RC가 세션을 없애도
  이 헤더는 매 요청 가므로 클라이언트 측은 무상태에 안정적이다. **유일한 결합점은
  서버측 `auto_register.py`가 등록 트리거로 `mcp-session-id` AND `X-Agora-Instance-Id`
  둘 다 요구하는 것**(`auto_register.py:34`). RC 클라이언트(미래의 Claude Code)가
  session-id를 안 보내면 등록이 안 된다. stateful 유지가 의도여도, auto-register를
  "`X-Agora-Instance-Id` 우선, session-id 보조"로 견고화하면 RC 클라이언트 호환 +
  stateful 의도를 둘 다 만족. (지금은 라이브러리·CC 클라이언트가 RC로 올라간 뒤
  대응; 추적만.) `type:http`/`type:stdio`(agora-channel)는 RC에서 계속 유효.
- **SSE 폐지→Multi-RTP** — MCP transport의 SSE 얘기. 대시보드 자체 SSE
  (`dashboard_events.py`, 일반 웹 UI)와는 무관 — 영향 없음.
- **Roots/Sampling/Logging deprecated (SEP-2577)** — 미사용. 영향 없음.

## 기술부채 — 2026-05-31 아키텍처 분석에서 식별

서브시스템 전수 분석에서 나온 미해결 항목. (에러 코드 직렬화 #4는 해결됨 —
`server.py` `_error_json` + `bot.py` code 기반 분류. conversation 캐시 evict는
`sweeper.message_gc_sweep`가 이미 호출 중.)

- **재시작 복구의 fragile trick** — `persistence.restore_from_persistence()`가
  closed 대화 메시지를 JOIN으로 제외하는 'Inst4 함정5' 주석의 취약한 쿼리에
  의존하고, 명시 호출 안 하면 in-memory 상태가 빈다(`dispatcher.py` '우려3').
  런타임 등록 schema는 재시작 시 복원되지 않아 orphan 가능. 복구를 부팅 시 명시
  단계로 승격 + schema 영속 복원 검토.
- **불완전 전송이 조용히 진행** — target 인박스가 `max_inbox_depth`(기본 100)
  도달 시 dispatch는 거부하지만 cc·봇 fan-out 대상은 `skipped_full[]`에 기록만
  하고 진행. dispatch 결과에 per-target 전달 상태(delivered/skipped/throttled)를
  1급 반환값으로 노출하는 것을 검토. `peek()`·`dispatched_to`는 TOCTOU 권고치.
- **routing-bot ACL 우회** — `agora.bot_emit(target=...)`이 comm-matrix를
  재검사하지 않는다(고정 워크플로 신뢰 인프라 전제). 선택적 재검사 플래그 추가
  후보. (README에 강화 후보로 명시됨)
- **수동 VACUUM** — `gc_retention_days` 설정 후 SQLite VACUUM은 수동. sweeper
  일일 GC 루프에 주기적 VACUUM 통합 검토.

## 기능 후보 — observability · 편의 도구

2026-05-15 워커 brainstorming에서 나온 미구현 제안. 6명의 워커 중 5명이
observability 결핍을 독립적으로 보고했다. (원본 제안서는 git 이력에 보존.)

- **`agora.transcript(conversation_id, since_ts?)`** — 한 conversation의 메시지
  시퀀스를 시간순 envelope 배열로 반환. 현재는 SQLite 직접 조회로만 가능하다.
- **`agora.coverage(command_id)`** — `expect_result=true`로 발사된 command의 응답
  커버리지(`responded` / `pending` / `deadline_ts`)를 한 호출로 조회.
- **`agora.reply(message, ...)`** — 최근 수신한 명령을 컨텍스트로 잡아 `in_reply_to`
  · `conversation_id` · `target` · `payload.from`을 자동으로 채우는 답신 헬퍼.
- **`agora.cancel(command_id)`** — 발신자가 아직 consume되지 않은 in-flight 명령을
  회수. 이미 consume됐으면 no-op + 사유 반환.

## 기능 후보 — 인터랙티브 대시보드 후속

2026-05-21 `interactive-dashboard` 브랜치(spec/plan: `docs/superpowers/specs/2026-05-21-interactive-dashboard-design.md`)에서 비목표로 미룬 항목들. MVP는 운영자 dispatch + 드릴다운 + SSE + 헬스 + trust/token 인증까지 포함했고, 아래는 그 위에 쌓는 후속이다.

- **워크플로 파이프라인 시각화** — superpowers persona 체인(planner→router→implementer→tester→reviewer→improver)을 Sankey/파이프라인 뷰로 시각화. in-flight 메시지를 위치 표시. Cytoscape.js 도입 필요.
- **운영자 액션 (state-changing)** — 멈춘 대화 close, dead 워커 unregister, comm-matrix 토글·편집·시각 편집. 이미 존재하는 `admin_routes.py`의 `AGORA_ADMIN_TOKEN` 게이트를 dashboard UI에서 사용.
- **에러/이벤트 로그 패널** — 최근 dispatcher·sweeper 에러, 스키마 검증 실패, dead-letter 항목 등 운영 이벤트 surface. 지금은 서버 콘솔에만.
- **스키마 카탈로그 explorer** — `/dashboard/schemas`의 JSON Schema를 시각적으로 탐색(샘플 payload 생성, 사용 통계). 현재는 dispatch 모달의 dropdown으로만.
- **파일 스토어 뷰** — `file_store.py`의 공유 파일 목록·정책 상태·다운로드 링크 surface.
- **시계열 차트** — 워커별 인박스 depth, dispatch rate(분당), 에러율 sparkline. SVG/Canvas 인라인.
- **추가 인증 모드** — `basic`(htpasswd), `oidc` — `dashboard_auth.py`에 모드 분기 추가만 하면 엔드포인트 코드 변경 0.
- **운영자별 inbox 격리 옵션** — 현재는 read-all 정책(다른 운영자 inbox 조회 가능). 비공개 정책 옵션을 환경변수 또는 설정으로 토글.
- **검색 엔진** — FTS5 기반 메시지·대화 full-text 검색. dashboard에 검색바 + 결과 뷰.

## 워크플로 이슈

- **리뷰어 트리거 신뢰성** — superpowers 워크플로에서 implementer(또는 model·view·controller)
  → reviewer로의 hand-off가 잘 트리거되지 않는 경우가 관찰됨. 페르소나 SKILL.md의
  "All tasks green → dispatch to reviewer" 규칙이 있지만 워커가 자율적으로 따르지
  않는 빈도가 있음. 원인 후보:
  (a) implementer가 "tests pass" 시점을 놓치고 다음 task로 넘어감,
  (b) reviewer 워커가 같은 팀에 spawn 안 됨,
  (c) reviewer 인스턴스 이름이 SKILL.md의 `agora.find` 키와 일치하지 않음.
  진단·완화: 페르소나 SKILL.md의 hand-off 강제력 보강(예: TodoWrite로 reviewer
  hand-off를 명시 step으로), 또는 자동 라우터(observer 봇)가 task 완료 시그널을
  감지해 reviewer로 자동 dispatch.
  - **통신 매트릭스로 구조적 강제 (유력)** — comm-matrix를 implementer의 허용
    downstream을 `tester`·`reviewer`로만 좁히고 `improver`로의 직접 dispatch를
    `0`(금지)으로 두면, implementer가 리뷰를 건너뛰고 improver로 보내려는 시도가
    `comm_denied`로 거부된다. 즉 "다음 단계는 반드시 reviewer"가 워커 자율 준수가
    아니라 ACL로 강제된다. `improver` 행은 `reviewer`에서만 `>0`이 되도록 구성하면
    reviewer→improver 게이트가 토폴로지에 박힌다. team spawn 시 함께 적용할
    comm-matrix CSV 프리셋을 제공하면 운영자 수작업도 줄어든다.

## 미수정 버그

- **register_bot 재등록 검증 실패 시 ref 오류** — `server.py`의 `agora_register_bot`은
  봇 재등록 시작 시점에 옛 스키마 ref를 먼저 해제한다. 그 후 검증이 실패하면
  (`unknown_msgtype` 등) 봇의 옛 등록은 `BotRegistry`에 그대로 살아 있는데 스키마
  ref만 날아가, 그 스키마가 잘못 해제될 수 있다. 정상 재등록·최초 등록엔 영향 없음 —
  재등록이 *검증 실패*하는 드문 경우만. register_bot의 스키마 ref 변경을 검증 통과
  후로 미루는 트랜잭션 순서 정리가 필요하다.
