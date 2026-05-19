# superpowers-debugger

AgentAgora debugger 역할 페르소나 플러그인이다. 이 플러그인은 워커가 debugger 역할(버그·blocker를 체계적으로 분석해 근본 원인을 찾고 수정 검증 후 tester에게 제어를 반환)로 동작하도록 페르소나 스킬과 `systematic-debugging` 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 운용 스킬(using-superpowers, verification-before-completion, writing-skills)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-debugger"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agentagora": true,
    "superpowers-debugger@agentagora": true
  }
}
```
