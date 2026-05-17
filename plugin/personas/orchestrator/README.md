# cc-agora-orchestrator

AgentAgora orchestrator 역할 페르소나 플러그인이다. 이 플러그인은 워커가 orchestrator 역할(사용자 요청을 적합한 워커에 위임하고 결과를 정리하는 팀 PM)로 동작하도록 페르소나 스킬을 제공한다.

`cc-agora` 코어 플러그인에 의존하며, 채널 메시징·dispatch 등의 통신 기능은 `cc-agora`가 제공한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"cc-agora"`와 `"cc-agora-orchestrator"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": ["cc-agora", "cc-agora-orchestrator"]
}
```
