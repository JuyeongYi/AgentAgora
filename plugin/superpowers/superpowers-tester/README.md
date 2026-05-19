# superpowers-tester

AgentAgora tester 역할 페르소나 플러그인이다. 이 플러그인은 워커가 tester 역할(모든 테스트 코드의 작성·실행·결과 분석, 구현자와의 TDD 핑퐁)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-tester"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-tester@agent-agora": true
  }
}
```
