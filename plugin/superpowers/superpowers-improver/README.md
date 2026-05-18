# superpowers-improver

superpowers 다중 에이전트 워크플로의 **improver** 페르소나 플러그인이다.

implementer 페르소나가 `finishing-a-development-branch`를 완료한 직후 트리거된다. 유저에게 개선 검토 여부를 묻고(게이트), 승인 시 완성된 결과물을 검토해 (a) 기능 개선, (b) 리팩토링 기회, (c) 추가 기능 아이디어를 findings로 정리한다. findings를 `agora.dispatch`로 planner 페르소나에게 넘겨 워크플로를 순환(ouroboros)시킨다.

## 활성화

워커의 `.claude/settings.local.json`에서 `enabledPlugins`에 `"superpowers-base@agent-agora"`와 `"superpowers-improver@agent-agora"`를 추가하면 페르소나가 적용된다.

```json
{
  "enabledPlugins": {
    "superpowers-base@agent-agora": true,
    "superpowers-improver@agent-agora": true
  }
}
```
