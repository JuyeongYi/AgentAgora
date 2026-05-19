# superpowers 페르소나 시스템 온보딩 가이드

## 개요

superpowers 페르소나 시스템은 기존 superpowers 단일 플러그인(14개 스킬)을 AgentAgora
다중 에이전트 아키텍처로 분리한 것이다. 각 워크플로 단계(brainstorming → 구현 → 리뷰 →
자가 개선)를 전담 페르소나-워커로 맡기고, 단계 간 핸드오프는 AgentAgora 브로커를 통한
명시적 위임(`agora.dispatch` + `delegation_request` 스키마)으로 처리한다.

워크플로는 자기 순환(ouroboros) 루프를 포함한다 — 구현 완료 후 improver가 개선 기회를
검토하고, 발견이 있으면 planner로 다시 위임해 워크플로를 재순환시킨다. 각 페르소나는
전용 컨텍스트·전용 모델로 동작하며, `superpowers-base` 공통 스킬은 모든 페르소나가 의존한다.

## 워크플로

```
planner ─▶ router ─▶ implementer
                        ⇅              TDD 핑퐁 (task마다)
                     tester
                        │ 어려운 실패
                        ▼
                     debugger ─▶ tester (재검증)   |   ─▶ planner (3+실패=구조)
            (전 task green)
   implementer ─▶ reviewer ─┬─▶ implementer            (코드 레벨 이슈)
                            ├─▶ planner                 (구조 문제)
                            └─(승인)▶ implementer ─▶ finishing-a-development-branch ─▶ improver ─▶ planner↻ / 종료
```

각 엣지는 `comm-matrix.csv`로 게이팅된다. planner→router→implementer⇄tester 순으로 진행되며,
debugger와 reviewer는 implementer~improver 구간에서 개입한다. reviewer와 debugger는 구조적
문제를 planner로 에스컬레이션할 수 있다. 대상이 불명확한 위임은 라우팅 봇이 `agora.find`로 resolve한다.

## 구성

| 컴포넌트 | 경로 | 역할 |
|---|---|---|
| `superpowers-base` | `plugin/superpowers/superpowers-base/` | 공통 스킬 3종(using-superpowers, verification-before-completion, writing-skills) — 모든 페르소나가 의존 |
| `superpowers-planner` | `plugin/superpowers/superpowers-planner/` | brainstorming + writing-plans — 아이디어를 명세·구현 플랜으로 |
| `superpowers-implementer` | `plugin/superpowers/superpowers-implementer/` | `executing-plans` + git 워크트리 + 브랜치 마무리 — 구현 코드 전담, 테스터와 핑퐁 |
| `superpowers-tester` | `plugin/superpowers/superpowers-tester/` | test-driven-development + analyzing-test-results — 모든 테스트 코드 작성·실행·결과 분석, 구현자와 TDD 핑퐁 |
| `superpowers-debugger` | `plugin/superpowers/superpowers-debugger/` | systematic-debugging — 버그 재현·원인 분석·수정 |
| `superpowers-reviewer` | `plugin/superpowers/superpowers-reviewer/` | requesting-code-review + receiving-code-review |
| `superpowers-router` | `plugin/superpowers/superpowers-router/` | subagent-driven-development + dispatching-parallel-agents + 병렬처리 체크포인트 |
| `superpowers-improver` | `plugin/superpowers/superpowers-improver/` | improvement-review — 구현 결과 검토 후 ouroboros 루프 |
| 라우팅 봇 | `plugin/superpowers/routing-bot/` | `delegation_request` 구독 → `agora.find`로 워커 resolve → `agora.bot_emit(target=...)` 전달 |

## 배포 절차 (온보딩)

### 1단계. AgentAgora 서버 설치 및 기동

서버 설치와 기동 절차는 저장소 루트의 [`FOR_AGENT.md`](../../FOR_AGENT.md)를 따른다.
서버가 먼저 떠 있어야 모든 후속 단계가 동작한다.

요약:
```
# 서버 설치 (저장소 클론 루트에서)
uv tool install .

# 배포 폴더로 이동 후 서버 기동
cd <배포폴더>
# Windows
<AgentAgora 클론 루트>\run-server.ps1
# Unix
<AgentAgora 클론 루트>/run-server.sh
```

### 2단계. 플러그인 마켓플레이스 등록

7개 superpowers 플러그인은 `plugin/.claude-plugin/marketplace.json`에 등록돼 있다.
로컬 클론에서 `plugin/` 디렉토리를 마켓플레이스로 등록하는 방법은
[`docs/plugins.md` §5-2](../../docs/plugins.md)를 참고한다.

선언형 등록 예시 (운영자 세션의 `.claude/settings.local.json`):

```json
{
  "extraKnownMarketplaces": {
    "agentagora": {
      "source": "directory",
      "path": "C:/path/to/AgentAgora/plugin"
    }
  },
  "enabledPlugins": {
    "cc-agora@agentagora": true,
    "cc-agora-ops@agentagora": true
  }
}
```

`path`는 클론한 `plugin/` 디렉토리의 절대경로다 (Windows에서도 forward slash).
`enabledPlugins`에 superpowers 플러그인은 별도 추가 불필요 — 워커 spawn 시 `agora-spawn`이
해당 워커의 `settings.local.json`에 자동으로 활성화한다.

### 3단계. 런타임 파일 설치

`.agentagora/` 디렉토리는 gitignore되어 있어 comm-matrix와 스키마가 자동으로
복사되지 않는다. 서버 첫 기동 전에 setup 스크립트로 설치한다.

**배포 폴더는 서버를 실행할 폴더다 (`--dir` 인자와 같은 경로).**

```
# Windows PowerShell — 배포 폴더를 인자로 전달
<AgentAgora 클론 루트>\plugin\superpowers\setup.ps1 -Dir <배포폴더>

# Unix — 배포 폴더를 인자로 전달
<AgentAgora 클론 루트>/plugin/superpowers/setup.sh --dir <배포폴더>
```

스크립트가 수행하는 작업:
- `routing-bot/comm-matrix.csv` → `<배포폴더>/.agentagora/comm-matrix.csv` 복사
- `routing-bot/delegation_request.schema.jsonl` → `<배포폴더>/.agentagora/schemas.jsonl` 에 append (이미 등록된 경우 스킵)
- `.agentagora/` 디렉토리 없으면 자동 생성

두 파일이 없으면 서버 기동 시 comm-matrix ACL과 `delegation_request` 스키마가
적용되지 않으며, 라우팅 봇이 정상 동작하지 않는다.

### 4단계. 라우팅 봇 기동

**서버 기동 후, 페르소나 워커보다 먼저** 실행한다.

```
# Windows
plugin\superpowers\routing-bot\run-bot.bat

# Unix
plugin/superpowers/routing-bot/run-bot.sh
```

환경변수 `AGORA_URL`로 서버 주소를 덮어쓸 수 있다 (기본값: `http://127.0.0.1:8420`).
라우팅 봇은 `delegation_request` 스키마를 구독하며, 페르소나 워커가 이 스키마로
emit하면 대상 워커를 resolve해 전달한다. 자세한 내용은
[`routing-bot/README.md`](routing-bot/README.md) 참조.

### 5단계. 페르소나 워커 spawn

운영자 세션에서 `/cc-agora-ops:agora-spawn`으로 7개 페르소나 워커를 생성한다.
`plugin/cc-agora-ops/config/roles.json`에 `sp-*` role → `superpowers-*` 플러그인 매핑이
등록돼 있어 플러그인이 자동으로 활성화된다.

```
/cc-agora-ops:agora-spawn sp-planner-1     sp-planner     "superpowers 플래너"
/cc-agora-ops:agora-spawn sp-router-1      sp-router      "superpowers 라우터"
/cc-agora-ops:agora-spawn sp-implementer-1 sp-implementer "superpowers 구현자"
/cc-agora-ops:agora-spawn sp-tester-1      sp-tester      "superpowers 테스터"
/cc-agora-ops:agora-spawn sp-debugger-1    sp-debugger    "superpowers 디버거"
/cc-agora-ops:agora-spawn sp-reviewer-1    sp-reviewer    "superpowers 리뷰어"
/cc-agora-ops:agora-spawn sp-improver-1    sp-improver    "superpowers 개선자"
```

spawn 완료 후 각 워커 디렉토리의 `run.bat`(Windows) 또는 `run.sh`(Unix)로 워커를 기동한다.

> **기동 순서**: 서버 → 라우팅 봇 → 페르소나 워커 순서를 반드시 지킨다.
> 워커는 기동 시 서버에 등록하므로 서버가 먼저 떠 있어야 한다.
> 라우팅 봇도 기동 시 서버에 연결하므로 페르소나 워커보다 먼저 떠 있어야 한다.

### 6단계. 워크플로 사용

planner 워커에 아이디어를 준다:

```
/cc-agora:invoke sp-planner-1 "새 기능 X를 기획하고 구현까지 진행해 줘"
```

planner가 brainstorming → writing-plans를 수행한 뒤, router에게 위임한다.
router는 플랜의 병렬 가능 여부를 판단해 implementer에게 라우팅한다.
구현 완료 후 improver가 개선 기회를 검토하고 유저에게 확인을 받는다.
개선이 있으면 planner로 재순환한다(ouroboros).

## 참고

- [`FOR_AGENT.md`](../../FOR_AGENT.md) — AgentAgora 서버 설치·기동
- [`docs/plugins.md` §5](../../docs/plugins.md) — 플러그인 마켓플레이스 등록 상세
- [`docs/plugins.md` §6](../../docs/plugins.md) — 워커 생성 경로 상세
- [`routing-bot/README.md`](routing-bot/README.md) — 라우팅 봇 상세
- [`docs/superpowers/specs/2026-05-18-superpowers-persona-split-design.md`](../../docs/superpowers/specs/2026-05-18-superpowers-persona-split-design.md) — 설계 spec (comm-matrix ACL 설계·ouroboros 루프·`agora.bot_emit` 확장 등)
