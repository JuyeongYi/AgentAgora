# superpowers-view

AgentAgora view 역할 페르소나 플러그인이다. 이 플러그인은 워커가 view 역할(프레젠테이션·UI·템플릿 전담)로 동작하도록 페르소나 스킬을 제공한다. HTML/템플릿, CSS, 클라이언트 JS(presentational), CLI output 포맷팅, 접근성, 시각 컴포넌트, view 단위 테스트를 담당하며, persistence·도메인 규칙·라우팅·비즈니스 로직은 다른 페르소나에 위임한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-view"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-view@agent-agora": true
  }
}
```
