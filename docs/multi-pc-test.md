# 여러 PC 접속 시나리오 테스트

여러 머신의 Claude Code 워커가 **한 대의 중앙 AgentAgora broker**에 붙어 서로
task를 주고받는 시나리오를 검증한다. 토폴로지는 *분산 broker*가 아니라 **중앙
broker 1대 + 분산 워커 N대**다 — broker만 네트워크에 노출하면 되고, 각 PC의 워커는
HTTP 클라이언트다.

```
   PC-1 (broker + 워커 A)          PC-2 (워커 B)         PC-3 (워커 C)
   ┌─────────────────────┐        ┌──────────┐         ┌──────────┐
   │ agent-agora :8420    │◀──────│ Claude   │         │ Claude   │
   │ Claude Code (A) ─────┤        │ Code (B) │         │ Code (C) │
   └─────────▲───────────┘   LAN   └────▲─────┘   LAN   └────▲─────┘
             └───────────────────────────┴──────────────────┘
                       모두 https://<broker-LAN-IP>:8420/mcp
```

## ⚠️ 현재 제약 — cross-PC는 아직 정식 지원 전

서버는 기본적으로 **`127.0.0.1`에만 바인딩**한다(로컬 전용). `--bind-host 0.0.0.0`
(또는 환경변수 `AGORA_BIND_HOST`)으로 바인딩을 넓혀 다른 PC에서 접속하게 할 수
있지만, **인증·TLS SAN은 여전히 없다** — `/mcp`·`/channel/wait`·`/files`는 무인증이다.
즉 cross-PC는 *테스트용 우회*로만 가능하고, 정식 secure 원격 배포
(`--remote`/`--host`/Bearer 인증/TLS SAN)는 설계만 끝났고 미구현이다 —
[`docs/superpowers/specs/2026-05-18-local-remote-deployment-design.md`](superpowers/specs/2026-05-18-local-remote-deployment-design.md).

그래서 이 문서는 세 갈래로 나눈다.

- **시나리오 A — 단일 PC 멀티 워커.** 지금 코드 그대로 가능. "여러 에이전트가 한
  broker로 통신"의 본질은 여기서 다 검증된다.
- **시나리오 B — 진짜 cross-PC (테스트용 임시 우회).** broker 바인딩을 한 줄
  넓혀 트러스트된 LAN에서 굴린다. 인증이 없으므로 **신뢰된 사설망 한정**.
- **시나리오 C — 정식 remote.** 위 spec이 구현된 뒤의 경로. 지금은 포인터만.

---

## 시나리오 A — 단일 PC 멀티 워커 (지금 가능)

한 PC에서 broker 1개 + Claude Code 인스턴스 여러 개를 띄운다. 절차는 인스턴스 간
end-to-end 스모크 테스트와 동일하다 — [`docs/manual-smoke-test.md`](manual-smoke-test.md)를
그대로 따르되 인스턴스를 2개 이상으로 늘린다.

요지:

1. broker 기동: `agent-agora --dir . --port 8420 --no-tls`
2. 각 Claude Code 인스턴스의 MCP 설정을 `http://127.0.0.1:8420/mcp`로.
3. 각자 `agora.register`(서로 다른 `instance_id`) → `agora.flush` 루프.
4. `agora.dispatch`/`agora.broadcast`로 메시지를 주고받고 `agora.instances`로 토폴로지 확인.

세 대 이상이면 broadcast 팬아웃·comm-matrix ACL·conversation 종결을 함께 검증할 수
있다. 플러그인으로 워커를 자동 스캐폴딩하려면 `cc-agora-ops`의 `agora-spawn`을 쓴다.

---

## 시나리오 B — cross-PC (테스트용 임시 우회)

> **보안 경고.** 아래 우회는 broker를 LAN에 **인증 없이** 노출한다(`/admin`·
> `/dashboard`만 토큰 보호, `/mcp`·`/channel/wait`·`/files`는 무인증). 운영자가
> 모든 머신을 통제하는 **신뢰된 사설망(LAN/VPN)에서만** 쓴다. 공용 네트워크·
> 인터넷 노출 금지.

### B-0. 사전 준비

- 같은 LAN(또는 VPN)에 있는 PC 2대 이상.
- broker PC의 LAN IP 확인: `ipconfig`(Windows) → `IPv4 주소`. 예: `192.168.0.10`.
- 모든 PC에 저장소 클론 + `pip install -e .` (워커는 `agora-channel` stdio
  어댑터를 쓰므로 패키지 설치 필요).

### B-1. broker 기동 (LAN 바인딩) + 방화벽 인바운드 허용

broker PC에서 `--bind-host 0.0.0.0`으로 전 인터페이스에 바인딩한다:

```
agent-agora --dir . --port 8420 --no-tls --bind-host 0.0.0.0
```

환경변수로도 같다 — `set AGORA_BIND_HOST=0.0.0.0` 후 기동(플래그가 우선).
비-로컬 바인딩이면 시작 배너에 경고가 함께 출력된다:

```
AgentAgora starting on http://0.0.0.0:8420/mcp
  Bind     : 0.0.0.0 (비-로컬 바인딩 — 인증 없음, 신뢰된 사설망에서만 사용)
```

Windows 방화벽에서 8420 인바운드를 허용한다(관리자 PowerShell):

```powershell
New-NetFirewallRule -DisplayName "AgentAgora 8420" -Direction Inbound `
  -Protocol TCP -LocalPort 8420 -Action Allow
```

도달 확인 — 워커 PC에서:

```powershell
Test-NetConnection 192.168.0.10 -Port 8420   # TcpTestSucceeded : True 면 도달 OK
```

### B-2. 워커 PC의 `.mcp.json` 구성

각 워커 PC의 Claude Code MCP 설정에서 broker URL을 **broker의 LAN IP**로 둔다.
플러그인 spawn을 쓴다면 `--server-url`을 LAN IP로 넘긴다:

```
agora-spawn --id B --role worker --server-url http://192.168.0.10:8420/mcp
```

또는 `.mcp.json`을 직접:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "http://192.168.0.10:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "B",
        "X-Agora-Role": "worker",
        "X-Agora-Description": "worker on PC-2",
        "X-Agora-Cwd": "C:/work/B"
      }
    },
    "agora-channel": {
      "type": "stdio",
      "command": "agora-channel",
      "args": ["--instance-id", "B", "--broker", "http://192.168.0.10:8420/mcp"]
    }
  }
}
```

`agora-channel`의 `--broker`도 같은 LAN URL을 가리켜야 한다 — 채널 어댑터의 인박스
long-poll(`GET /channel/wait`)이 이 주소로 붙는다.

### B-3. 검증

1. 각 워커 PC의 Claude Code에서 `agora.register` 호출 → `{"status":"ok"}`.
2. broker PC(또는 임의 워커)에서 `agora.instances` → 모든 PC의 워커가 등재.
3. PC-1 워커 A → PC-2 워커 B로 `agora.dispatch`(task) → B의 `agora.flush`가 수신.
4. B가 답신 → A가 `agora.flush`로 회수.
5. `agora.broadcast` → 발신자 제외 전 워커 수신.
6. 대시보드: broker PC 브라우저에서 `http://192.168.0.10:8420/dashboard` → 인스턴스
   테이블에 여러 PC의 워커가 보이고 last_seen이 갱신.

### 합격 기준 (B)

- B-1: 워커 PC에서 `Test-NetConnection`이 성공(방화벽·바인딩 OK).
- B-3-1·2: 모든 PC 워커가 등록되고 `agora.instances`에 전부 나열.
- B-3-3·4: cross-PC task→reply 왕복 성공.
- B-3-5: broadcast가 다른 PC 워커에 도달.

---

## 시나리오 C — 정식 remote (spec 구현 후)

[local/remote 배포 spec](superpowers/specs/2026-05-18-local-remote-deployment-design.md)이
구현되면 임시 패치·수동 방화벽 없이 다음으로 대체된다:

```
# broker
set AGORA_AUTH_TOKEN=<공유 토큰>
agent-agora --remote --host 192.168.0.10 --port 8420

# 워커 — spawn이 https URL·Bearer 헤더·agora-cert.pem을 .mcp.json에 baking
agora-spawn --id B --role worker   # (remote 배포 자동 감지)
```

차이: `0.0.0.0` 바인딩·TLS(self-signed, SAN에 `--host`)·전 라우트 Bearer 인증이
기본으로 들어가고, 인증서가 워커 번들에 동봉된다. 진행 상황은
[`docs/backlog.md`](backlog.md)를 본다.

---

## 자주 보는 실패

- **워커 PC에서 연결 타임아웃 / 거부:** ① broker가 아직 `127.0.0.1` 바인딩
  (`--bind-host 0.0.0.0` 누락), ② 방화벽 8420 인바운드 차단, ③ URL이 broker LAN
  IP가 아님. `Test-NetConnection`으로 도달부터 끊어 확인.
- **`agora.register`는 되는데 메시지 수신이 안 됨:** `agora-channel`의 `--broker`가
  로컬호스트를 가리킨다. 채널 어댑터 URL도 LAN IP여야 한다(B-3).
- **`Mcp-Session-Id` 헤더 누락:** 클라이언트가 Streamable HTTP transport를 안 쓴다.
  AgentAgora는 Streamable HTTP 전용. (MCP 표준의 무상태 전환과 stateful 유지 입장은
  [`docs/backlog.md`](backlog.md)의 "MCP 표준 추적" 참조.)
- **여러 PC에서 같은 `instance_id`로 등록:** 나중 등록이 앞 세션을 대체한다
  (`registry.py`의 instance_id 단일성). PC마다 고유 `instance_id`를 쓴다.
- **HTTPS(`--no-tls` 생략) 시 cert 거부:** 현재 인증서 SAN은 `127.0.0.1` 기준이라
  LAN IP로 붙으면 검증 실패한다. cross-PC HTTPS는 시나리오 C(SAN에 `--host`)를
  기다리거나, 테스트는 `--no-tls` 평문으로 한다.
