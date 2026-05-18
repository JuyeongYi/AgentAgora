# superpowers-router

Superpowers router 역할 페르소나 플러그인이다. planner가 작성·승인한 플랜을 받아, 병렬 처리 가능 여부를 판단한 뒤 implementer 워커에 task를 dispatch한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 보유 스킬

- `subagent-driven-development` — 순차 실행 경로: task를 순서대로 subagent에 dispatch하고 두 단계 리뷰(spec→quality)를 수행한다.
- `dispatching-parallel-agents` — 병렬 실행 경로: 독립적인 task를 동시에 parallel agent로 dispatch한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-router"`를 추가한다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-router@agent-agora": true
  }
}
```
