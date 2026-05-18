# superpowers-planner

AgentAgora superpowers planner 역할 페르소나 플러그인이다. 이 플러그인은 워커가 planner 역할(아이디어 → spec → 구현 플랜 → router 핸드오프)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 워크플로 스킬(`using-superpowers`, `verification-before-completion`, `writing-skills`)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-planner"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-planner@agent-agora": true
  }
}
```

## 워크플로 위치

```
planner (brainstorming → writing-plans)
   │
   ▼  agora.dispatch → router
```

planner는 워크플로 진입점이다. 유저의 아이디어 또는 improver의 findings를 받아 brainstorming → writing-plans 순으로 실행하고, 완성된 플랜을 router 페르소나로 위임한다.
