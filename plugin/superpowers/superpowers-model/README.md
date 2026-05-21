# superpowers-model

AgentAgora model 역할 페르소나 플러그인이다. 이 플러그인은 워커가 model 역할(데이터·상태·persistence·도메인 규칙 전담)로 동작하도록 페르소나 스킬을 제공한다. 데이터 구조·dataclass·schema 정의, DB/persistence 레이어, 검증 로직, 도메인 모델, model 단위 테스트를 담당하며, UI 렌더링·템플릿·라우트 핸들러·프레젠테이션은 다른 페르소나에 위임한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-model"`을 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-model@agent-agora": true
  }
}
```
