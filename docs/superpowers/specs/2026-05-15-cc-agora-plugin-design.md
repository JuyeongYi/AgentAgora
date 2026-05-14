# cc-agora Claude Code Plugin — Design Spec

- 날짜: 2026-05-15
- 대상 코드: `AgentAgora/plugin/cc-agora/` (신규)
- 베이스: 없음 (신규 플러그인)
- 입력 문서: [feature-proposals-2026-05-15.md](../../feature-proposals-2026-05-15.md)
- 결정 방식: Inst1 brainstorming + 워커 6명(Inst2/4/5/6/7/8) 디테일 의견 두 라운드 → 사용자 확정

## 1. 배경

AgentAgora MCP 서버를 사용하는 Claude Code 인스턴스(orchestrator + 워커들)의 셋업·통신은 현재 손작업 비중이 크다. 본 세션에서 직접 실측된 보일러플레이트:

- **셋업**: 새 워커 추가 시 디렉토리 + `CLAUDE.md`(페르소나) + `.mcp.json`(instance_id/role/description 헤더) + `.claude/settings.local.json`(Stop hook)을 손으로 4파일 생성·정합성 유지.
- **통신**: `agora.dispatch` / `agora.broadcast` 호출은 자연어 부탁("Inst3에게 X 보내")보다 짧은 슬래시가 토큰 효율적이고 의도가 명확. target 선택은 사용자/orchestrator의 머릿속 매칭에 의존.
- **wait 제어**: Stop hook은 강제 진입만 있고 fine-grain 제어(timeout, from_sources 필터, 일시 비활성)는 직접 도구 호출.

이 빈 자리를 Claude Code 플러그인으로 채운다.

## 2. 목표 / Non-goals

### 목표

1. **`/agora-spawn` 한 줄로 새 워커 인스턴스 셋업** — 디렉토리·4파일·role-policy 적용 일괄.
2. **통신 슬래시 5개**로 일상 통신을 짧게 — `/agora-target`, `/agora-wait`, `/agora-unwait`, `/broadcast`, `/invoke`.
3. **Role 기반 hook 자동 분기** — `roles.json` single source of truth + 미정의 role은 hook 미설치 + 경고.
4. **워커 페르소나 공통 규약** — 응답 시 다른 멤버에 forward 가능, wait 진입 시 페르소나 규칙 비적용.

### Non-goals (명시 제외)

- **`/agora-target` 자동 dispatch** — 사용자 결정으로 제외. *워커 6명 만장일치(X1: `--auto` 플래그 옵트인)는 추후 재도입 시 권장 형태로 §6 결정 트레일에 보존*.
- **Observability 슬래시** (`/agora-transcript`, `/agora-coverage`) — 어제 brainstorming 결과의 P1 server-side 도구 도입에 종속. 클라이언트 슬래시는 P1 후속.
- **LLM 자동 페르소나 초안** — Inst6(Writer) 우려: 자동 초안은 일반론·형용사 나열로 빠져 워커 톤 평탄화. 프리셋 큐레이션으로 floor 확보, 추가 작성은 사용자.
- **그룹 conversation 시맨틱** (multi-target dispatch) — 어제 brainstorming 결론(YAGNI) 따름.
- **자동 등록·healthcheck** — 워커가 실제로 시작되면 `.mcp.json` 헤더로 자동 등록되는 기존 메커니즘이 충분.

## 3. 패키지 형태

### 위치

`AgentAgora/plugin/cc-agora/` — AgentAgora 모노레포에 공존. 별도 repo 안 함(사용자 확정). Python 서버와 디렉토리만 분리, 같은 git 트리.

### 표준 Claude Code 플러그인 컨벤션

```
plugin/cc-agora/
  package.json
  README.md
  commands/
    agora-spawn.md
    agora-target.md
    agora-wait.md
    agora-unwait.md
    broadcast.md
    invoke.md
  scripts/
    spawn.py            # /agora-spawn 본체
    role_policy.py      # roles.json 로더
  config/
    roles.json          # 확장 가능한 role-policy single source of truth
  templates/
    CLAUDE.md.template
    mcp.json.template
    settings.local.json.template
    presets/
      orchestrator.md
      coder.md
      reviewer.md
      tester.md
      writer.md
      planner.md
      general.md
  hooks/
    (비어 있음 — 플러그인 install 자체에는 hook 없음. spawn이 워커별 settings.local.json에 박음.)
```

플러그인 install이 *사용자 환경 전체*에 hook을 박지 않는다는 점이 중요. Inst7의 우려("spawn했더니 인스턴스가 안 멈춰요" 디버깅 경로) 차단.

## 4. 컴포넌트

### 4.1 `config/roles.json` — Role-Policy 설정 파일

확장 가능한 single source of truth. 사용자 편집 가능.

```json
{
  "orchestrator": { "hook": "none",           "preset": "orchestrator" },
  "coder":        { "hook": "stop-auto-wait", "preset": "coder" },
  "reviewer":     { "hook": "stop-auto-wait", "preset": "reviewer" },
  "tester":       { "hook": "stop-auto-wait", "preset": "tester" },
  "writer":       { "hook": "stop-auto-wait", "preset": "writer" },
  "planner":      { "hook": "stop-auto-wait", "preset": "planner" },
  "general":      { "hook": "stop-auto-wait", "preset": "general" }
}
```

**Hook 정책 enum**:

- `"stop-auto-wait"` — Stop hook으로 `agora.wait(timeout_ms=0)` 자동 호출. Inst2/.claude/settings.local.json 패턴.
- `"none"` — settings.local.json을 만들지 않거나 빈 hooks.

**미정의 role**: hook 미설치 + 경고 출력 + roles.json 편집 가이드 (Inst5 의견 보강).

### 4.2 `/agora-spawn <id> <role> <description> [--preset=<role>]`

1. `roles.json` 조회 → hook/preset 결정. 미정의 role이면 경고 + hook 비활성.
2. `<id>/` 디렉토리 생성. 기본 경로는 `slash 호출 시점의 cwd`(즉 사용자가 `/agora-spawn`을 친 인스턴스의 작업 디렉토리의 부모, 일반적으로 AgoraTest 루트와 동일). 명시 오버라이드는 `--dir=<path>` 옵션.
3. 4개 파일 생성:
   - `<id>/CLAUDE.md` — `templates/presets/<preset>.md` 복사 + description 헤더 치환.
   - `<id>/.mcp.json` — `mcp.json.template`에 instance_id/role/description 치환.
   - `<id>/.claude/settings.local.json` — hook 정책에 따라 (none이면 파일 생략).
   - `<id>/.claude/` 디렉토리 (위 파일의 부모로 생성).
4. `--preset=<role>` 명시 시 그 role의 preset 강제. 미명시 시 roles.json의 preset 사용.
5. 등록은 자동 안 함 — 사용자가 `<id>/`에서 `claude` 실행하면 .mcp.json 헤더로 자동 등록되는 기존 메커니즘.

### 4.3 `/agora-target "<task>"`

1. `agora.instances` 호출 → 등록 인스턴스 목록 + role/description.
2. LLM이 task와 매칭. **1순위 추천 워커** + 짧은 사유 표시.
3. **자동 발사 X**. 다음 슬롯에 `/invoke <recommended-instance> "<task>"`를 prefill (chaining).
4. 사용자가 prefill을 수정/확정 후 Enter로 발사.

자동 발사 재도입 시 권장 형태는 §6 결정 트레일에 보존.

### 4.4 `/agora-wait [--timeout=<ms>] [--from=<id>,...] [--conv=<id>]`

`agora.wait` 래퍼. Stop hook이 디폴트 폴링(timeout=0 unbounded)을 담당하므로 이 슬래시는 fine-grain 제어용. 인자 없으면 동일하게 unbounded.

### 4.5 `/agora-unwait`

자기 인스턴스의 Stop hook을 일시 비활성. `settings.local.json` 백업 후 hooks 섹션 제거. 재시작 또는 별도 복원 슬래시(미정의 — 후속) 시 복구. orchestrator는 no-op + 안내.

### 4.6 `/broadcast "<message>"`

`agora.broadcast` 래퍼. payload는 `{from, type:"task", message, ts}` 자동 채움.

### 4.7 `/invoke <instance> "<message>" [--reply-to=<cmd>] [--conv=<id>] [--expect]`

`agora.dispatch` 래퍼. payload 자동 채움. 옵션:

- `--reply-to=<cmd_id>` → in_reply_to 명시.
- `--conv=<id>` → conversation_id 명시 (계속 이어지는 스레드).
- `--expect` → expect_result=true.

## 5. 운영 규약 (preset 공통)

### 5.1 워커 preset 공통 단락

`templates/presets/{coder,reviewer,tester,writer,planner,general}.md` 모두에 공통 포함:

#### Forward 규약

응답은 원 발신자에게만 보낼 의무 없음. 작업 성격상 다른 멤버가 더 적합하다고 판단되면 `/invoke <other> "<task>"`로 forward 가능. 원 발신자에 **"X에게 위임함" 한 줄 acknowledgment 권장** (orphan 방지) — 절대 의무 아님, 페르소나가 자율 판단.

#### wait 진입 규약

Stop hook이 자동으로 `agora.wait(timeout_ms=0)`를 호출할 때, 페르소나 규칙은 *수신 명령*에만 적용. wait 진입 자체는 분석·확인 절차 없이 즉시 응답.

### 5.2 orchestrator preset 별도 단락

`templates/presets/orchestrator.md`:

dispatch는 본업. 사용자 자연어 요청을 받아 적합한 워커를 골라 위임. 모호하면 한 줄로 사용자에 확인 후 dispatch. Stop hook은 박지 않음 (사용자가 깨움). `/agora-target`으로 워커 추천을 받을 수 있으나 최종 발사는 사용자 confirm.

## 6. 결정 트레일

설계 결정의 동기·근거·반대 의견을 보존 (v3 spec 컨벤션).

### 결정 1: `/agora-target` 자동 dispatch 여부

- **확정**: 비활성. `/agora-target`은 추천만 + `/invoke` chaining (1c).
- **트레일**: 1라운드 워커 의견 — (1a) 3명(Inst5/6/7), (1c) 2명(Inst4/8), (1b) 1명(Inst2). 사용자가 "자동 invoke도 되면 좋겠다" 추가 의견. 2라운드 절충안 의견 — **6명 만장일치 (X1) 디폴트=수동 chaining + `--auto` 플래그 옵트인** (Inst2 갈아탐). 사용자 최종 결정 — 자동 invoke 취소.
- **재도입 트리거**: 운영 중 추천 정확도 누적 측정 + 사용자가 자동 발사 가치를 명확히 인식 시. 재도입 형태는 워커 6명 만장일치로 권장된 **"디폴트 = 수동 chaining, `--auto` 플래그로 자동 옵트인"**. 비추천 대안 — (i) 디폴트를 자동으로 두고 `--draft`/`--dry-run`으로 옵트아웃: 깜빡한 한 번이 silent fire. (ii) 별도 슬래시(`/agora-dispatch-auto` 등)로 분리: 본체와 옵션 표준화가 점차 어긋남, 같은 의도에 슬래시 두 개 표면적 증가. (iii) 인스턴스 수 기반 컨텍스트 분기: 같은 명령이 환경에 따라 다르게 동작 → mental model 깨짐 + 회귀 테스트 어려움. (iv) 추천 신뢰도 임계값 자동: 점수 calibration 부담 + 임계값 자체가 외부 노출 안 돼 디버깅 불가.

### 결정 2: 페르소나 생성 정책

- **확정**: `(2a) 빈 템플릿 default + --preset=<role>로 큐레이션 프리셋 선택`. LLM 자동 초안 비활성.
- **트레일**: Inst6(Writer)이 유일하게 답 — (2c) 프리셋. 자동 LLM 초안(2b)은 일반론·형용사 나열로 빠져 워커 톤이 서로 닮은 평탄한 산문이 됨. 다른 5명은 자기 영역 아니라 자제.

### 결정 3: Hook 정책

- **확정**: (3a) role 기반 자동 분기 + Inst5 보강 — `roles.json` 명시 상수 파일, 미정의 role = hook 미설치 + 경고.
- **트레일**: 4명 (3a), 1명 (3c, Inst7) — Inst7 우려는 "role 분류가 worker/orchestrator 둘만이라는 전제 깨질 위험". 보강 채택으로 차단 — roles.json이 single source of truth, 새 role 추가 = 파일 항목 추가. 사용자가 "확장 가능한 온라인 목록" 명시.
- **추가 안전선**: 플러그인 install 자체에는 hook 없음 — spawn 단위로만 워커 settings.local.json에 박힘 (Inst7의 "spawn 직후 안 멈춤" 디버깅 경로 차단).

### 결정 4: 패키지 위치

- **확정**: AgentAgora 모노레포 안 `plugin/cc-agora/`. Python 서버와 디렉토리만 분리, 같은 git 트리.
- **트레일**: 사용자 직접 확정 (별도 repo 안 함).

### 결정 5: Forward ack 의무

- **확정**: 페르소나 권장, 절대 의무 아님.
- **트레일**: 강제·생략 옵션 중 권장. 사용자 직접 결정.

## 7. 의문점·후속 작업

- **`/agora-unwait`의 복원 메커니즘**: 백업 파일 위치, 재가동(`/agora-rewait`?) 슬래시 추가 여부는 구현 단계에서 결정. 사용 패턴이 적으면 백업 없이 사용자 수동 복원도 가능.
- **`/agora-target`의 추천 사유 길이**: 2~3문장 권고, 단 인스턴스 수 늘어나면 더 짧게(1문장). 구현 단계 튜닝.
- **roles.json 위치 우선순위**: 플러그인 디폴트 `config/roles.json` vs 사용자 오버라이드 `~/.claude/cc-agora/roles.json` 같은 cascading 지원 여부. 현 단계 명세에서는 플러그인 디폴트만, cascading은 후속.
- **Observability 슬래시** (`/agora-transcript`, `/agora-coverage`) — server-side P1 도구 도입(어제 brainstorming 결과) 후 클라이언트 래퍼로 추가. 이 spec 외 범위.

## 8. 구현 우선순위 (writing-plans 인풋)

1. `roles.json` + `role_policy.py` 로더 (single source of truth).
2. `templates/presets/*.md` 작성 (워커 6 + orchestrator = 7개).
3. `scripts/spawn.py` (`/agora-spawn` 본체).
4. 통신 슬래시 5개 (`commands/*.md`) — `/agora-target`이 가장 복잡(LLM 매칭), 나머지는 thin wrapper.
5. README + 사용 예시.
6. 통합 테스트: 새 인스턴스 spawn → 시작 → broadcast 받기 → /invoke로 응답.
