# AgentAgora 인스턴스 간 Smoke Test

실제 Claude Code 인스턴스 두 개와 떠 있는 AgentAgora 서버로 A→B 명령 채널을
end-to-end 검증한다. 자동 테스트(`tests/`)는 in-process 시뮬레이션이고, 이 절차는
실 클라이언트가 쓰는 HTTP transport + `Mcp-Session-Id` 헤더 경로를 굴린다.

파이썬 스크립트만으로 더 빠르게 굴려보려면 [`examples/README.md`](../examples/README.md).

## 사전 준비

- Python 3.13, 저장소 루트에서 `pip install -e .`
- AgentAgora MCP 엔드포인트에 붙을 Claude Code 인스턴스 두 개

## 절차

### 1. 서버 기동

저장소 루트(또는 임의 작업 디렉토리)에서:

```
agent-agora --dir . --port 8420 --no-tls
```

기대 출력:

```
AgentAgora starting on http://127.0.0.1:8420/mcp
  Data dir : .../.agentagora
  DB       : .../.agentagora/agora.db
  Cert     : (none -- HTTP mode, localhost only)
```

서버는 첫 기동에 `.agentagora/schemas.jsonl`(기본 스키마 6종)을 생성한다.
HTTPS로 검증하려면 `--no-tls`를 빼면 되고, 클라이언트가 self-signed cert를
신뢰해야 한다.

### 2. Claude Code 인스턴스 A 연결

A의 MCP 설정을 `http://127.0.0.1:8420/mcp`로 맞춘다. A에서 프롬프트:

> `agora.register` 도구를 `instance_id="A"`, `role="orchestrator"`로 호출해줘.

기대: `{"status": "ok", "instance_id": "A", "role": "orchestrator", ...}`.

### 3. 인스턴스 B 연결 + wait 루프

B의 MCP 설정을 같은 엔드포인트로 맞춘다. B에서 프롬프트:

> `agora.register`를 `instance_id="B"`, `role="worker"`로 호출해. 그다음 루프:
> `agora.flush`를 반복 호출하고, 명령이 오면 `payload`를 보고 처리한 뒤, 결과를
> 명령의 `source`에게 `agora.dispatch`로 되돌려. payload는 `worker_freeform`
> 스키마를 따라야 한다 — `{"msgtype":"worker_freeform","type":"reply","from":"B",
> "ts":<ISO 시각>,"message":<결과>}`. `in_reply_to`에는 받은 명령의 `id`를 넣어.
> 그리고 다시 `agora.flush`.

기대: B가 등록되고 flush 루프에 든다. `agora.flush`는 논블로킹 — 큐가 비어 있으면 빈 배열을 즉시 반환한다.

### 4. A에서 B로 명령 dispatch

A에서 프롬프트:

> 먼저 `agora.instances`로 B가 등록됐는지 확인해. 그다음 `agora.dispatch`를
> `target="B"`, `payload={"msgtype":"worker_freeform","type":"task","from":"A",
> "ts":<ISO 시각>,"message":"src/agent_agora 파일을 나열해줘"}`로 호출해.

기대:
- `agora.instances`가 A·B를 올바른 `role`로 보여준다.
- `agora.dispatch`가 `{"status":"ok","command_id":"<uuid>", ...}`를 반환한다.

> 모든 payload는 `msgtype`이 필수고 등록 스키마로 검증된다. `msgtype`이 없거나
> 스키마에 안 맞으면 dispatch가 거부된다.

### 5. B의 수신·처리 관찰

B가 `agora.flush`를 호출하면 dispatch된 명령과 함께 리턴된다. B의 LLM은
payload를 읽고, 작업(여기선 `src/agent_agora` 파일 나열)을 수행하고,
`agora.dispatch(target="A", in_reply_to=<id>, payload=<worker_freeform reply>)`로
답신한 뒤 `agora.flush`로 복귀한다.

### 6. A에서 결과 회수

A에서 프롬프트:

> `agora.flush`를 호출해. B의 결과가 도착해 있을 거야. 큐가 비어 있으면 잠시 뒤 다시 호출.

기대: A의 `agora.flush`가 `source="B"`인 명령을 반환하고, payload에 파일 목록이
담겨 있다.

### 7. broadcast (선택)

A에서:

> `agora.broadcast`를 `payload={"msgtype":"worker_freeform","type":"task",
> "from":"A","ts":<ISO 시각>,"message":"ping"}`로 호출해.

기대: B가 명령 하나를 받는다. A는 자기 broadcast를 받지 않는다.

### 8. unregister

B에서:

> `agora.unregister`를 호출해.

이어서 A에서:

> `agora.instances`를 다시 호출해.

기대: B가 목록에서 사라진다. 명시적 `agora.unregister` 없이 인스턴스가
종료되면, 서버의 dead-session sweep이 `--dead-session-timeout-ms`(기본 30분)
경과 후 정리한다 — 즉시 사라지지는 않는다.

## 합격 기준

- 2: A 등록.
- 3: B 등록 + `agora.flush` 루프 시작.
- 4: A의 `agora.instances`가 둘 다 나열, `agora.dispatch` 성공.
- 5: dispatch 후 B의 `agora.flush`가 명령 반환.
- 6: A가 결과 수신.
- 7: broadcast가 B에 도달, A에는 미도달.
- 8: `agora.unregister` 후 B가 목록에서 사라짐.

## 자주 보는 실패

- **B의 `agora.flush`가 매번 빈 commands를 반환:** B가 미등록이거나 dispatch
  `target`이 B의 `instance_id`와 불일치. `agora.instances`로 확인.
- **dispatch가 `payload_missing_msgtype` / `unknown_msgtype` / `schema_violation`로
  거부:** payload에 `msgtype`이 없거나, 미등록 스키마이거나, 스키마 위반.
  `agora.schemas_list`로 등록 스키마를 확인.
- **`Mcp-Session-Id` 헤더 누락:** 클라이언트가 Streamable HTTP transport를 안
  쓰고 있다. AgentAgora는 Streamable HTTP 전용이다.
- **self-signed cert 거부:** Claude Code가 `~/.agent-agora/certs/cert.pem`을
  신뢰하거나 검증을 건너뛰도록 설정돼야 한다 (HTTPS 모드 한정).
