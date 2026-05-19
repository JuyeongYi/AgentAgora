# agora-channel 플러그인화 — 설계 노트 (`--channels` 전환)

- 작성일: 2026-05-19
- 상태: **분석 + 제안 — 미착수.** 착수 시 spec → plan → 구현 사이클을 밟는다.
- 맥락: UeT3DRay superpowers 배포 중, 워커 채널 로딩을 `--dangerously-load-development-channels`에서 `--channels`(비-dev 플래그)로 옮길 수 있는지 검토한 결과. 이 문서는 그 결정 트레일을 보존한다.

## 1. 현재 상태

- `agora-channel`은 워커 `.mcp.json`에 직접 등록된 **stdio MCP 서버**다 — `spawn.py`가 워커마다 생성한다.
- 인자: `agora-channel --instance-id <워커별> --broker <서버 URL>`. `instance-id`가 워커마다 다르다.
- 로딩: `claude --dangerously-load-development-channels server:agora-channel`.
- 마켓플레이스 16개 플러그인(`cc-agora`·personas·`superpowers-*`) 중 MCP 서버를 번들한 것은 **0개**. `cc-agora`의 `plugin.json`도 `name`·`description`·`version`뿐.

## 2. 제약 — 왜 `--channels`가 안 되나

Claude Code 채널 문서(`/en/channels`, `/en/channels-reference`) 확인 결과:

| 채널 형식 | `--channels` | `--dangerously-load-development-channels` | `allowedChannelPlugins` | `channelsEnabled` |
|---|---|---|---|---|
| `server:` (= 현재 `agora-channel`) | ❌ | ✅ | 무관 | 적용 |
| `plugin:` | ✅ (allowlist 등재 시) | ✅ | 적용 | 적용 |

- `--channels`는 **플러그인만** 받는다(`plugin:이름@마켓`). 리서치 프리뷰 동안 Anthropic allowlist 또는 조직 `allowedChannelPlugins`로 게이팅된다.
- `server:` 형식은 bare MCP 서버 = 플러그인이 아니라 `--channels`가 거부한다. 자작/server 채널은 `--dangerously-load-development-channels server:<name>`이 유일한 경로.
- `allowedChannelPlugins`는 **플러그인** 허용목록(`{ "marketplace", "plugin" }` 항목)이라 `server:` 채널엔 적을 자리가 없다.
- `channelsEnabled`·`allowedChannelPlugins`는 둘 다 **managed settings 전용**(`C:\Program Files\ClaudeCode\managed-settings.json` 등) — user/project/local 스코프에선 무시된다.

## 3. 왜 플러그인화가 안 돼 있었나

채널 MCP 서버가 워커별 `--instance-id`를 받아야 하는데, **정적 플러그인 번들 설정은 워커별 값을 담을 수 없다.** 그래서 `spawn.py`가 워커마다 `.mcp.json`을 생성해 `--instance-id`를 박는 구조가 됐고, 채널이 플러그인이 아니라 워커별 `server:` 채널로 남았다.

## 4. 해결책 — `${ENV}` 보간

플러그인이 번들하는 MCP 서버 설정은 **환경변수 보간(`${VAR}`)**을 지원한다. 이를 쓰면 정적 플러그인 설정 하나로 워커별 값을 주입할 수 있다:

```json
{
  "command": "agora-channel",
  "args": ["--instance-id", "${AGORA_INSTANCE_ID}", "--broker", "${AGORA_BROKER}"]
}
```

- 런처(`run-agora.ps1` 등 `.ps1`/`.bat`)가 워커 패널마다 `$env:AGORA_INSTANCE_ID = <워커 id>` / `$env:AGORA_BROKER = <서버 URL>`을 세팅한다.
- 런처가 띄우는 `claude` 자식 프로세스가 그 env를 상속한다.
- Claude Code가 플러그인 MCP 설정의 `${...}`를 그 env로 보간 → 워커별 값이 채워진다.

→ "워커마다 인자가 달라 플러그인에 못 박는다"는 제약이 env 보간으로 풀린다. `channel_adapter.py`는 `--instance-id`/`--broker`를 인자로 계속 받으면 되고 — 그 값이 CLI 직접 지정이 아니라 보간으로 채워질 뿐, 어댑터 코드 변경은 불필요하다.

## 5. 변경 셋

| # | 변경 | 위치 |
|---|---|---|
| 1 | 채널 플러그인 생성 — `plugin.json` + 채널 MCP 서버 번들(`agora-channel`, 인자는 `${ENV}` 보간). `channel_adapter.py`는 `claude/channel` capability를 이미 선언하는 채널 서버다 | `plugin/agora-channel/` (레포) |
| 2 | 플러그인 등록 | `plugin/.claude-plugin/marketplace.json` (레포) |
| 3 | 기존 `agora-channel` stdio 서버 항목 제거 (플러그인이 대체) | 워커 `.mcp.json` |
| 4 | 채널 플러그인 활성화 | 워커 `.claude/settings.local.json` |
| 5 | `allowedChannelPlugins`에 `{ "marketplace": "agent-agora", "plugin": "agora-channel" }` 등재 | managed settings |
| 6 | 워커 패널: `$env:AGORA_INSTANCE_ID`·`AGORA_BROKER` 세팅 후 `--channels plugin:agora-channel@agent-agora` (dev 플래그 제거) | 런처 `.ps1` |

## 6. 미정 / 착수 시 확인

- **플러그인 배치** — 채널 MCP 서버를 기존 `cc-agora`에 넣을지, 별도 `agora-channel` 플러그인으로 뺄지. 워커가 현재 `cc-agora`를 활성화하지 않으므로 **별도 플러그인이 깔끔**해 보인다.
- **`${ENV}` 보간 범위** — 플러그인 번들 MCP 설정에서 임의 환경변수 보간이 되는지(프로세스 env 전체인지, 특정 변수만인지) 구현 시 스모크 테스트로 확인.
- **리서치 프리뷰 게이팅** — 자체 마켓플레이스 플러그인도 Anthropic 공식 allowlist에 없으므로, 조직 `allowedChannelPlugins`(managed settings)에 등재되기 전까지는 `--channels`가 아니라 여전히 `--dangerously-load-development-channels plugin:...`이 필요하다. 즉 `--channels`로 dev 플래그를 떼려면 #5(managed settings 등재)가 필수다.
- `channelsEnabled`는 어느 경로든 항상 필요 (off면 dev 플래그까지 차단).

## 7. 권장 순서

배포 테스트는 현재 `server:` + `--dangerously-load-development-channels` 구성으로 먼저 검증한다(채널 자체는 정상 동작). 위 플러그인화는 그 뒤 별도 기능 작업으로 진행한다.
