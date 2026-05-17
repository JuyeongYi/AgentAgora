# 채널 어댑터 (claude/channel push) — Design Spec

- 날짜: 2026-05-16
- 대상 코드: AgentAgora 서버 (`src/agent_agora/`) + 신규 stdio 어댑터 + 문서
- 베이스: v4 messaging + bots + comm-matrix. 트리거 — 워커가 `agora.wait` long-poll에 블록된 채 대기하는 "대기상태"가 불편하다는 사용자 요구.
- 결정 방식: 사용자와 sequential 합의 (§6 결정 트레일). `claude/channel` 프로토콜은 [Claude Code Channels reference](https://code.claude.com/docs/en/channels-reference) 직접 확인.

## 1. 배경 / 목적

현재 cc-agora 워커(Claude Code 인스턴스)는 **Stop hook + `agora.wait(timeout_ms=0)`** 패턴으로 메시지를 받는다. Stop hook이 매 턴 종료마다 워커를 다시 `agora.wait`로 진입시키고, 그 도구 콜이 블록됐다 메시지 도착 시 리턴한다. 즉 워커는 항상 블록된 도구 콜 안에 "대기상태"로 머문다.

이게 우회책인 이유 — MCP 메시지가 클라이언트에 도착해도 LLM 에이전트의 *턴*을 깨우지 못한다. 에이전트는 하니스가 턴을 줄 때만 동작한다. long-poll은 "블록된 도구 콜이 턴 안에서 리턴"하게 해 이를 우회한다.

Claude Code에는 이를 위한 네이티브 메커니즘 **`claude/channel`** 이 있다. MCP 서버가 `experimental['claude/channel']` capability를 선언하고 `notifications/claude/channel`을 emit하면, 그 이벤트가 세션 컨텍스트에 `<channel>` 태그로 들어와 **에이전트 턴을 깨운다.** 서버→클라이언트 push다.

제약 — `claude/channel`은 **stdio 전용**이다. Claude Code가 채널 서버를 *자식 서브프로세스*로 spawn해 stdio로 통신한다. AgentAgora는 워커가 *접속해 오는* 원격 HTTP 브로커라, AgentAgora 자신이 채널이 될 수 없다. 브로커는 본질적으로 공유 프로세스(여러 인스턴스를 한 점에서 라우팅)여야 하고, stdio는 1:1(클라이언트가 자기 서브프로세스를 spawn)이라 공유가 불가능하다.

본 spec은 그 틈을 메우는 **per-worker stdio 채널 어댑터**를 설계한다. 어댑터는 워커마다 하나, Claude Code가 자식으로 spawn하는 얇은 stdio MCP 서버다. 브로커에 HTTP로 닿아 인박스 도착을 감시하고, 도착 시 `claude/channel` 알림으로 워커 턴을 깨운다.

**북극성:** 최종 목표는 폴링 "대기상태"의 제거다. 본 spec은 그 발판 — 채널 경로를 폴링 경로와 *공존*시키되, 미래의 "기본 승격 + 폴링 제거"가 깔끔하도록 설계한다.

## 2. 비범위 (후속)

- **cc-agora 플러그인 자동화** — `/cc-agora:agora-spawn`이 채널 모드 워커를 spawn하도록 플러그인 템플릿·스크립트를 고치는 일. 본 spec은 어댑터 컴포넌트 + 수동 배선 가이드까지. 플러그인 통합은 별도 후속 spec.
- **기본 승격 / 폴링 경로 제거** — 본 spec은 공존(opt-in)만. 채널이 실사용 검증되고 게이팅이 풀리면 별도로 승격.
- **payload 운반 채널** — 어댑터가 메시지 본문을 `claude/channel` content에 통째 실어 워커가 `agora.wait` 드레인조차 불필요하게 하는 최적화. 미래. 본 spec은 비파괴 알림 + 워커 드레인.
- **permission relay** (`claude/channel/permission`) — 안 한다.
- **봇·스크립트 클라이언트** — `AgoraBot`·`send.py` 등 순수 MCP 클라이언트는 하니스 턴 문제가 없다(코루틴이 자연히 블록·리턴). 채널 무관, 변경 없음.

## 3. 설계

### 3.1 컴포넌트 개관

```
Inst A ──spawn(stdio)──▶ 채널 어댑터 A ──┐
Inst B ──spawn(stdio)──▶ 채널 어댑터 B ──┼──HTTP──▶ AgentAgora 브로커 (1개, 공유)
                  ▲                      │
                  └─ notifications/claude/channel ─┘  (워커 턴 깨움)
```

신규 3개:

1. **`agora.wait_notify`** — AgentAgora 서버 신규 도구. 비파괴 long-poll.
2. **`agora-channel` 어댑터** — `agent_agora` 패키지 신규 Python stdio MCP 서버.
3. **워커 배선 가이드** — 채널 모드 워커의 `.mcp.json`·`settings.local.json`·기동 구성 문서.

AgentAgora 브로커는 HTTP·공유 그대로다. 서버 변경은 `wait_notify` 도구 하나뿐.

### 3.2 `agora.wait_notify` — 서버 신규 도구

```
agora.wait_notify(instance_id: str, timeout_ms: int | None = None) -> str
```

`instance_id`의 인박스가 비지 않을 때까지 블록하고(또는 timeout), **드레인 없이** 신호를 반환한다:

```json
{"instance_id": "InstA", "pending": 3, "sources": ["PM", "Coder1"]}
```

`pending`은 큐 길이, `sources`는 큐에 쌓인 envelope의 distinct `source` 정렬 목록. 빈 채 timeout이면 `{"instance_id": ..., "pending": 0, "sources": []}`.

구현 — `Dispatcher.wait_notify(instance_id, timeout_ms)`:

- `_queues[instance_id]`가 이미 비어있지 않으면 즉시 스냅샷 반환.
- 비어있으면 기존 `wait()`와 동일하게 `_waiters[instance_id]`에 future를 등록하고 await(timeout 적용). 메시지 enqueue 시 `_wake`가 future를 깨운다 → 스냅샷 반환. timeout이면 future를 `_waiters`에서 제거하고 빈 스냅샷 반환.
- 스냅샷은 `_queues[instance_id]`를 **읽기만** 한다 — 드레인하지 않는다. 파괴적 드레인은 여전히 `instance_id` 본인 세션의 `agora.wait`가 소유한다(신원 무결성).
- **`last_seen` 갱신** — `wait_notify`는 `instance_id`의 `last_seen`을 갱신한다. 어댑터는 워커 Claude Code의 자식 프로세스라 "어댑터 살아있음 ⟹ 워커 살아있음"이 성립한다. 어댑터가 bounded `timeout_ms`로 `wait_notify`를 반복하면 채널 모드 idle 워커의 `last_seen`이 유지돼 `dead_session_sweep`에 잘못 잡히지 않는다.
- query 계열 — 호출자(어댑터)가 등록 인스턴스일 필요 없다. `agora.peek`와 일관(아무 호출자나 임의 인스턴스 큐를 관찰). AgentAgora는 로컬 신뢰 모델.
- 인자 `instance_id`가 아직 미등록이어도 거부하지 않는다 — 빈 큐 기준으로 블록한다(큐는 instance_id로 키잉되는 defaultdict). 워커 Claude Code 기동과 어댑터 spawn의 레이스(어댑터가 워커보다 먼저 떠 `wait_notify`를 거는 경우)를 무해하게 흡수한다.
- advisory — `peek`처럼 원자성 보장 없음. `wait_notify` 후 다른 세션이 드레인할 수 있다(공존 모드에서는 워커가 백그라운드 wait를 안 쥐므로 실제 경합은 거의 없다).

`_wake`는 한 타깃의 future를 전부 깨우므로, `wait_notify` future와 일반 `wait` future가 공존해도 둘 다 정상 동작한다.

### 3.3 `agora-channel` 어댑터

`agent_agora` 패키지의 신규 모듈. `python -m agent_agora.channel_adapter --instance-id <id> --broker <url>`로 실행. Claude Code가 `.mcp.json` 항목으로 자식 spawn한다.

**이중 역할** — Claude Code 쪽으로는 stdio MCP *서버*, 브로커 쪽으로는 HTTP MCP *클라이언트*.

**서버 측 (stdio, toward Claude Code):**
- `mcp` 저수준 `Server` 사용 — `create_initialization_options(experimental_capabilities={"claude/channel": {}})`로 채널 capability 선언.
- `instructions` 문자열 설정 — 워커 시스템 프롬프트에 들어가 행동 지침을 준다: "AgentAgora 인박스 알림이 `<channel source="agora-channel">`로 도착하면 `agora.wait`로 메시지를 수신해 처리하라." (`source` 속성은 채널 서버 이름 `agora-channel`로 자동 설정된다.)
- one-way 채널 — `tools` capability 없음 (워커의 송신은 별도 HTTP `agora` 연결이 담당, §3.4).
- 도착 시 `notifications/claude/channel` emit — `content` = 사람이 읽는 알림문("AgentAgora 인박스 N건 도착 (from: …). agora.wait로 수신하라."), `meta` = `{"instance_id": <id>, "pending": "<n>", "sources": "<comma-joined>"}`. meta 키는 식별자만(letters/digits/underscore), 값은 문자열.

**클라이언트 측 (HTTP, toward broker):**
- 브로커에 HTTP MCP 클라이언트로 연결(`streamable_http_client`). 등록하지 않는다(`wait_notify`는 등록 불요) — 어댑터는 `agora.instances`에 안 보이는 인프라.
- 감시 루프: `agora.wait_notify(instance_id, timeout_ms=30000)` 반복(기본 30000ms — `dead_session_timeout`보다 충분히 짧아 heartbeat 유지).

**edge-triggered 발화 (중복 방지):**
- `pending`이 `0 → >0`으로 전이할 때만 `claude/channel` 알림을 emit한다.
- emit 후 `pending`이 계속 >0이면(워커가 아직 드레인 안 함) 재발화하지 않는다. `agora.peek`로 드레인 여부만 폴링하다 `0`이 되면 다시 `wait_notify` 블로킹으로 복귀.

**복원력:** 브로커 unreachable이면 backoff 재연결, 크래시 금지. 연결이 끊긴 동안은 알림을 못 보내지만(워커가 idle 유지) — 공존 모드라 치명적이지 않다.

### 3.4 워커 배선 — 수동 가이드 (문서)

채널 모드 워커의 구성. 신규 문서 `docs/channel-mode.md`로 기술한다.

`.mcp.json` — MCP 서버 둘:
- `agora` — HTTP, 기존 그대로. 워커가 `agora.*` 도구를 호출(특히 깨어난 뒤 `agora.wait` 드레인, 답신 `agora.dispatch`). `X-Agora-*` 헤더로 자동 등록.
- `agora-channel` — stdio. `command`/`args`로 `python -m agent_agora.channel_adapter --instance-id <id> --broker <url>` spawn.

`settings.local.json` — **wait Stop hook 제거.** 채널 푸시가 재무장 루프를 대체한다. 워커는 푸시 사이에 진짜로 idle(블록된 도구 콜 없음).

흐름: `<channel source="agora-channel">` 도착 → 워커 턴 깨어남 → `agora.wait`로 드레인 → 처리 → `agora.dispatch` 답신 → 턴 종료 → 다음 푸시까지 idle.

기동: 조직 정책 `channelsEnabled`가 true여야 하고, 자작 어댑터는 allowlist에 없으므로 `claude --dangerously-load-development-channels server:agora-channel`로 띄운다.

**공존** — 한 워커는 폴링 모드(Stop hook + `agora.wait`, 어댑터 없음) **또는** 채널 모드(어댑터, Stop hook 없음) 중 하나다. 본 가이드는 채널 모드 구성을 다룬다. 폴링 모드는 기존 그대로 유효.

### 3.5 테스트

- **`Dispatcher.wait_notify` 단위 테스트** (`tests/test_v4_*`): (1) 큐가 비어있지 않으면 즉시 스냅샷 반환, (2) 빈 큐 → 블록하다 enqueue 시 깨어나 스냅샷 반환, (3) 빈 채 timeout → 빈 스냅샷, (4) **비파괴** — `wait_notify` 후 큐가 그대로(이어서 `wait`가 같은 메시지를 드레인), (5) `last_seen` 갱신, (6) `wait_notify` future와 일반 `wait` future 공존 시 둘 다 동작.
- **어댑터 루프 단위 테스트** (`tests/test_*`): 가짜 브로커 클라이언트로 — edge-triggered 발화(0→N에만 emit, N 유지 중 미발화), 드레인 감지 후 발화 복귀, `claude/channel` notification 조립(method·content·meta 형태).
- **수동 smoke test**: 실제 Claude Code가 어댑터를 spawn하고 실제 채널로 푸시받는 end-to-end는 문서화된 수동 절차로.

## 4. 영향받는 파일 (요약)

| 파일 | 변경 |
| --- | --- |
| `src/agent_agora/dispatcher.py` | `wait_notify` 메서드 추가 |
| `src/agent_agora/server.py` | `agora.wait_notify` 도구 추가 |
| `src/agent_agora/channel_adapter.py` | 신규 — stdio 채널 어댑터 |
| `tests/test_v4_*` | `wait_notify` 테스트 |
| `tests/test_*` | 어댑터 루프 테스트 |
| `docs/channel-mode.md` | 신규 — 채널 모드 워커 배선 가이드 |
| `README.md` | 채널 모드 언급 + 문서 링크 |

## 5. 알려진 리스크

- **Python `mcp` SDK 커스텀 notification 발화** — `ServerSession.send_notification`은 알려진 `ServerNotification` union에 타입 바인딩돼 있다. `notifications/claude/channel`은 비표준이라, 제네릭 `Notification[dict, str]` 모델 또는 raw `JSONRPCNotification`을 write stream에 직접 쓰는 우회가 필요할 수 있다. MCP는 결국 JSON-RPC라 raw notification 발화는 기계적으로 보장되나, **구현 첫 task에서 정확한 호출 경로를 spike**할 것.
- **research preview 게이팅** — `claude/channel`은 research preview. 자작 어댑터는 공식 allowlist에 없어 `--dangerously-load-development-channels` 상시 필요. Anthropic 인증 전용(Bedrock/Vertex/Foundry 불가).
- **notification 무확인** — `claude/channel` 알림은 ack 없음. 세션이 채널을 로드 안 했거나 정책 차단 시 조용히 드롭. 공존 모드라 — 채널이 안 먹으면 사용자가 폴링 모드로 fallback.

## 6. 결정 트레일

- **결정 1 — 범위: 공존(opt-in) + 단계적.** 채널 어댑터는 기존 폴링 경로와 나란히 가는 opt-in 경로. 추후 "기본 승격 + 폴링 제거"는 별도. 대안(즉시 대체 / 공존 / 단계적) 중 단계적 채택. 북극성은 폴링 "대기상태"의 제거이며, 본 spec은 그 발판이다.
- **결정 2 — cc-agora 플러그인 통합은 후속.** 본 spec은 어댑터 컴포넌트 + 수동 배선 가이드. 새롭고 리스크 있는 어댑터를 먼저 검증하고, 플러그인 자동화는 별도 spec — 단계적 접근과 일관.
- **결정 3 — 접근 B(깨우기 전용 어댑터 + 서버 primitive).** 대안 A는 어댑터가 워커의 *모든* agora 트래픽을 프록시(MITM)하는 단일 세션 모델 — 어댑터 장애 시 통신 전체 마비(blast radius 큼), 백그라운드 wait와 프록시 호출의 한 세션 동시 사용 등 복잡. B는 어댑터가 "깨우기" 한 가지만 하고 워커의 기존 HTTP 연결·도구는 0 변경 — 책임 분리가 깔끔하고 장애가 격리된다. "서버 수정 있어도 깔끔한 게 좋다"는 사용자 결정에 따라 B 채택.
- **결정 4 — 어댑터 언어: Python.** Channels reference 예제는 전부 JS/TS SDK 기준이나, 설치된 Python `mcp` SDK가 `create_initialization_options(experimental_capabilities=...)`로 capability 선언을 지원하고 제네릭 `Notification[dict, str]` 모델이 존재함을 확인. 프로젝트를 순수 Python으로 유지한다.
- **결정 5 — wake 메커니즘: `wait_notify` 블로킹 long-poll.** 대안은 어댑터가 `agora.peek`를 주기 폴링(서버 무변경)하는 것이나 — 지연과 상시 브로커 부하가 생긴다. `wait_notify`는 기존 `_waiters`/`_wake` 메커니즘을 재사용해 메시지 enqueue 즉시 wake하며 폴링 부하가 0이다.
