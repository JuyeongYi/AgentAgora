# cc-agora 컴팩션 복구 훅 설계

- 작성일: 2026-05-18
- 상태: 설계 승인 → 구현 플랜 대기
- 관련 백로그: `docs/backlog.md` "cc-agora PostCompact 훅"

## 1. 배경 / 문제

채널 모드 워커(Claude Code 인스턴스)는 `<channel source="agora-channel">` 알림으로
깨어나 `agora.flush`로 인박스를 드레인하고, 처리 후 `agora.dispatch`로 답신한 뒤
idle로 복귀한다 (`docs/channel-mode.md`, `agora-protocol` 스킬).

컨텍스트 창이 차면 Claude Code는 대화를 요약한다(컴팩션). 컴팩션이 워커의 루프
중간 — 인박스 드레인·메시지 처리 중 — 에 일어나면, 요약이 그 진행 상태를 잃는다.
컴팩션 후 워커는 요약만 보고 행동할 근거를 찾지 못해, 처리·답신하지 못한 메시지를
남긴 채 턴을 끝내고 idle로 복귀한다. 새 채널 알림은 오지 않으므로(메시지는 이미
전달·소비됨) 워커는 영구히 멈춘다.

## 2. 목표 / 비목표

**목표** — 컴팩션 직후 채널 모드 워커에게 "인박스를 다시 확인하고 루프를 재개하라"는
지시를 주입해, 컴팩션으로 인한 멈춤을 복구한다.

**비목표**

- 워커 턴 *도중* 도착한 메시지의 채널 알림 유실(`docs/channel-mode.md` "알림 무확인"
  한계)은 별개 문제 — 다루지 않는다.
- 컴팩션 요약 자체에 채널 상태를 보존시키는 PreCompact 기반 선제 대응은 범위 밖.

## 3. 메커니즘 확인 (결정 트레일)

백로그 항목명은 "PostCompact 훅(`prompt` 타입)"이었다. 공식 문서
(`https://code.claude.com/docs/en/hooks`)를 직접 확인한 결과 두 전제가 틀렸다.

- **`type: "prompt"` 훅** — 존재하지만 텍스트 주입 도구가 아니다. Haiku에 프롬프트를
  보내 yes/no 결정(`{ok, reason}`)을 받는 결정 게이트다.
- **`PostCompact` 훅** — 존재한다. "After context compaction completes"에 발화한다.
  그러나 decision control이 `None`인 **side-effect 전용 훅**이다 (`Notification`·
  `SessionEnd`·`FileChanged`와 같은 부류, 문서: "Used for side effects like logging
  or cleanup"). exit code 표는 `PostCompact | No | Shows stderr to user only`.
  `additionalContext`를 지원하지 않아 **워커 컨텍스트에 텍스트를 주입할 수 없다.**

컴팩션 후 워커 컨텍스트에 텍스트를 주입할 수 있는 훅은 `SessionStart`뿐이다.
`SessionStart`는 `source` 필드(`startup`/`resume`/`clear`/`compact`)와 `matcher`를
가지며, `matcher: "compact"`는 "Auto or manual compaction" 후 발화한다.
`additionalContext` 및 stdout→컨텍스트 주입을 공식 지원한다 (문서: "Any text your
hook script prints to stdout is added as context for Claude"). 공식 문서의
"Re-inject context after compaction" 예제가 바로 이 용도로 `SessionStart` +
`compact` 매처를 제시한다.

→ **채택: `SessionStart` 훅, `matcher: "compact"`, `type: "command"`.**

## 4. 설계

### 4.1 훅 정의

`plugin/cc-agora/hooks/hooks.json` (신규). 플러그인 루트의 `hooks/hooks.json`은
Claude Code가 자동 발견하므로 `plugin.json` 수정은 불필요하다.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo Context was just compacted. If you are an AgentAgora channel-mode worker, call agora.flush now to drain any unprocessed inbox messages, reply to each sender, then return to idle."
          }
        ]
      }
    ]
  }
}
```

훅 명령의 stdout이 워커 컨텍스트에 system-reminder로 주입된다.

### 4.2 안내문

한 줄 평문 영어. "If you are an AgentAgora channel-mode worker, ..." 조건절이 비워커
세션(orchestrator 등)의 가드 역할을 한다 — orchestrator는 조건을 읽고 자기 얘기가
아님을 알아 행동하지 않는다.

### 4.3 인라인 echo 안전 조건 (불변 제약)

`type: "command"` 훅의 명령 문자열은 cmd.exe(Windows)와 POSIX 셸 양쪽에서
실행된다. 안내문에 셸 메타문자가 들어가면 한쪽이 깨진다. **안내문은 글자·공백·
쉼표·마침표·하이픈만 쓴다.** 금지: 백틱(POSIX 명령 치환), `;` `|` `&` `<` `>`
`(` `)` `$` `"` `'` `!` `%` `^`. 명령은 따옴표로 감싸지 않는다 — cmd.exe는 따옴표를
리터럴로 출력한다.

특히 코드 식별자(`agora.flush` 등)에 백틱을 두르지 않는다. 이 제약은 §6 테스트로
락한다.

### 4.4 적용 범위

훅은 cc-agora 플러그인에 들어가므로 cc-agora가 켜진 모든 세션(채널 워커·
orchestrator·개발 세션)에서 발화한다. 세션별 판별 로직은 두지 않는다(brainstorm
Q1 결정). §4.2 조건절 문구로 비워커 세션이 스스로 제외된다.

## 5. 검토했다 접은 대안

- **`PostCompact` 훅** — side-effect 전용, 컨텍스트 주입 불가 (§3).
- **`type: "prompt"` 훅** — yes/no 결정 게이트, 텍스트 주입이 아님 (§3).
- **`PreCompact` 훅** — 컴팩션 차단은 가능하나 컨텍스트 주입 미지원. 선제 상태 보존은
  범위 밖 (§2).
- **Python 스크립트로 stdout 출력** — 멀티라인·백틱 안내문이면 필요했으나, 안내문을
  한 줄 평문으로 단순화해 불필요해졌다. 산출 파일 1개 절감.
- **`spawn.py`가 생성하는 `settings.local.json`에 hooks 블록 주입** — 신규 파일은
  0개지만 (a) 신규 spawn 워커만 적용되어 기존 fleet은 미적용, (b) 훅이 cc-agora가
  아니라 cc-agora-ops로 이동, (c) `spawn.py` + 그 테스트 수정 필요.
  `hooks/hooks.json` 한 파일이 더 작고 즉시 전체 적용된다.
- **Stop 훅** — 채널 모드 설계가 명시적으로 제거한 것. 재도입 시 idle 복귀가 깨진다.
- **스킬·CLAUDE.md에 문장 추가** — 스킬 본문은 컴팩션 요약에 함께 소실된다.
  CLAUDE.md는 매 턴 상존하나 "지금 컴팩션 직후인가"라는 트리거 신호가 없다. 훅은
  컴팩션 직후에만 발화하므로 발화 자체가 신호다.

## 6. 검증 / 테스트

`tests/`의 기존 `test_plugin_*` 패턴에 추가한다 (또는 `test_plugin_hooks.py` 신규).

1. `hooks/hooks.json`이 유효 JSON이고, `SessionStart`에 `matcher == "compact"`
   그룹이 있으며, 그 그룹의 `hooks`에 `type == "command"` 항목이 있다.
2. 명령 문자열이 핵심 의도 문구를 담는다 — `agora.flush`, `channel-mode worker`.
3. **메타문자 회귀 가드** — 명령 문자열에 §4.3 금지 문자가 없다. 안내문 편집 시
   백틱 등이 끼어드는 회귀를 잡는다.

## 7. 에러 처리

`SessionStart` 훅 실패는 non-blocking. `echo`가 어떤 이유로 실패해도 최악의 경우
"안내문 미주입 = 현재 동작"으로 fail-safe다. 명령은 `echo` 한 줄이라 실패 경로가
사실상 없다.

## 8. 파일 영향

| 파일 | 변경 |
|---|---|
| `plugin/cc-agora/hooks/hooks.json` | 신규 — 훅 정의 (수정 본체) |
| `plugin/cc-agora/README.md` | 갱신 — 훅 1종 문서화 |
| `docs/channel-mode.md` | 갱신 — 컴팩션 복구 훅 언급 |
| `tests/test_plugin_*` | 갱신/신규 — §6 테스트 |
| `docs/backlog.md` | 갱신 — 항목 문구를 `SessionStart(compact)`로 정정, 완료 시 항목 정리 |

5개 파일 — 구현 플랜에서 단계로 분해한다 (예: ① `hooks.json` + 테스트,
② 문서 갱신).
