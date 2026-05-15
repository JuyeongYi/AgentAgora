---
description: Temporarily disable this instance's Stop hook by backing up settings.local.json to .bak and clearing the hooks section.
---

# /cc-agora:agora-unwait

자기 인스턴스의 Stop hook을 일시 비활성한다. spec §4.5.

## 인자

없음.

## 동작

1. 자기 워커의 `.claude/settings.local.json` 경로를 확인한다. cwd 기준으로 찾는다.
2. 파일이 이미 백업(`.claude/settings.local.json.bak`)을 갖고 있으면 — 이전 unwait 이후 rewait를 안 한 상태 — no-op + 한국어 경고 "이미 unwait 상태입니다. 먼저 `/cc-agora:agora-rewait`를 실행하세요."를 출력하고 종료한다.
3. `settings.local.json`을 `settings.local.json.bak`로 복사한다(기존 .bak은 덮어쓰기, 한 단계 deep 복원만 지원).
4. 원본의 `hooks` 섹션을 제거하거나 빈 객체(`{}`)로 치환한다. 다른 키는 그대로 둔다.
5. 사용자에 한 줄 안내: "다음 wait는 호출되지 않습니다. 복원은 `/cc-agora:agora-rewait`."
6. **orchestrator (hook=none)** — `.claude/settings.local.json` 자체가 없는 경우 no-op + 안내 "orchestrator는 hook이 없습니다." 출력 후 종료한다.

## 구현 도구 선택

Read/Edit/Write 도구로 JSON을 안전하게 다루거나, Bash 도구로 `cp` + `python -c '...'`를 써도 된다. 모델 자율 판단. Windows에서 작업할 때 경로는 forward slash로 작성한다.

## 예시

```
/cc-agora:agora-unwait
```

`.claude/settings.local.json.bak`이 새로 생기고 원본의 hooks가 비워진다. 다음 Stop 이벤트에서 자동 wait가 발화하지 않는다.
