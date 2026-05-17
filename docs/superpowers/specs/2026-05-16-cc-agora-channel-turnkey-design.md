# cc-agora 채널 모드 turnkey — Design Spec

- 날짜: 2026-05-16
- 대상 코드: `plugin/cc-agora/` + `pyproject.toml` + 문서
- 베이스: [`2026-05-16-channel-adapter-design.md`](2026-05-16-channel-adapter-design.md) (채널 어댑터 — 구현 완료, master 머지됨)
- 결정 방식: 사용자와 sequential 합의 (§5 결정 트레일)

## 1. 배경 / 목적

채널 어댑터(`agora-channel`)와 서버 도구 `agora.wait_notify`는 구현·머지됐다. 그러나 채널 모드 워커를 띄우려면 아직 손작업이 크다 — 워커 디렉토리, MCP 서버 2개를 담은 `.mcp.json` 수기 작성, Stop hook 제거, 기동 플래그. 게다가 채널 모드 워커와 폴링 모드 워커의 설정이 달라 **한 배포 안에서 워커마다 구성이 제각각이면 혼란**스럽다.

해결 — cc-agora 플러그인을 채널 모드로 전환한다. `/cc-agora:agora-spawn`이 **완전한 채널 모드 워커 묶음을 한 번에 찍어내고**, 모든 참가 인스턴스가 instance ID를 제외하면 동일한 실행 구성을 갖게 한다. 폴링 모드 셋업은 제거 대상이다 — 플러그인은 채널 모드만 spawn한다.

원칙 — **아고라 참가 인스턴스는 instance ID만 다르고 `.mcp.json`·기동 명령이 전부 동일하다.** 이질성이 혼란의 근원이므로 단일 모드로 통일한다.

## 2. 비범위

- **`agora.wait` 서버 도구 제거** — 봇(`AgoraBot`)·수동 MCP 클라이언트가 쓴다. 폴링 *수신 메커니즘*은 서버에 남는다. 본 spec은 플러그인의 폴링 *셋업 plumbing*만 제거한다.
- **`--dangerously-load-development-channels` 게이팅 해소** — `claude/channel`이 research preview라 자작 어댑터는 이 플래그가 필요하다. Anthropic 공식 allowlist 등재는 우리 손 밖 — 후속.
- **기존 커밋 문서의 "브로커"→"서버" 일괄 치환** — 본 spec과 그 산출물은 "서버"로 통일하나, 과거 문서 전반의 치환은 범위 밖.
- **비-Windows 기동 헬퍼** — 본 spec은 `run.bat`(Windows)만. `.sh`는 후속.

## 3. 설계

### 3.1 `agora-channel` 콘솔 스크립트

`pyproject.toml`의 `[project.scripts]`에 `agora-channel`을 추가한다 — `agent-agora`(서버) 옆에. 그러면 `uv tool install .` / `pip install .` 시 두 명령이 모두 PATH에 오른다.

`channel_adapter.py`의 진입점 `main`은 `async def`라 콘솔 스크립트 엔트리로 직접 못 쓴다. 동기 래퍼를 둔다:

```python
def cli() -> None:
    """콘솔 스크립트 진입점 (동기) — pyproject [project.scripts]가 가리킨다."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
```

`pyproject.toml`:
```toml
[project.scripts]
agent-agora = "agent_agora.__main__:main"
agora-channel = "agent_agora.channel_adapter:cli"
```

### 3.2 워커 `.mcp.json` — MCP 서버 2개

`plugin/cc-agora/templates/mcp.json.template`을 MCP 서버 2개로 바꾼다:

```json
{
  "mcpServers": {
    "agentagora": {
      "type": "http",
      "url": "{{SERVER_URL}}",
      "headers": {
        "X-Agora-Instance-Id": "{{INSTANCE_ID}}",
        "X-Agora-Role": "{{ROLE}}",
        "X-Agora-Description": "{{DESCRIPTION}}"
      }
    },
    "agora-channel": {
      "type": "stdio",
      "command": "agora-channel",
      "args": ["--instance-id", "{{INSTANCE_ID}}", "--broker", "{{SERVER_URL}}"]
    }
  }
}
```

- `agentagora` (HTTP) — 기존. 워커가 `agora.*` 도구를 호출(특히 깨어난 뒤 `agora.wait` 드레인, 답신 `agora.dispatch`). `X-Agora-*` 헤더로 자동 등록.
- `agora-channel` (stdio) — 채널 어댑터. `command`가 §3.1의 콘솔 스크립트 `agora-channel`이라 **머신 독립** — python 절대경로가 안 들어가, 모든 워커가 동일 템플릿.
- `--broker`는 HTTP 서버 `url`과 같은 `{{SERVER_URL}}`.
- 폴링용 헤더 `{{WAIT_MODE_HEADER_LINE}}`·`X-Agora-Wait-Timeout-Ms`는 제거 — 채널 모드 워커는 폴링하지 않는다(깨어난 뒤 `agora.wait` 1회 드레인은 인박스가 비어있지 않아 즉시 리턴, timeout 무의미).

치환 변수는 `{{SERVER_URL}}`·`{{INSTANCE_ID}}`·`{{ROLE}}`·`{{DESCRIPTION}}` — instance별로 달라지는 건 `{{INSTANCE_ID}}`(+역할 메타)뿐.

### 3.3 spawn — 완전한 채널 모드 묶음

`/cc-agora:agora-spawn <id> <role> "<desc>"`이 워커 디렉토리에 생성하는 것:

- `CLAUDE.md` — 역할 페르소나. 역할별로 다르다 — "실행 옵션"이 아니라 내용이라 균일성 원칙과 무관.
- `.mcp.json` — §3.2의 2-서버 템플릿.
- **`run.bat`** — 한 줄: `claude --dangerously-load-development-channels server:agora-channel`. 워커 디렉토리에서 이걸 실행하면 채널 모드로 기동된다. `server:`의 이름은 `.mcp.json`의 stdio 서버 이름 `agora-channel`.
- `.claude/settings.local.json`·`stop-hook.py`는 **생성하지 않는다** — 채널 모드 워커는 Stop hook이 없고, 기존 `settings.local.json`은 그 hook만 담고 있었으므로 파일 자체가 불필요하다.

spawn 출력은 기동법(`<id>/`에서 `run.bat` 실행)을 안내한다. `spawn_team.py`(일괄 spawn)도 동일하게 채널 모드 묶음을 찍는다.

### 3.4 폴링 plumbing 제거

플러그인의 폴링 모드 셋업 코드를 제거한다:

- **스킬 삭제** — `plugin/cc-agora/skills/agora-wait/`, `agora-unwait/`, `agora-rewait/` (폴링 Stop hook 조작용).
- **Stop hook 산출 제거** — `spawn.py`/`spawn_team.py`에서 `stop-hook.py`·`settings.local.json`·역할별 Stop hook 생성 로직을 제거. `templates/settings.local.json.template`은 삭제(채널 워커는 이 파일이 불필요).
- **`roles.json`** — 역할→preset/persona 매핑만 유지. hook policy·wait_mode 필드 제거.
- 플러그인 테스트(`tests/test_plugin_*`)에서 폴링·Stop hook을 검증하던 부분은 채널 모드 산출에 맞게 갱신한다.

서버 측은 일절 건드리지 않는다 — `agora.wait`·`agora.wait_notify`·Dispatcher 모두 그대로.

### 3.5 문서

- `docs/channel-mode.md` — "수동 절차"에서 "`/cc-agora:agora-spawn`으로 채널 모드 워커를 찍는다"로 갱신. 수동 `.mcp.json` 작성 절은 플러그인 없이 쓰는 경우의 참고로 축소.
- `plugin/cc-agora/README.md` — 채널 모드 전환 반영, 폴링/`agora-wait` 계열 언급 제거.
- `plugin/cc-agora/skills/agora-spawn/SKILL.md` — "역할별 Stop hook" → "채널 모드 묶음"으로.
- 루트 `README.md` — 플러그인이 채널 모드 워커를 spawn한다는 점 반영.

## 4. 영향받는 파일 (요약)

| 파일 | 변경 |
| --- | --- |
| `pyproject.toml` | `agora-channel` 콘솔 스크립트 추가 |
| `src/agent_agora/channel_adapter.py` | `cli()` 동기 래퍼 추가 |
| `plugin/cc-agora/templates/mcp.json.template` | MCP 서버 2개 (HTTP + stdio 채널) |
| `plugin/cc-agora/templates/settings.local.json.template` | 삭제 (채널 워커는 settings.local.json 불필요) |
| `plugin/cc-agora/scripts/spawn.py` | 채널 모드 묶음 산출, `run.bat` 생성, Stop hook 산출 제거 |
| `plugin/cc-agora/scripts/spawn_team.py` | 동일 |
| `plugin/cc-agora/scripts/role_policy.py` · `config/roles.json` | hook policy·wait_mode 제거 |
| `plugin/cc-agora/skills/agora-wait,agora-unwait,agora-rewait/` | 삭제 |
| `plugin/cc-agora/skills/agora-spawn/SKILL.md` | 채널 모드로 갱신 |
| `tests/test_plugin_*` | 채널 모드 산출에 맞게 갱신 |
| `docs/channel-mode.md` · `plugin/cc-agora/README.md` · `README.md` | 문서 갱신 |

## 5. 결정 트레일

- **결정 1 — 플러그인 채널 전용.** 대안: 채널 기본+폴링 opt-out / 채널+폴링 보존. 사용자 — "폴링은 제거 대상". 플러그인은 채널 모드만 spawn하고 폴링 셋업 plumbing은 제거한다. 폴링 수신 메커니즘(`agora.wait`)은 봇·수동용으로 서버에 남는다.
- **결정 2 — 균일성.** 아고라 참가 인스턴스는 instance ID를 제외하면 `.mcp.json`·기동 명령이 전부 동일하다. 워커마다 설정이 다른 이질성이 혼란의 근원이므로 단일 채널 모드로 통일한다.
- **결정 3 — `.mcp.json`의 채널 `command`는 콘솔 스크립트 `agora-channel`.** python 절대경로를 박으면 머신마다 달라 균일 템플릿이 깨진다. 콘솔 스크립트로 머신 독립을 확보 — 이 때문에 `pyproject.toml` 콘솔 스크립트 등록(§3.1)이 선행 요건이다.
- **결정 4 — spawn이 완전한 묶음을 한 번에.** 워커 한 명 spawn = `.mcp.json`·`CLAUDE.md`·settings·`run.bat`까지 채널 모드로 완비. 사용자가 손으로 조립할 것이 없다.
- **결정 5 — 용어 "서버".** AgentAgora의 HTTP 프로세스는 "서버"로 부른다("브로커" 아님). 채널 어댑터는 혼동을 피해 "어댑터"로 칭한다.
