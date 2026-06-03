# AgentAgora 사용 가이드

처음 AgentAgora를 쓰는 사람을 위한 단계별 안내다. 서버를 띄우고, 에이전트를
붙이고, 메시지를 주고받고, 봇과 통신 제한까지 얹는 흐름을 순서대로 다룬다.

도구 시그니처 전체는 [`README.md`](../README.md)의 'MCP 도구 레퍼런스'를,
파이썬 스크립트만으로 굴려보는 최소 예제는 [`examples/README.md`](../examples/README.md)를
참조한다.

---

## 0. 큰 그림

AgentAgora는 **여러 에이전트 사이의 우체국**이다. 등장 인물은 셋:

- **워커(worker)** — `agora.register`로 등록하는 인스턴스. 보통 Claude Code
  인스턴스. 서로에게 일을 보내고(`dispatch`) 받는다(`flush`).
- **봇(bot)** — `agora.register_bot`으로 등록하는 스키마 구독자. 특정 종류의
  메시지를 자동으로 받아 처리하는, LLM이 아닐 수도 있는 처리기.
- **스키마(schema)** — 메시지의 모양을 정의하는 JSON Schema. 모든 메시지는
  `msgtype` 필드로 어떤 스키마를 따르는지 밝히고, 서버가 검증한다.

여기에 **통신 매트릭스**가 더해지면 "누가 누구에게 보낼 수 있는가"를 제한할 수 있다.

마지막으로 **대시보드**가 운영자(사람)의 관찰·개입 창구다 — 등록된 워커·봇·대화를
브라우저에서 한눈에 보고, 운영자가 직접 워커에게 메시지를 dispatch하거나 인박스를
드릴다운한다 (7장).

핵심 사이클은 **등록 → dispatch → flush → 답신**. 아래는 그걸 손에 익히는 과정이다.

---

## 1. 서버 띄우기

요구 사항은 Python 3.13+. 저장소 루트에서 설치한다.

```bash
pip install -e .      # 또는: uv sync
```

서버를 띄운다. 로컬 실험이면 `--no-tls`로 평문 HTTP가 편하다.

```bash
agent-agora --dir . --port 8420 --no-tls
```

```
AgentAgora starting on http://127.0.0.1:8420/mcp
  Data dir : .../.agentagora
  DB       : .../.agentagora/agora.db
  Cert     : (none -- HTTP mode, localhost only)
```

서버는 `<dir>/.agentagora/`에 상태를 둔다 — `agora.db`(SQLite), `schemas.jsonl`
(기본 스키마, 첫 기동에 자동 생성), `comm-matrix.csv`(있으면 로드).

---

## 2. 워커 붙이기

### Claude Code 인스턴스로 (권장)

각 워커 디렉토리의 `.mcp.json`에 서버를 등록한다. `X-Agora-*` 헤더를 주면
첫 요청에서 **자동 등록**된다 — 별도 `agora.register` 호출이 필요 없다.

```json
{
  "mcpServers": {
    "agora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "InstA",
        "X-Agora-Role": "orchestrator",
        "X-Agora-Description": "사용자 대면 오케스트레이터"
      }
    }
  }
}
```

> Windows에서는 `.mcp.json` 안의 경로·셸 문자열을 forward slash로 쓴다.
> backslash는 hook/spawn 레이어에서 escape 충돌을 일으킨다.

워커 디렉토리·`CLAUDE.md`·hook까지 한 번에 찍어내는 Claude Code 플러그인은
[`plugin/cc-agora/`](../plugin/cc-agora/)에 있다.

### 최초 세팅을 한 번에: `agora-init`

AI(Claude)를 거치지 않고 사람이 직접 실행하는 부트스트랩 CLI다. 팀 구성·스폰
위치·통신 매트릭스를 입력받아 워커 디렉토리들과 설정 파일을 한 번에 찍는다.

```bash
agora-init                          # 대화형 — 프롬프트로 팀/위치/매트릭스 입력
agora-init --manifest team.json     # 비대화형 — 기존 manifest로 재실행(CI)
```

대화형은 스폰 위치·서버 URL·마켓플레이스 소스(기본 GitHub
`JuyeongYi/AgentAgora-ClaudePlugins`, 또는 로컬 plugin 경로)를 먼저 묻고, 워커마다
`id`·`role`·`description`·`allow`(dispatch 가능 대상 id/정규식, 쉼표구분; 빈칸=없음,
`*`=전체)를 묻는다. 생성물(스폰 위치 아래):

- 각 워커 디렉토리 4파일 — `CLAUDE.md`·`.mcp.json`·`run.bat`·`.claude/settings.local.json`
  (마켓플레이스 `agent-agora`를 신뢰 등록 + 페르소나 플러그인 활성화)
- `team.json` — 입력 보존(재실행용)
- `.agentagora/comm-matrix.csv` — `allow` 목록에서 생성한 통신 매트릭스(행=수신자/열=발신자)
- `run-server.bat` — 서버 기동 스크립트

마켓플레이스 별칭은 `marketplace.json`의 `name`과 같은 `agent-agora`로 고정된다 —
`/plugin marketplace add JuyeongYi/AgentAgora-ClaudePlugins`로 수동 등록한 경우와
식별자가 일치해 충돌하지 않는다.

다음 단계: `run-server.bat`으로 서버를 띄우고 각 워커에서 `run.bat`을 실행하면
`.mcp.json` 헤더로 자동 등록된다. 서버가 이미 떠 있고 `AGORA_ADMIN_TOKEN`이
설정돼 있으면 매트릭스를 즉시 적용(POST)하고, 아니면 파일만 두어 서버가 시작 시 로드한다.

### 스크립트로

MCP 클라이언트 라이브러리로 직접 붙을 수도 있다. `agora.register`를 호출해
세션을 인스턴스 이름에 바인딩한다. 동작하는 예제는
[`examples/echo_bot/send.py`](../examples/echo_bot/send.py).

붙은 인스턴스는 `agora.instances`로, 봇은 `agora.bots`로, 둘 다 `agora.find`로
확인한다.

---

## 3. 메시지 주고받기

워커 A가 워커 B에게 일을 보낸다고 하자.

**A — 보내기:**

```
agora.dispatch(
  target="InstB",
  payload={
    "msgtype": "worker_freeform",
    "type": "task",
    "from": "InstA",
    "ts": "2026-05-16T03:00:00+00:00",
    "message": "src/ 아래 파일을 나열해줘"
  }
)
```

**B — 받기:** `agora.flush()`를 호출하면 현재 큐에 쌓인 명령이 `commands` 배열로
즉시 반환된다. 각 원소는 `id`·`source`·`payload`·`conversation_id` 등을 담은 envelope다.

**B — 답신:** 처리 후 발신자에게 되돌린다. `in_reply_to`에 원 명령의 `id`를
주면 같은 대화(`conversation_id`)로 묶인다.

```
agora.dispatch(
  target="InstA",
  in_reply_to="<받은 명령의 id>",
  payload={"msgtype": "worker_freeform", "type": "reply", "from": "InstB",
           "ts": "...", "message": "파일 목록: ..."}
)
```

- 전원에게 보내려면 `agora.broadcast(payload=...)` — 자기 자신은 제외된다.
- 같은 대화를 여러 라운드 이어가려면 `conversation_id`를 명시하거나 `in_reply_to`로
  상속받는다. 대화를 끝낼 땐 `closing=True` 또는 `agora.close_thread`.
- 큐 상태는 `agora.peek`로 비파괴 조회한다.

---

## 4. 스키마 — `msgtype` 규칙

**모든 메시지 payload는 JSON 객체이고 `msgtype` 필드가 필수다.** 서버는 그
`msgtype`으로 등록된 스키마를 찾아 payload를 검증한다. 빠지거나 틀리면 dispatch가
거부된다 (`payload_missing_msgtype` / `unknown_msgtype` / `schema_violation`).

기본 제공 스키마 6종:

| msgtype | kind | 용도 |
|---------|------|------|
| `worker_freeform` | conversation | 워커 간 자연어 통신 — `message`가 자유 텍스트 |
| `default` | conversation | 구조화 로그 엔트리 |
| `closing` | conversation | 대화 종결 통지 |
| `ack` | conversation | forward 통지 |
| `bot_reply` | bot-task | 봇 처리 결과 |
| `bot_error` | bot-task | 봇 처리 실패 |

워커끼리 대화할 땐 보통 `worker_freeform`이면 충분하다. 새 메시지 종류가
필요하면 `agora.register_schema(name, body, kind, purpose)`로 등록한다 — `body`에는
`msgtype` property가 반드시 있어야 하고, 한 번 등록하면 immutable이다. 등록된
스키마는 `agora.schemas` / `agora.schemas_list`로 조회한다.

스키마 `kind`는 둘 — `conversation`(워커↔워커)과 `bot-task`(봇 입출력). 봇이
구독하는 스키마는 반드시 `bot-task`여야 한다.

---

## 5. 봇 붙이기

봇은 **특정 `msgtype`을 구독해 자동으로 메시지를 받는** 처리기다. `register_bot`으로
등록하며, 워커와는 별도 네임스페이스다.

```
agora.register_bot(
  instance_id="bot_echo",
  description="echo_task를 받아 bot_reply로 회신",
  bot_mode="handler",
  subscribe_schemas=["echo_task"],
  schemas={"echo_task": {"kind": "bot-task", "purpose": "...",
                         "body": { ... msgtype property 포함 ... }}}
)
```

- `bot_mode="handler"` — `subscribe_schemas`의 메시지만 받는다.
- `bot_mode="observer"` — 스키마 무관 모든 메시지를 사본(cc)으로 받는다.
- `schemas` — 구독할 스키마를 등록과 동시에 인라인 정의 (별도 `register_schema`
  호출 생략).

봇도 `agora.flush`로 메시지를 받는다. 처리 결과는 dispatch가 아니라
**`agora.bot_emit`**으로 회신한다 — `in_reply_to`에 원 명령 `id`를 주면 원
발신자에게 돌아간다.

워커가 봇에게 보낼 땐 `target`을 **생략**하면 된다. 서버가 payload의 `msgtype`을
구독한 봇을 찾아 라우팅한다(schema-routed dispatch):

```
agora.dispatch(payload={"msgtype": "echo_task", "text": "안녕"})
# → echo_task를 구독한 봇(bot_echo)에게 자동 전달
```

봇은 보통 `agent_agora.bot.AgoraBot`을 상속해 `handle()`만 구현한다 — 자세한 SDK 사용법은 [`docs/bot-sdk.md`](bot-sdk.md).

동작하는 봇 전체 코드는 [`examples/echo_bot/echo_bot.py`](../examples/echo_bot/echo_bot.py).

---

## 6. 통신 매트릭스로 제한하기

기본적으로 워커는 누구에게나 dispatch할 수 있다. 흐름을 강제하고 싶을 때 —
예: 워커는 PM에게만 회신하고 워커끼리 직접 통신 금지 — **통신 매트릭스**를 쓴다.

매트릭스는 N×N CSV로 정의한다. 헤더 = `from` 목록, i번째 데이터 행 = i번째
인스턴스를 `to`로 했을 때 각 `from`의 허용 여부(`1`/`0`):

```
pm,coder,reviewer
0,1,1
1,0,0
1,0,0
```

위는 hub-and-spoke — `pm`은 양방향 자유, `coder`와 `reviewer`는 서로 직접
dispatch 불가.

적용하는 두 방법:

1. **startup 로드** — `<dir>/.agentagora/comm-matrix.csv`에 두면 서버 기동 때 읽는다.
2. **런타임 교체** — 운영자 전용 엔드포인트 `POST /admin/comm-matrix`(바디에 CSV)로
   재기동 없이 교체한다. 서버를 `AGORA_ADMIN_TOKEN` 환경변수와 함께 띄워야 활성화되고,
   요청엔 `Authorization: Bearer <token>` 헤더가 필요하다. 워커가 호출하던 옛
   `agora.register_comm_matrix` 도구는 제거됐다 — ACL은 운영자만 바꾼다.

매트릭스가 금지한 dispatch는 `comm_denied` 에러로 거부되고, broadcast에서는
금지 대상이 fan-out에서 빠진 채 `denied` 목록으로 보고된다. 봇으로 가는
schema-routed 메시지와 cc는 매트릭스 대상이 아니다.

ACL이 막고/통과시키는 걸 직접 보는 데모는 [`examples/comm_demo/`](../examples/comm_demo/).

---

## 7. 대시보드 — 운영자(사람)가 들여다보고 개입하는 창구

워커·봇·대화는 모두 서버 메모리·SQLite에 살아 있다. 그걸 **브라우저 한 탭으로
관찰하고 사람이 직접 dispatch까지 할 수 있는** 게 대시보드다. read-only 모니터가
아니라, 운영자가 워커에게 메시지를 보내고 답신을 받는 양방향 채널이다.

### 7.1 열기

서버가 떠 있으면 바로 접속:

```
http://127.0.0.1:8420/dashboard
```

cc-agora-ops 플러그인이 깔려 있으면 슬래시로 자동 오픈:

```
/cc-agora-ops:agora-dashboard
```

첫 접속에 로그인 모달이 뜬다. `trust` 모드(기본)면 username만 자기 신고, `token`
모드면 username + token. 인증 모드는 8장(원격 접근) 참고.

### 7.2 한눈에 보기

- **요약 카드 4개** — 인스턴스·봇·열린 대화·총 인박스.
- **인스턴스 테이블** — 등록된 워커. 인박스에 메시지 있으면 노란색 강조. 정렬·필터.
- **대화 테이블** — 최근 50개. 행 클릭 → 메시지 thread 드릴다운 모달.
- **봇 테이블** + **comm-matrix SVG 그래프** — 워커 간 dispatch 허용 흐름 시각화.

업데이트는 **SSE 푸시** — 워커가 등록되거나 메시지를 dispatch하면 화면이 즉시
바뀐다. SSE가 실패하면 자동으로 3초 폴링으로 전환된다 (우상단 indicator로 표시).

### 7.3 운영자 → 워커 직접 dispatch

우하단 "**+ 보내기**" 버튼 → dispatch 모달.

- **단일 워커** — dropdown으로 한 명 선택.
- **브로드캐스트** — 여러 워커 체크박스.
- **Schema** — 등록된 스키마 dropdown (5장의 스키마 등록 도구와 동일 카탈로그).
- **Payload** — JSONEditor가 선택한 스키마로 폼을 자동 생성. raw JSON도 가능.
- **`reply_only`** 체크박스 — "다른 워커로 forward 금지, 답신만" 의도를
  envelope에 박는다. 워커가 `agora-protocol` 스킬 규약으로 자율 존중 (서버 강제 안 함).

전송 직후 envelope이 영속화되고, 워커의 다음 `agora.flush`에서 즉시 수신된다.

### 7.4 워커 답신 받기 — 운영자 인박스 패널

워커가 dispatch로 답신하면 운영자의 인박스 패널(좌측)에 카드로 즉시 도착
(SSE 푸시). 카드 클릭 → 전체 envelope drilldown. **ack 버튼**으로 읽음 처리하면
패널에서 사라지지만 영속 저장된 본문은 그대로 — `?include_acked=true`로 다시 볼 수 있다.

### 7.5 드릴다운

- **대화 행 클릭** — 그 대화 thread 전체 메시지를 시간순 카드로.
- **인스턴스 행 클릭** — 그 워커의 현재 인박스 (envelope 본문 포함).

운영자가 워커들 사이 어떤 일이 오갔는지 SQLite를 직접 뒤지지 않고 본다.

### 7.6 다중 운영자

각 운영자는 `operator:<username>` pseudo-instance로 lazy 등록된다.

- sweeper TTL·comm-matrix ACL에서 제외 — 영구·전능.
- 자기 인박스만 본다(`GET /dashboard/operator/inbox`) — 답신은 dispatch한 본인
  에게만.
- 다른 운영자의 인박스도 드릴다운으로 볼 수 있음(read-all 투명 정책).

여러 사람이 동시에 같은 서버에 붙어 서로 다른 워커에 dispatch 가능.

### 7.7 어디까지 가는지

기본 (서버에 persistence·write_queue 미주입)이면 대시보드는 read-only다.
dispatch·broadcast·inbox 엔드포인트는 두 인프라가 모두 준비됐을 때만 활성화된다
(기본 빌드는 활성). comm-matrix 변경·인스턴스 unregister 같은 state-changing은
대시보드에서 안 한다 — admin HTTP 엔드포인트와 cc-agora-ops 슬래시로 분리돼 있다.

엔드포인트 전체 레퍼런스·페이로드 스키마·이벤트 타입은
[`docs/dashboard.md`](dashboard.md).

---

## 8. 원격 접근

기본 서버는 `127.0.0.1`에만 바인딩돼 로컬 접근만 허용한다. 다른 PC·모바일에서
대시보드를 봐야 한다면:

1. **외부 바인딩** — `agent-agora --host 0.0.0.0 --port 8420`.
2. **token 인증 활성화** — 원격 노출에서 `trust` 모드는 위험. 토큰 모드 사용:

   ```bash
   export AGORA_DASHBOARD_AUTH_MODE=token
   export AGORA_DASHBOARD_TOKENS=alice:secret_a,bob:secret_b
   ```

   토큰을 모르는 클라이언트는 401. 토큰으로 추출한 username이 `X-Agora-Operator-User`
   헤더보다 우선해 impersonation을 차단한다.
3. **TLS** — 내부 테스트면 self-signed(`certs.py` 자동), 운영이면 리버스 프록시 +
   공인 인증서.
4. **방화벽 포트** — 8420(기본)만 열고 나머지 닫는다.

자세한 체크리스트는 [`docs/dashboard.md`](dashboard.md#원격-배포-설정).

---

## 자주 막히는 곳

- **`agora.flush`가 매번 빈 배열로 돌아온다** — 등록이 안 됐거나, 보내는
  쪽 `target`이 내 `instance_id`와 다르다. `agora.instances`로 확인.
- **dispatch가 `payload_missing_msgtype`로 거부된다** — payload에 `msgtype`이
  없다. 모든 메시지는 `msgtype` 필수 (4장 참조).
- **dispatch가 `unknown_msgtype`로 거부된다** — 그 `msgtype` 스키마가 등록 전이다.
  봇 스키마라면 봇을 먼저 띄워야 한다.
- **`target` 없는 dispatch가 `no_route`로 거부된다** — 그 `msgtype`을 구독한
  핸들러 봇이 하나도 없다.
- **dispatch가 `comm_denied`로 거부된다** — 통신 매트릭스가 그 쌍을 금지한다.
- **`Mcp-Session-Id` 헤더 없음** — 클라이언트가 Streamable HTTP transport를 안
  쓰고 있다. AgentAgora는 Streamable HTTP 전용이다.

---

## 다음 단계

- [`examples/README.md`](../examples/README.md) — 봇·매트릭스 데모를 실제로 실행.
- [`README.md`](../README.md) — 전체 도구 레퍼런스·CLI 옵션.
- [`docs/dashboard.md`](dashboard.md) — 대시보드 전체 엔드포인트·SSE·인증 레퍼런스.
- [`docs/superpowers/specs/`](superpowers/specs/) — 각 기능의 설계 의도와 결정 트레일.
- [`plugin/cc-agora/`](../plugin/cc-agora/) — 워커 셋업을 자동화하는 Claude Code 플러그인.
