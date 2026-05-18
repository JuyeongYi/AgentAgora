# superpowers-reviewer

AgentAgora superpowers reviewer 역할 페르소나 플러그인이다. 이 플러그인은 워커가 reviewer 역할(코드 변경 리뷰·피드백 처리)로 동작하도록 페르소나 스킬을 제공한다.

`superpowers-base` 플러그인에 의존하며, 공통 스킬(skill 발견·완료 전 검증·스킬 작성)은 `superpowers-base`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base"`와 `"superpowers-reviewer"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agentagora": true,
    "superpowers-reviewer@agentagora": true
  }
}
```
