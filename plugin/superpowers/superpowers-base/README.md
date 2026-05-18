# superpowers-base

superpowers 페르소나 플러그인들이 공통으로 의존하는 기반 라이브러리 플러그인이다.
스킬 탐색·사용법(`using-superpowers`), 완료 전 검증(`verification-before-completion`),
스킬 작성법(`writing-skills`) — 모든 페르소나 워커가 필요로 하는 공통 스킬 3종을 제공한다.

SessionStart 훅(`hooks/`)도 포함한다. 매 세션 시작 시 `using-superpowers` SKILL.md를
컨텍스트에 자동 주입해, 워커가 처음부터 스킬 사용법을 인지하도록 한다.

다른 superpowers 페르소나 플러그인(`superpowers-planner`, `superpowers-implementer` 등)은
이 플러그인을 `dependencies`로 선언한다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 추가한다:

```json
{
  "enabledPlugins": {
    "superpowers-base@agentagora": true
  }
}
```
