# Backlog — 미뤄둔 작업

## 완료

- ~~**wait-tool-gating**~~ — ✅ 완료(2026-06-03 확인). 3요소 모두 master에 구현·테스트됨:
  (1) `GET /channel/wait` always-on(`channel_routes.py`, `__main__`에서 무조건 등록),
  (2) `agora-channel` 어댑터·`AgoraBot` SDK가 HTTP 경로 사용(`_broker_http.py`),
  (3) MCP `agora.wait_notify`는 기본 비등록 + `--add-wait`로만 등록(`server.py:648` 게이트,
  `__main__ --add-wait`). 테스트: `test_v4_wait_notify`(기본 미등록/플래그 등록)·
  `test_main`(플래그 기본값). 설계 spec은 `2026-05-18-wait-tool-gating-design.md`(보존).
  ※ `wait-tool-gating` 브랜치는 redundant(옛 spec 초안, 168 behind) — 삭제 가능.

## 리팩토링 로드맵 — 2026-06-03 전수 분석 (ultracode 워크플로)

2026-06-03 다중에이전트 워크플로(서브시스템 매핑 → 8개 차원 기회식별 → 적대적
검증 → 분할계획 합성 → 비판 → 확정)로 전수 분석. 펀넬: 51 원시기회 → 41 통합 →
적대적 검증 통과 34 → **15 plan화 + 15 의도적 drop + 7 검증탈락(허상)**. 각 plan은
독립 브랜치·명시경로 커밋·pytest(`.venv`) 검증 전제. 강제 선행만 `dependsOn`.

### ✅ 구현 완료 (2026-06-03)

Wave 1–7 전부 구현·머지(master 선형 히스토리) + 패키지 재구성 minimal. 전체 **618 passed**.
- **W1**: silent-swallow-logging, close-thread DispatcherClosed 가드(★버그), docstring 정정.
- **W2**: register-cwd-durability(★버그), broker-http-helper, dashboard-protected-paths, harness 일원화(FakeCtx/_tool).
- **W3**: operator-prefix, server `_session_or_error`, dashboard error-narrowing, longpoll/file bounds.
- **W4–5**: dispatcher print→logging + fan-out 골든, dispatch fan-out 추출(`_fanout_to_bots`, Stage 1).
- **W6–7**: hook-fire 공개 API(`notify_registered/unregistered`), 레지스트리 Plan E(`_BidirectionalRegistry`).
- **패키지**: `files/` + `dashboard/` 서브패키지.

### 남은 후속 (deferred)

- **dispatcher Stage 2–3**: broadcast/bot_emit fan-out 통합 + dispatch validate/commit 분리 —
  broadcast/bot_emit fan-out 골든 커버 확보 후(핵심 라우터를 테스트 범위 밖에서 리팩토링 금지).
- **harness 일원화 잔여**: 파일별로 변이 큰 dispatcher 와이어링 픽스처 통합(보류).
- **확장 모듈화**: `registry/`(+Plan E 베이스)·`storage/`(persistence·schemas·sweeper)·`http/`(routes) 서브패키지.
- **기타 defer**: envelope-row-mapping, conversation-domain-enums/object, schema-registry-lifecycle 등(필드추가/편집 시 기회적).
- **junction-sandboxed worker**(설계 논의): 워크스페이스 정션 + cwd 경계로 쓰기 샌드박스 — CC 정션-경계 해석 실측 후 spec화.

아래는 분석 당시의 plan 원본 (기록용 — 실제 구현은 git 커밋 트레일 참조).

**Wave 1 — 무위험 quick-win (병렬)**
- `observability-silent-swallow-logging` (S/low) — `persistence`·flush 경로 `except: pass`를
  logging으로 신호화(`persistence.py`·`dispatcher.py`). 동작 불변.
- `close-thread-dispatcher-closed-guard` (S/low) — ★버그: `agora.close_thread`만
  `except DispatcherClosed` 누락(종료 레이스 미처리 예외). `server.py`.
- `docstring-correctness-quickwins` (S/low) — `bot.py`·`agora.register` 거짓/스테일 docstring.

**Wave 2 — 저위험 추출 + 버그수정 + 안전망**
- `agora-register-cwd-durability-fix` (S/medium) — ★버그: 도구 cwd를 `AutoRegisterMiddleware`가
  빈 헤더로 클로버. spec 선행 + 미들웨어 가드(`server`/`registry`/`auto_register`).
- `broker-http-client-helper` (S/low) — `bot`·`channel_adapter`의 `/channel/wait` HTTP 클라
  3종 중복 → `_broker_http.py` 추출.
- `dashboard-protected-paths-single-source` (S/low) — protected-paths 3중 복제 → 모듈 상수
  (통일 전 동일성 assert).
- `test-harness-consolidation` (L/low) — 테스트 하니스 보일러플레이트 → `conftest`/`_helpers`.
  라우팅 대공사 안전망(선행).

**Wave 3 — 중간 정리**
- `operator-prefix-constant-unify` (S/low) — `'operator:'` 매직스트링 → 헬퍼.
- `server-session-caller-resolution-helper` (M/medium) — `server` 13도구 세션해석 보일러플레이트
  → `_caller_or_error`.
- `dashboard-route-error-narrowing-dedup` (M/low, **dependsOn** operator-prefix) — 광역 except
  좁히기 + 내부텍스트 누출 차단.
- `longpoll-file-bounded-wait-body` (M/medium) — 파일 업로드 바디 상한(Content-Length+chunked
  누적 가드) + long-poll timeout 클램프.

**Wave 4–5 — dispatcher 코어 분해 (순차)**
- `dispatcher-routing-stdout-to-logging` (M/medium, **dependsOn** harness) — `print`→logging +
  fan-out 골든 테스트 격리 파일로 고정.
- `dispatcher-fanout-decompose-skeleton` (L/medium, **dependsOn** stdout-logging) —
  `dispatcher.py`(1084줄) 분해: `_fanout_bots` → dispatch 분해 → 공통 골격. 동작 보존.

**Wave 6–7 — 레지스트리 일원화 (Plan E)**
- `dispatcher-hook-fire-public-api` (S/low) — register/unregister hook 공개 API 승격(Plan E 선행).
- `registry-bidirectional-base-plan-e` (L/medium-high, **dependsOn** hook-fire) — 아래
  "레지스트리 일원화" 섹션 + spec 참조.

**핵심 발견**
- **실제 버그 2건**: close_thread 종료 레이스, register cwd durability(미들웨어 클로버).
  리팩토링 아니라 정합성 버그라 분리·spec화.
- **허상 7건 기각**: "동시성 race"류 제안(registry-threading-lock·sqlite-txn-boundary·
  wait-notify-wake-race·close-thread-lock-boundary 등)이 단일스레드 asyncio 모델에선
  구조적 불가능함을 코드 대조로 확인. → 락 기반 "수정"에 노력 낭비 금지.
- **15건 의도적 drop**: 의도적 설계(stateful 유지·schema 비복원) 오인, over-abstraction
  (ROI 음수), 이미 해결 항목. 주요 defer 후보(envelope-row-mapping·conversation-domain-
  enums/object·schema-registry-lifecycle·governance-base-filepolicy)는 전부 "다음 필드추가/
  편집 시 기회적"으로 처리.

### 패키지 재구성 — 권고: minimal (2026-06-03 별도 워크플로)

설계 spec(`2026-06-03-package-layout-minimal-reorg-design`) — git 히스토리.

- 의존그래프가 이미 **무순환 DAG**(leaf 바닥) → 서브패키징은 결합을 못 줄이고 import 경로만
  relabel. 전면(full/by-domain) 재구성은 24~28모듈 + 235 테스트import(49파일) 갱신 대비
  이득=탐색성뿐이라 과함 — **권고 안 함**.
- ~~**minimal**(effort S)~~ — ✅ 완료(2026-06-03). `files/`(store·policy·routes)·`dashboard/`
  (routes·events·auth·health + `dashboard.html`·`dashboard_static/` 동거) 서브패키지화. pyproject
  package-data `'agent_agora.dashboard'=['*.html','dashboard_static/**/*']` 재경로,
  `test_packaging.py`(실제 휠 빌드)가 새 경로 에셋 포함 검증. 609 passed.
- **보류(deferred)**: HTTP 라우트 통합(`admin`/`channel`/`auto_register`는 comm_matrix/dispatcher
  의존), `bot`/`channel_adapter` 이동(진입점·이득). ※ "묶을 코드 많다"의 더 급한 절반은 파일이동이
  아니라 `dispatcher.py` 1084줄 god-module 분해(Wave 4–5) — 패키지보다 우선.

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

- **재시작 복구의 fragile trick** — (2026-06-02 Plan B 검토) `restore_from_persistence()`는
  이미 `__main__`에서 `--restore`로 명시 호출되므로 "명시 단계 승격"은 충족.
  남은 항목인 **런타임 schema 영속 복원은 보류** — `__main__.py:106-108`이 명시하듯
  비복원은 *의도적 설계*다(ref-counting 하에서 holder가 죽어 orphan ref가 되므로;
  봇·워커는 재접속 시 재등록). 복원하면 봇 미재접속 시 orphan schema가 남는
  역효과. trade-off가 있어 사용자와 재논의 후 결정. JOIN 쿼리 자체는 동작(테스트 통과).
- ~~**routing-bot ACL 우회**~~ — ✅ 완료(2026-06-02 Plan B). `--bot-emit-recheck-acl`
  opt-in 플래그(기본 off). 켜면 `bot_emit(target=워커)`도 comm-matrix 재검사
  (`dispatcher._bot_emit_recheck_acl`). 봇도 `instance_id`가 있어 매트릭스 패턴 매칭 가능.
- ~~**수동 VACUUM**~~ — ✅ 완료(2026-06-02 Plan B). `sweeper.vacuum()`을 일일 GC
  루프(`_message_gc_loop`)의 `message_gc_sweep` 뒤에 통합.

## 후속 — 레지스트리 일원화 (Plan E) — ✅ 완료 (2026-06-03)

구현·머지됨(커밋 `c3b61ad`). 공통 베이스 `_BidirectionalRegistry[InfoT]` 도입,
Instance/Bot가 상속, 봇 파생 인덱스는 `_on_store_locked`/`_on_detach_locked` 훅으로만 노출.
공개 시그니처 스냅샷 테스트(`test_registry_signature_snapshot.py`)로 API 불변 강제. 618 passed.
설계 spec(`2026-06-03-registry-unification-plan-e-design`)은 git 히스토리. 이하 원 식별 기록:

`InstanceRegistry`와 `BotRegistry`가 `register`/`resolve`/`touch_last_seen`/
`last_seen`/dead-sweep에서 유사 로직을 중복한다. 공통 베이스 레지스트리 클래스를
두고 Instance/Bot로 구체화하면 코드 중복 제거 + 통일된 식별 체계를 얻는다. 단
영향 범위가 큼(`server.py`·`dispatcher`·`sweeper`·`auto_register`가 곳곳에서 두
레지스트리를 구분해 씀) — 독립 plan으로 분리. 주의: 봇/워커의 동작 차이(봇은
expect_result 대상 아님·schema 구독·observer)와 "봇은 ACL 면제" 정책 분기는
일원화 후에도 명시적으로 남아야 한다(일원화가 ACL을 자동 처리하지 않음).

설계 트레일(2026-06-03, git 히스토리):
공통 베이스 `_BidirectionalRegistry[InfoT]` + 봇 고유 로직은 `_on_store_locked`/
`_on_detach_locked` 훅으로만 노출. risk **medium-high**(frozen+Generic 런타임 회귀) —
공개 시그니처 스냅샷 테스트 선행. **dependsOn** `dispatcher-hook-fire-public-api`(register/
unregister/dead-sweep 레이어 churn 완화). drop된 `registry-last-seen-test-seam`도 여기 흡수.

## 교착(deadlock) — 폐기, deadline 안전망으로 대체 (2026-06-02)

런타임 교착 사이클 탐지/자동해소는 **채택하지 않기로 결정**했다. expect_result
사이클 ≠ 교착이고(큐 기반 비동기), 사이클은 정상 반복 워크플로의 본질이며,
런타임 탐지기는 acyclic 매트릭스에선 dead code·사이클 매트릭스에서만 작동하는
역-ROI 기능이기 때문. 대신 **deadline 강제**(Plan A1)로 교착·죽은 워커·느린
응답을 한 메커니즘으로 처리한다. 결정 트레일: `2026-06-02-routing-core-deadline-observability-design`
§2 (git 히스토리). comm-matrix `cycles()`는 진단 정보로만 제공(거부 없음).

## 기능 후보 — 인터랙티브 대시보드 후속

2026-05-21 `interactive-dashboard`(설계 문서는 git 히스토리)에서 비목표로 미룬 항목들 — **미구현 미래 후보**(정리 대상 아님). MVP는 운영자 dispatch + 드릴다운 + SSE + 헬스 + trust/token 인증까지 포함했고, 아래는 그 위에 쌓는 후속이다.

- **워크플로 파이프라인 시각화** — superpowers persona 체인(planner→router→implementer→tester→reviewer→improver)을 Sankey/파이프라인 뷰로 시각화. in-flight 메시지를 위치 표시. Cytoscape.js 도입 필요.
- **운영자 액션 (state-changing)** — 멈춘 대화 close, dead 워커 unregister, comm-matrix 토글·편집·시각 편집. 이미 존재하는 `admin_routes.py`의 `AGORA_ADMIN_TOKEN` 게이트를 dashboard UI에서 사용.
- **에러/이벤트 로그 패널** — 최근 dispatcher·sweeper 에러, 스키마 검증 실패, dead-letter 항목 등 운영 이벤트 surface. 지금은 서버 콘솔에만.
- **스키마 카탈로그 explorer** — `/dashboard/schemas`의 JSON Schema를 시각적으로 탐색(샘플 payload 생성, 사용 통계). 현재는 dispatch 모달의 dropdown으로만.
- **파일 스토어 뷰** — `files/store.py`의 공유 파일 목록·정책 상태·다운로드 링크 surface.
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

- ~~**register_bot 재등록 검증 실패 시 ref 오류**~~ — ✅ 완료(2026-06-02 Plan B).
  `agora_register_bot`을 검증 블록과 부수효과 블록으로 분리: 검증(description·
  subscribe·inline preflight·구독 schema 존재)을 먼저 끝내고, 실패 시 옛 등록·옛
  스키마 ref를 전혀 건드리지 않고 return. 옛 ref 해제·inline 등록·acquire는 모두
  검증 통과 후에만 수행. 회귀 테스트:
  `tests/test_v4_bots.py::test_register_bot_revalidation_failure_preserves_old_schema_ref`.
