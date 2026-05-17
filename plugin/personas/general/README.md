# cc-agora-general

AgentAgora general 역할 페르소나 플러그인이다. 이 플러그인은 워커가 general 역할(전문 역할이 지정되지 않은 범용 폴백 워커)로 동작하도록 페르소나 스킬을 제공한다.

`cc-agora` 코어 플러그인에 의존하며, 채널 메시징·dispatch 등의 통신 기능은 `cc-agora`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"cc-agora"`와 `"cc-agora-general"`을 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": ["cc-agora", "cc-agora-general"]
}
```
