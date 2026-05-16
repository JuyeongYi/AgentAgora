# cc-agora

AgentAgora MCP 서버 위에서 다중 Claude Code 인스턴스를 orchestration 하기 위한 Claude Code 플러그인. 워커 디렉토리 셋업과 슬래시 통신을 한 줄로 줄여 준다.

## 무엇을 하는가

- 워커 1명을 한 슬래시(`/cc-agora:agora-spawn`)로 셋업한다 — `CLAUDE.md` 페르소나, `.mcp.json` 2-서버(HTTP + agora-channel stdio), `run.bat` 채널 모드 기동 스크립트를 한 번에 생성.
- manifest JSON 한 개로 팀 전체(코더·리뷰어·테스터 등)를 일괄 셋업한다 (`/cc-agora:agora-spawn-team`).
- 다른 워커에 작업을 dispatch 하고 (`/cc-agora:invoke`), 모두에게 announcement를 fan-out 한다 (`/cc-agora:broadcast`).
- 자연어 task에 가장 적합한 워커를 추천한다 (`/cc-agora:agora-target`) — 직접 발사하지 않고 chaining 문자열을 제안.
- conversation을 명시적으로 종결 (`/cc-agora:agora-close`).
- `payload.py::make_payload`가 `type` enum (`task | reply | closing | ack`)을 강제해 envelope·payload 분리를 보장 (spec §5.3).

자세한 설계와 결정 사유는 `docs/superpowers/specs/2026-05-15-cc-agora-plugin-design.md`(v2.1, ground truth)에 있다.

## 설치

Claude Code 플러그인 시스템에 등록하는 정식 절차는 현 시점 추정으로 다음 두 가지 중 하나다 — 환경에 맞게 선택한다.

1. 로컬 디렉토리 등록 (개발용 가장 빠른 경로):
   - `~/.claude/plugins/cc-agora`에 본 디렉토리를 git clone 또는 symlink 한다.
   - Claude Code를 재기동하면 `/cc-agora:` 네임스페이스로 슬래시 6개가 활성화된다.
2. 플러그인 마켓플레이스 설치: 현 시점 미공개. 마켓플레이스 채널이 열리면 본 README에 갱신한다 (TODO: 정식 배포 채널 확정 후 본 항 수정).

플러그인이 활성화되면 `.claude-plugin/plugin.json`의 declared skills가 `/cc-agora:<name>` 형태로 슬래시 명령에 노출된다. 워커 본체 셋업은 본 플러그인 안의 `scripts/spawn.py` 가 담당하므로, 워커가 spawn 된 *다른* 디렉토리에서 `run.bat`을 실행할 때는 본 플러그인이 활성화돼 있을 필요가 없다 — `.mcp.json` 헤더로 서버 자동 등록만 일어난다.

요구 사항:

- Python 3.13+ (`agora-channel` 어댑터 콘솔 스크립트 포함해 `pip install -e .` 또는 `uv tool install .`로 설치).
- AgentAgora MCP 서버가 별도 프로세스로 떠 있어야 한다(기본 `http://127.0.0.1:8420/mcp`).
- Windows에서 `--launch=auto`를 쓰려면 Windows Terminal(`wt.exe`)가 PATH에 있어야 한다. 부재 시 자동으로 `--launch=manual`로 강등된다.

## 빠른 시작

전형적인 1 orchestrator + 1 coder 흐름:

```bash
# 1. 서버를 별도 터미널에서 띄운다 (저장소 루트에서)
python -m agent_agora --port 8420 --no-tls --no-timeout

# 2. orchestrator 디렉토리에서 워커 한 명 셋업
cd C:/AgoraTeam
claude
# (Claude Code 안에서)
/cc-agora:agora-spawn Coder1 coder "프런트엔드 React 컴포넌트 작성과 훅 설계 담당."

# 3. 새 터미널에서 워커 기동 (채널 모드 — run.bat이 --dangerously-load-development-channels 적용)
cd C:/AgoraTeam/Coder1
run.bat
# 워커가 채널 모드로 기동 — agora-channel 어댑터가 서버 인박스를 감시하며,
# 메시지 도착 시 claude/channel push로 워커 턴을 깨운다

# 4. orchestrator로 돌아가 작업 보내기
/cc-agora:invoke Coder1 "로그인 폼 컴포넌트 작성. props는 onSubmit 하나." --expect
```

`--expect` 플래그는 워커 페르소나에 응답 의무를 알리는 envelope 메타다. 워커는 채널 알림으로 깨어나 `agora.wait`로 인박스를 드레인하고, task 완료 후 `type=reply` payload로 응답한다. orchestrator는 다음 wait에서 그 응답을 받는다.

manifest 일괄 셋업:

```bash
# templates/team.json.example을 복사·편집 후
/cc-agora:agora-spawn-team C:/AgoraTeam/team.json --dir=C:/AgoraTeam --launch=auto
```

각 워커 디렉토리가 만들어지고, `wt.exe`가 있으면 새 Windows Terminal 탭에서 자동 기동된다.

## 슬래시 6개

| 슬래시 | 시그니처 | 동작 |
| ------ | -------- | ---- |
| `/cc-agora:agora-spawn` | `<id> <role> "<description>" [--dir --preset --force --server-url]` | 워커 1명 채널 모드 번들 셋업 (CLAUDE.md + .mcp.json + run.bat). |
| `/cc-agora:agora-spawn-team` | `<manifest.json> [--dir --launch=off/manual/auto --force --server-url]` | manifest로 다수 워커 일괄 spawn. 부분 실패 시 sequential abort. |
| `/cc-agora:agora-target` | `"<task>"` | `agora.find` + 매칭으로 1순위 워커 추천. chaining 문자열 제안만 — 직접 발사 X. |
| `/cc-agora:agora-close` | `<conversation-id> [--reason="<text>"]` | conversation을 명시 종결. 다른 참여자에 `type=closing` payload 자동 dispatch. |
| `/cc-agora:invoke` | `<id> "<message>" [--reply-to --conv --expect --cc --closing --priority --deadline]` | 한 워커에 task dispatch. payload 자동 채움 + envelope 분리. |
| `/cc-agora:broadcast` | `"<message>" [--closing --priority --conv --expect]` | 모든 등록 워커에 fan-out. announcement·세션 종료 신호. |

각 슬래시의 상세 동작 — 인자 의미, 에러 처리, 예시 — 는 `skills/<name>/SKILL.md`에 있다. 슬래시 본문은 한국어 평서체, frontmatter `description`은 영어.

## 자주 묻는 질문

### inbox_full 에러가 떴다

수신자가 `agora.wait`를 못 따라가서 받은편지함이 가득 찼다는 신호다. 다음 중 하나:

- 수신자 채널 모드 워커가 채널 알림을 받지 못하고 있다 → 수신자 터미널에서 `run.bat`이 제대로 기동됐는지 확인.
- 수신자 워커가 멈춰 있을 수 있다 → 수신자 터미널을 확인하고 필요하면 재기동.
- `agora.wait`를 수동으로 호출해 인박스를 직접 드레인할 수 있다.

상세 메시지는 §5.6 표준 한국어를 따른다 (`/cc-agora:invoke`·`/cc-agora:agora-close` SKILL.md 참조).

### `--launch=auto`가 안 된다

Windows Terminal `wt.exe`가 PATH에 없으면 자동으로 `--launch=manual`로 강등되고 stderr에 안내가 출력된다. macOS·Linux는 `--launch=manual`만 사용하거나, 직접 새 터미널에서 `cd <id> && claude --dangerously-load-development-channels server:agora-channel`를 실행한다.

### "role X는 roles.json에 정의되지 않음" 경고가 떴다

`config/roles.json`에 등록되지 않은 role을 쓰면 §4.1 미정의 처리가 발동한다 — `CLAUDE.md`와 `.mcp.json`, `run.bat`은 생성되지만 preset은 `general`이 fallback으로 사용된다. 해결:

- `config/roles.json`에 항목 추가: `{"<role>": {"preset":"general"}}`.
- 또는 spawn 결과 디렉토리에서 `CLAUDE.md`를 수동으로 편집해 페르소나를 조정.

### 워커 디렉토리는 어디에 만들어지나

spec §4.2 step 2의 4단계 cascade를 따른다:

1. `--dir=<path>` 명시 → 그 경로.
2. 환경 변수 `AGORA_HOME` 설정 → 그 경로.
3. 현재 cwd에 `.mcp.json`이 있으면 (즉 워커 디렉토리에서 호출) → 부모 디렉토리.
4. 그 외 → cwd 자체 (stderr에 경고).

오케스트레이터에서 호출할 때는 1번 (`--dir`) 또는 2번 (`AGORA_HOME` 환경 변수)이 권장된다.

## 디렉토리 구조

```
plugin/cc-agora/
  .claude-plugin/
    plugin.json              # 플러그인 manifest
  config/
    roles.json               # role → {preset} 단일 진실 (§4.1)
  scripts/
    role_policy.py           # preset_for / ...
    payload.py               # make_payload (type enum 강제)
    spawn.py                 # /agora-spawn 본체 (do_spawn 공개)
    spawn_team.py            # /agora-spawn-team 본체 (manifest 검증 + sequential abort)
  templates/
    mcp.json.template        # 2-서버 템플릿 (agentagora HTTP + agora-channel stdio)
    team.json.example
    presets/
      orchestrator.md
      coder.md
      reviewer.md
      tester.md
      writer.md
      planner.md
      general.md
  skills/
    agora-spawn/SKILL.md
    agora-spawn-team/SKILL.md
    agora-target/SKILL.md
    agora-close/SKILL.md
    invoke/SKILL.md
    broadcast/SKILL.md
  README.md                  # 본 문서
  SMOKE.md                   # manual e2e 시나리오
```

## 라이센스 / 저자

AgentAgora 모노레포 정책을 따른다 (TODO: 라이센스 파일 추가 시 본 항 갱신).
