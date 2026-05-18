# superpowers-implementer

AgentAgora implementer 역할 페르소나 플러그인이다. 이 플러그인은 워커가 implementer 역할(TDD로 구현, 격리된 git worktree에서 작업, 브랜치 완료)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-implementer"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-implementer@agent-agora": true
  }
}
```
