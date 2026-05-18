# 채널 모드 워커 배선 가이드

AgentAgora 워커(Claude Code 인스턴스)가 채널 모드로 메시지를 받는 방식과 기동 방법을 설명한다.

---

## 개요

채널 모드에서는 `agora-channel` 어댑터(stdio)가 서버 인박스를 감시해, 메시지 도착 시 `claude/channel` 알림으로 워커 턴을 깨운다. 폴링 블록 없이 진짜 idle 상태로 기다리다 push 알림에 의해 깨어나는 방식이다.

| 방식 | 메커니즘 | 기동 인프라 |
|------|----------|------------|
| **채널 모드** (플러그인 기본) | `agora-channel` 어댑터(stdio)가 서버 인박스를 감시해 메시지 도착 시 `claude/channel` 알림을 push한다. 알림이 에이전트 턴을 깨운다. | `.mcp.json`의 `agora-channel` stdio 항목 + `run.bat` |
| **폴링 수신** (봇·수동 클라이언트용) | `agora.flush` 도구를 직접 호출해 큐를 드레인한다. 서버 측 기능이므로 모든 클라이언트에서 사용 가능. | 없음 (도구 호출만) |

채널 모드 플러그인 워커도 깨어난 뒤 인박스 드레인에는 `agora.flush`를 사용한다 — 채널 알림은 "깨우기"만 담당한다. `agora.flush`는 현재 큐에 쌓인 메시지를 즉시 반환하는 논블로킹 호출이다.

---

## 권장 경로: `/cc-agora-ops:agora-spawn`

cc-agora-ops 플러그인의 `/cc-agora-ops:agora-spawn` 슬래시 명령이 채널 모드 워커 번들을 자동으로 생성한다. 직접 `.mcp.json`을 편집하지 않아도 된다.

```
# orchestrator Claude Code 세션 안에서
/cc-agora-ops:agora-spawn Coder1 coder "React 컴포넌트 담당."
```

생성되는 파일 3개:

| 파일 | 내용 |
|------|------|
| `CLAUDE.md` | role preset 기반 페르소나 |
| `.mcp.json` | 2-서버 설정 (agentagora HTTP + agora-channel stdio) |
| `run.bat` | 채널 모드 기동 스크립트 (`--dangerously-load-development-channels`) |

워커 기동:

```bash
cd C:/AgoraTeam/Coder1
run.bat
```

`run.bat` 내용은 다음과 동일하다:

```bat
claude --dangerously-load-development-channels server:agora-channel %*
```

`server:agora-channel`은 `.mcp.json`의 `agora-channel` MCP 서버 항목을 채널로 로드하라는 지시다.

---

## 사전 조건

- **`claude/channel` research preview 게이팅** — `claude/channel`은 현재 research
  preview다. 조직 정책 `channelsEnabled`가 `true`여야 한다.
  - **개인 Pro/Max 계정**과 **Console API 사용자**는 기본값이 `true`다.
  - Bedrock / Vertex / Foundry 환경은 지원하지 않는다 — Anthropic 직접 인증 전용.
- **Claude Code v2.1.80+** — `claude/channel` capability를 지원하는 버전.
- **`agora-channel` 콘솔 스크립트 설치** — `pip install -e .` 또는 `uv tool install .`로
  `AgentAgora`를 설치하면 `agora-channel` 콘솔 스크립트가 PATH에 추가된다.
  ```bash
  pip install -e /path/to/AgentAgora
  ```

---

## 플러그인 없이 쓰는 경우 (참고)

플러그인을 사용하지 않고 수동으로 채널 모드 워커를 구성할 때는 다음을 직접 작성한다.

### `.mcp.json` 구성

채널 모드 워커는 MCP 서버를 **두 개** 등록한다.

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "http://127.0.0.1:8420/mcp",
      "headers": {
        "X-Agora-Instance-Id": "InstA",
        "X-Agora-Role": "worker",
        "X-Agora-Description": "채널 모드 워커 A"
      }
    },
    "agora-channel": {
      "type": "stdio",
      "command": "agora-channel",
      "args": [
        "--instance-id", "InstA",
        "--broker", "http://127.0.0.1:8420/mcp"
      ]
    }
  }
}
```

**`agentagora` (HTTP)** — 서버 연결. 워커가 `agora.flush` 드레인, `agora.dispatch`
답신 등 모든 `agora.*` 도구를 이 서버로 호출한다. `X-Agora-*` 헤더가 자동 등록을
처리한다.

**`agora-channel` (stdio)** — 채널 어댑터. Claude Code가 자식 서브프로세스로
spawn한다. 서버에 HTTP로 연결해 `--instance-id` 워커의 인박스를 감시하고, 메시지
도착 시 `claude/channel` 알림으로 워커 턴을 깨운다. 도구를 노출하지 않는다 — 오직
알림 push만 한다.

`command`는 `agora-channel` 콘솔 스크립트다. `pip install -e .` 또는 `uv tool install .`로
설치하면 PATH에 추가된다. `.mcp.json` 안의 경로·셸 문자열은 forward slash를 쓴다 —
backslash는 hook/spawn 레이어에서 escape 충돌을 일으킨다.

`--instance-id`는 `agentagora` HTTP 항목의 `X-Agora-Instance-Id`와 **반드시 같아야** 한다.
어댑터는 그 ID의 인박스를 감시한다.

### 기동

`run.bat` 없이 직접 기동할 때는 다음 명령을 실행한다:

```bash
claude --dangerously-load-development-channels server:agora-channel
```

최초 실행 시 확인 프롬프트가 한 번 뜬다. 확인하면 이후에는 묻지 않는다.

서버가 먼저 떠 있어야 한다:

```bash
agent-agora --dir . --port 8420 --no-tls --no-timeout
```

---

## 동작 흐름

1. **idle** — 워커 턴이 없다. 어댑터는 서버의 `GET /channel/wait` HTTP
   엔드포인트를 long-poll한다. (`agora.wait_notify` MCP 도구는 워커 도구
   표면에서 제거됐다 — 어댑터·봇은 HTTP 경로를 쓴다. `--add-wait`로 도구를
   다시 켤 수 있다 — 레거시·디버깅용.)
2. **메시지 도착** — 다른 워커가 `InstA`에 `agora.dispatch`하면, 서버가 어댑터를
   깨운다.
3. **`claude/channel` 알림 push** — 어댑터가 `notifications/claude/channel`을 emit한다.
   Claude Code가 이를 세션 컨텍스트에 `<channel source="agora-channel">` 태그로
   주입해 워커 턴을 시작한다.
4. **드레인** — 워커가 `agora.flush`를 호출해 인박스를 드레인한다.
5. **처리 + 답신** — 메시지를 처리하고 `agora.dispatch`로 답신한다.
6. **턴 종료 → idle 복귀** — 턴이 끝나면 워커는 다시 idle. 어댑터가 다음 push를
   기다린다.

```
[다른 워커]──agora.dispatch(InstA)──▶[서버]
                                        │
                              GET /channel/wait 해제
                                        │
                                 [어댑터 A]
                                        │
                          notifications/claude/channel
                                        │
                                   [워커 A]
                                        │
                    <channel source="agora-channel"> → 턴 시작
                                        │
                              agora.flush() → 드레인
                                        │
                              agora.dispatch(답신)
                                        │
                                    턴 종료
```

---

## 컴팩션 복구

워커의 컨텍스트 창이 차면 Claude Code가 대화를 요약한다(컴팩션). 컴팩션이 채널
루프 도중 — 인박스 드레인·메시지 처리 중 — 일어나면 진행 상태가 요약에서 사라져
워커가 멈출 수 있다. `cc-agora` 플러그인의 `SessionStart`(`matcher: "compact"`)
훅이 컴팩션 직후 "인박스를 `agora.flush`로 다시 확인하고 채널 루프를 재개하라"는
안내문을 컨텍스트에 주입해 이를 복구한다.

---

## 수동 smoke test

채널 모드 워커가 폴링 없이 push로 깨어나는지 직접 확인하는 절차다.

### 준비

터미널 A — 서버 기동:

```bash
agent-agora --dir . --port 8420 --no-tls --no-timeout
```

터미널 B — 채널 모드 워커 기동 (`worker-ch/` 디렉토리 준비, `.mcp.json`에 위
구성 적용, `run.bat` 배치):

```bash
cd worker-ch
run.bat
```

또는 직접:

```bash
claude --dangerously-load-development-channels server:agora-channel
```

확인 프롬프트를 수락하고, 워커가 기동 완료될 때까지 기다린다. 서버 로그에
`InstA` 등록이 찍혀야 한다.

터미널 C — 발신 워커 기동 (`sender/` 디렉토리):

```bash
cd sender
claude
```

### 테스트

1. **발신 워커(터미널 C)** 에서 메시지를 보낸다:

   ```
   agora.dispatch(
     target="InstA",
     payload={
       "msgtype": "worker_freeform",
       "type": "task",
       "from": "Sender",
       "ts": "<현재 ISO 타임스탬프>",
       "message": "ping — 채널 모드 smoke test"
     }
   )
   ```

2. **채널 모드 워커(터미널 B)** 를 관찰한다. Stop hook 없이도 워커 턴이
   시작되면 성공이다:
   - `<channel source="agora-channel">` 태그가 세션에 들어오고,
   - 워커가 `agora.flush`를 호출해 메시지를 드레인하고,
   - 처리 결과를 `agora.dispatch`로 답신한다.

3. **발신 워커(터미널 C)** 에서 답신이 돌아오는지 `agora.flush`로 확인한다.

이 사이클이 완성되면 채널 모드가 정상 동작하는 것이다.

---

## 한계

- **Research preview 게이팅** — `claude/channel`은 research preview다. 정식 GA
  전까지 조직 정책에 따라 비활성화될 수 있고, 인터페이스나 동작이 변경될 수 있다.
- **자작 어댑터 — 매번 플래그 필요** — `agora-channel` 어댑터는 Anthropic 공식
  allowlist에 없다. `--dangerously-load-development-channels`가 항상 필요하다.
- **알림 무확인** — `claude/channel` 알림은 전달 확인(ack)이 없다. 채널이 로드되지
  않았거나 조직 정책이 차단하면 알림이 조용히 드롭된다. 이 경우 워커가 깨어나지
  않는다.
  - 채널 모드가 동작하지 않는다면 `agora.flush`를 직접 호출해 인박스를 드레인한다.
- **Bedrock / Vertex / Foundry 미지원** — `claude/channel`은 Anthropic 직접 인증
  환경에서만 동작한다.

---

## 참고

- [`docs/usage-guide.md`](usage-guide.md) — 전체 워커·봇·매트릭스 사용 가이드
- [`plugin/cc-agora/`](../plugin/cc-agora/) — 워커 셋업 자동화 Claude Code 플러그인
- [`README.md`](../README.md) — MCP 도구 레퍼런스 · CLI 옵션
- [Claude Code Channels reference](https://code.claude.com/docs/en/channels-reference) — `claude/channel` 프로토콜 공식 문서
