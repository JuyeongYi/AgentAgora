# superpowers-controller

AgentAgora controller 역할 페르소나 플러그인이다. 이 플러그인은 워커가 controller 역할(라우팅·요청 처리·model+view 조율 전담)로 동작하도록 페르소나 스킬을 제공한다. 라우트 핸들러, 요청 처리, command dispatch, 상태 머신, model-view 통합, controller 단위 테스트를 담당하며, 데이터 구조 정의(model 담당)·시각 표현(view 담당)은 다른 페르소나에 위임한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(using-superpowers, verification-before-completion, writing-skills)은 base가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-controller"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-controller@agent-agora": true
  }
}
```
